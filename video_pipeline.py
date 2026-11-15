"""Bounded public-video processing, with shared results and no paid fallback."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from threading import BoundedSemaphore, Lock
import time
from urllib.parse import urlsplit

import pytesseract
from PIL import Image, ImageOps
import yt_dlp

from tiktok_import import GroqClient, ImportProblem, clean_tiktok_url
from asset_resolution import complete_drafts
from photo_import import read_photo_post

IMPORT_VERSION = "2026-11-15.2"

MAX_SECONDS = 180
MAX_VIDEO_BYTES = 50 * 1024 * 1024
MAX_FRAMES = 16
ENGINE_VERSION = "groq-whisper-ocr-v8"
# A release reload must not duplicate the queue or release another semaphore.
if "_POOL" not in globals():
    _POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="video-import")
    _SLOTS = BoundedSemaphore(8)
    _TASKS = OrderedDict()
    _LOCK = Lock()
CACHE_SECONDS = 24 * 60 * 60


def creator_name(info, original_url):
    """Prefer a handle from the canonical video URL; never show a numeric UID."""
    for url in [info.get("webpage_url"), original_url]:
        try:
            parsed = urlsplit(url or "")
            if parsed.hostname not in {"tiktok.com", "www.tiktok.com", "m.tiktok.com"}:
                continue
            found = re.match(r"/@([A-Za-z0-9_.]+)/video/", parsed.path)
            if found and not found[1].isdigit():
                return "@" + found[1]
        except ValueError:
            continue
    for field in ["uploader_id", "uploader"]:
        value = str(info.get(field) or "").strip()
        if value and not value.lstrip("@").isdigit():
            return value[:100]
    return ""


class _QuietLog:
    def debug(self, message): pass
    def warning(self, message): pass
    def error(self, message): pass


def _run_command(arguments, timeout):
    try:
        return subprocess.run(arguments, check=True, capture_output=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        raise ImportProblem("The video could not be processed on this server. Try another public video or use manual input.") from None


def read_video(url, folder):
    """Use standard public extraction only: no login cookies, proxies or access bypass."""
    url = clean_tiktok_url(url)
    started = time.monotonic()
    def guard(progress):
        if progress.get("downloaded_bytes", 0) > MAX_VIDEO_BYTES or time.monotonic() - started > 90:
            raise ImportProblem("This video is too large or slow to download. Try a shorter public clip.")
    options = {"quiet": True, "no_warnings": True, "logger": _QuietLog(), "noplaylist": True,
               "socket_timeout": 12, "retries": 0, "extractor_retries": 0, "fragment_retries": 0,
               "cachedir": False, "geo_bypass": False, "compat_opts": {"no-certifi"},
               "format": "worst[ext=mp4]/worst",
               "outtmpl": str(Path(folder) / "video.%(ext)s"), "max_filesize": MAX_VIDEO_BYTES,
               "progress_hooks": [guard]}
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=False)
            duration = info.get("duration") if isinstance(info, dict) else None
            if not isinstance(duration, (float, int)) or not 0 < duration <= MAX_SECONDS:
                raise ImportProblem("This prototype supports public videos up to three minutes with an available duration.")
            if info.get("is_live"):
                raise ImportProblem("Use a finished TikTok video rather than a live stream.")
            downloader.process_info(info)
    except ImportProblem:
        raise
    except Exception:
        # Downloader errors may contain temporary media URLs; do not expose or log them.
        raise ImportProblem("TikTok could not be downloaded from this server. The video may be restricted, unavailable or temporarily inaccessible. You can still use the curated or manual modes.") from None
    videos = [p for p in Path(folder).glob("video.*") if p.suffix in {".mp4", ".webm", ".mov", ".mkv"}]
    if not videos or not 0 < videos[0].stat().st_size <= MAX_VIDEO_BYTES:
        raise ImportProblem("No usable video was downloaded within the prototype's 50 MB limit.")
    published = None
    try:
        published = datetime.strptime(str(info.get("upload_date")), "%Y%m%d").date().isoformat()
    except ValueError:
        pass
    metadata = {"createdAt": published, "author": {"username": creator_name(info, url)},
                "stats": {"views": info.get("view_count")}, "video_id": str(info.get("id") or ""), "duration": duration}
    return videos[0], metadata


def prepare_audio(video, folder):
    if not shutil.which("ffmpeg"):
        raise ImportProblem("The server's audio processor is not installed. The app owner needs to finish deployment setup.")
    audio = Path(folder) / "audio.mp3"
    _run_command(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1", "-y",
                  "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(audio)], 45)
    if not audio.exists() or audio.stat().st_size == 0:
        raise ImportProblem("No usable audio track was found in the video.")
    return audio


def read_screen_text(video, duration, folder):
    """Sample up to sixteen frames. This is OCR, not full video understanding."""
    if not shutil.which("tesseract"):
        return "", "Screen text was not read because OCR is unavailable on this server. Review the original video for visual-only information."
    step = max(2.0, duration / MAX_FRAMES)
    pattern = str(Path(folder) / "frame-%03d.png")
    try:
        _run_command(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1", "-y",
                      "-i", str(video), "-vf", f"fps=1/{step},scale=640:-2", "-frames:v", str(MAX_FRAMES), pattern], 45)
        seen, lines = set(), []
        for i, frame in enumerate(sorted(Path(folder).glob("frame-*.png"))):
            with Image.open(frame) as original:
                image = ImageOps.autocontrast(ImageOps.grayscale(original))
                text = pytesseract.image_to_string(image, lang="eng", config="--psm 11", timeout=4).strip()
            compact = " ".join(text.split())
            if not compact or compact.casefold() in seen:
                continue
            seen.add(compact.casefold())
            second = int((i + 0.5) * step)
            lines.append(f"[{second // 60:02d}:{second % 60:02d}] {compact}")
        return "\n".join(lines)[:6000], "Screen text is sampled from up to 16 frames. Small or briefly shown text may be missed."
    except (ImportProblem, RuntimeError, OSError, pytesseract.TesseractError):
        return "", "Screen text could not be read. This result uses speech only; check visual-only names and targets against the original video."


class ImportTask:
    """Only source-derived checkpoints are shared; user edits stay in their session."""
    def __init__(self, checkpoint=None):
        self.created = time.time()
        self.progress = "Waiting for an analysis slot…"
        self.checkpoint = deepcopy(checkpoint or {})
        self.future = None
        self.retry_at = 0


def _process(task, url, api_key):
    data = task.checkpoint
    try:
        client = GroqClient(api_key)
        client.compatibility_mode = bool(data.get("compatibility_mode"))
        data.setdefault("source_kind", "photo" if "/photo/" in urlsplit(url).path else "video")
        if "source_text" not in data and "transcript" in data:
            data["source_text"] = data["transcript"]
        if "source_text" not in data:
            with tempfile.TemporaryDirectory(prefix="reality-check-") as folder:
                if data["source_kind"] == "photo":
                    task.progress = "Retrieving the public TikTok photos…"
                    text, data["metadata"] = read_photo_post(url, folder, lambda value: setattr(task, "progress", value))
                    data.update(source_text=text, photo_text=text, photo_count=data["metadata"]["photo_count"], screen_text="")
                else:
                    task.progress = "Retrieving the public TikTok video…"
                    video, data["metadata"] = read_video(url, folder)
                    task.progress = "Reading sampled on-screen text…"
                    data["screen_text"], data["screen_note"] = read_screen_text(video, data["metadata"]["duration"], folder)
                    task.progress = "Transcribing the speech with Groq…"
                    audio = prepare_audio(video, folder)
                    data["transcript"] = client.transcribe(audio)
                    data["source_text"] = data["transcript"]
            # Every original video/audio/frame/photo file is temporary.
        task.progress = "Identifying the investment predictions…"
        data["import_version"] = IMPORT_VERSION
        if not data["source_text"].strip() and not data.get("screen_text", "").strip():
            data["drafts"] = []
        else:
            if "raw_drafts" not in data:
                data["raw_drafts"] = client.extract(data["source_text"], data.get("screen_text", ""), source_kind=data["source_kind"])
                checks = getattr(client, "extraction_checks", [])
                data["extraction_checks"] = deepcopy(checks) if isinstance(checks, list) else []
            task.progress = "Matching names to tickers…"
            data["drafts"] = complete_drafts(data["raw_drafts"])
        data.pop("provider_error", None)
        data.pop("failed_stage", None)
        data["analysed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        data["compatibility_mode"] = client.compatibility_mode is True
        return {"ok": True, "data": deepcopy(data)}
    except ImportProblem as exc:
        data["provider_error"] = exc.provider_error
        data["compatibility_mode"] = getattr(locals().get("client"), "compatibility_mode", False) is True
        checks = getattr(locals().get("client"), "extraction_checks", [])
        if isinstance(checks, list):
            data["extraction_checks"] = deepcopy(checks)
        data["failed_stage"] = task.progress
        task.retry_at = time.time() + (max(1, exc.retry_after) if exc.retry_after is not None else 30)
        return {"ok": False, "error": str(exc), "retry_after": exc.retry_after, "data": deepcopy(data)}
    except Exception:
        data["compatibility_mode"] = getattr(locals().get("client"), "compatibility_mode", False) is True
        checks = getattr(locals().get("client"), "extraction_checks", [])
        if isinstance(checks, list):
            data["extraction_checks"] = deepcopy(checks)
        data["failed_stage"] = task.progress
        task.retry_at = time.time() + 30
        return {"ok": False, "error": "The post analysis did not complete. Please try again later or use Manual Entry.", "retry_after": None, "data": deepcopy(data)}


def submit_import(url, api_key, *, refresh=False):
    """Reuse in-flight/completed public analyses; at most two active, eight total."""
    url = clean_tiktok_url(url)
    if not isinstance(api_key, str) or not api_key.strip():
        raise ImportProblem("The Groq connection has not been configured yet.")
    identity = (ENGINE_VERSION, url, sha256(api_key.encode()).hexdigest())
    with _LOCK:
        now = time.time()
        for old_key, old_task in list(_TASKS.items()):
            if old_task.future.done() and now - old_task.created > CACHE_SECONDS:
                del _TASKS[old_key]
        existing = _TASKS.get(identity)
        if existing:
            _TASKS.move_to_end(identity)
            if (not existing.future.done() or now < existing.retry_at
                    or (existing.future.result()["ok"] and (not refresh or now < existing.created + 30))):
                return existing, True
        if not _SLOTS.acquire(blocking=False):
            raise ImportProblem("Several post analyses are already queued. Please try again shortly.")
        task = ImportTask(existing.checkpoint if existing else None)
        if refresh:
            for field in ["raw_drafts", "drafts", "analysed_at", "extraction_checks", "failed_stage", "provider_error"]:
                task.checkpoint.pop(field, None)
        try:
            task.future = _POOL.submit(_process, task, url, api_key)
        except Exception:
            _SLOTS.release()
            raise ImportProblem("An analysis slot could not be started. Please try again later.") from None
        task.future.add_done_callback(lambda future: _SLOTS.release())
        _TASKS[identity] = task
        for old_key, old_task in list(_TASKS.items()):
            if len(_TASKS) <= 32:
                break
            if old_key != identity and old_task.future.done():
                del _TASKS[old_key]
        return task, False
