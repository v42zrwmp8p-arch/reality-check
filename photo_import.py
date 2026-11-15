"""Bounded anonymous retrieval and OCR of direct TikTok photo posts."""
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import ssl
import time
from urllib.parse import urljoin, urlsplit

from gallery_dl import config, extractor
from gallery_dl.extractor.common import Message
from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError
import pytesseract
import requests

from tiktok_import import ImportProblem, clean_tiktok_url

IMPORT_VERSION = "2026-11-15.3"
MAX_PHOTOS = 15
MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_TEXT_CHARS = 12000
TRUST_STORE = ssl.get_default_verify_paths().cafile or True
CDN_SUFFIXES = (".tiktokcdn.com", ".tiktokcdn-us.com", ".tiktokcdn-eu.com",
                ".ibytedtos.com", ".byteoversea.com")

# No user configuration, browser cookies, account login or persistent cache.
config.set(("extractor",), "retries", 0)
config.set(("extractor",), "timeout", 12)
config.set(("extractor",), "cookies", None)
config.set(("extractor",), "verify", TRUST_STORE)
config.set(("extractor", "tiktok"), "audio", False)
config.set(("extractor", "tiktok"), "videos", False)
config.set(("cache",), "file", None)


def _public_image_url(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and not parsed.username and not parsed.password
                and parsed.port is None and (parsed.hostname or "").endswith(CDN_SUFFIXES))
    except (TypeError, ValueError):
        return False


def _download_photo(session, url, path, remaining):
    """Follow only bounded HTTPS redirects to the known public TikTok CDNs."""
    try:
        for _ in range(3):
            if not _public_image_url(url):
                raise ImportProblem("This photo does not have a supported public image address.")
            with session.get(url, timeout=(8, 15), stream=True, verify=TRUST_STORE,
                             allow_redirects=False) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers.get("Location", ""))
                    continue
                if response.status_code != 200:
                    raise ImportProblem("A photo could not be downloaded from this server. Try another public post or use Manual Entry.")
                size = 0
                with Path(path).open("wb") as output:
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > MAX_PHOTO_BYTES or size > remaining:
                            raise ImportProblem("This photo post exceeds the 8 MB per image or 50 MB total limit.")
                        output.write(chunk)
                if not size:
                    raise ImportProblem("TikTok returned an empty image.")
                return size
    except requests.RequestException:
        raise ImportProblem("A photo could not be reached. Try again later or use Manual Entry.") from None
    raise ImportProblem("The image redirected too many times to process safely.")


def read_photo_text(original):
    """Keep the full reading, plus a bounded pass for light text over photos.

    Background texture can overwhelm sparse-text OCR even when an overlay is
    clear to a reader. Isolating bright, near-neutral lettering gives that
    overlay another chance without dropping the original chart/body text.
    The additional pass is optional: its timeout must not lose readable text.
    """
    image = ImageOps.autocontrast(ImageOps.grayscale(original))
    text = pytesseract.image_to_string(image, lang="eng", config="--psm 11", timeout=8).strip()
    overlay = original.convert("RGB")
    overlay.thumbnail((1600, 1600))
    red, green, blue = overlay.split()
    darkest = ImageChops.darker(ImageChops.darker(red, green), blue)
    lightest = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    bright = darkest.point(lambda value: 255 if value >= 210 else 0)
    neutral = ImageChops.subtract(lightest, darkest).point(lambda value: 255 if value <= 35 else 0)
    mask = ImageChops.multiply(bright, neutral)
    coverage = mask.histogram()[255] / (overlay.width * overlay.height)
    # A mostly white page or an image without light lettering needs no such pass.
    if not 0.001 <= coverage <= 0.35:
        return text
    try:
        extra = pytesseract.image_to_string(
            ImageOps.invert(mask), lang="eng", config="--psm 6", timeout=6,
        ).strip()
    except (RuntimeError, OSError, pytesseract.TesseractError):
        return text
    if extra and " ".join(extra.casefold().split()) not in " ".join(text.casefold().split()):
        return (text + "\n\n[Additional text reading]\n" + extra).strip()
    return text


def read_photo_post(url, folder, progress=None):
    """Return all readable image text/caption and safe platform metadata.

    The caller owns the temporary directory and deletes all media even when
    retrieval/OCR fails. No source image URLs are returned or logged.
    """
    url = clean_tiktok_url(url)
    if "/photo/" not in urlsplit(url).path:
        raise ImportProblem("Use the full TikTok photo link containing /photo/.")
    if not shutil.which("tesseract"):
        raise ImportProblem("The server's photo text reader is not installed. The app owner needs to finish setup.")
    expected_id = url.rsplit("/", 1)[-1]
    metadata, caption, images = {}, "", []
    started = time.monotonic()
    try:
        item = extractor.find(url)
        if item is None:
            raise ImportProblem("This photo link could not be read.")
        item.log.disabled = True

        def no_challenge_solving(html):
            raise ImportProblem("TikTok did not provide readable public post data from this server.")

        item._solve_challenge = no_challenge_solving
        item._sanitize_url = lambda value: clean_tiktok_url(value).replace("/photo/", "/video/", 1)
        for message in item:
            if time.monotonic() - started > 60:
                raise ImportProblem("TikTok took too long to provide this photo post.")
            if message[0] == Message.Directory:
                post = message[2]
                if str(post.get("id")) != expected_id or "imagePost" not in post:
                    raise ImportProblem("TikTok did not return the requested photo post.")
                count = len(post["imagePost"].get("images", []))
                if not 1 <= count <= MAX_PHOTOS:
                    raise ImportProblem(f"This prototype supports photo posts with up to {MAX_PHOTOS} images.")
                created = None
                try:
                    raw_time = post.get("createTime")
                    if isinstance(raw_time, bool):
                        raise ValueError
                    created = datetime.fromtimestamp(int(raw_time), timezone.utc).isoformat()
                except (TypeError, ValueError, OverflowError, OSError):
                    pass
                author = re.search(r"/@([A-Za-z0-9_.]+)/photo/", url)
                username = "@" + author[1] if author and not author[1].isdigit() else str(post.get("user") or "")
                metadata = {"createdAt": created, "author": {"username": username},
                            "stats": {"views": (post.get("stats") or {}).get("playCount")},
                            "video_id": expected_id, "photo_count": count, "source_kind": "photo"}
                caption = str(post.get("desc") or "").strip()
            elif message[0] == Message.Url and message[2].get("type") == "image":
                details = message[2]
                alternatives = details.get("image", {}).get("imageURL", {}).get("urlList", [])
                address = next((value for value in alternatives if _public_image_url(value)), message[1])
                images.append((address, details.get("num")))
                if len(images) > MAX_PHOTOS:
                    raise ImportProblem(f"This prototype supports up to {MAX_PHOTOS} photos per post.")
        if not metadata or len(images) != metadata["photo_count"]:
            raise ImportProblem("TikTok could not be read completely from this server. Use another public photo post or Manual Entry.")
        parts = ["[Post caption]\n" + caption] if caption else []
        total_bytes = 0
        for index, (address, _) in enumerate(images, 1):
            if progress:
                progress(f"Reading photo {index}/{len(images)}…")
            path = Path(folder) / f"photo-{index:02}.image"
            total_bytes += _download_photo(item.session, address, path, MAX_TOTAL_BYTES - total_bytes)
            try:
                with Image.open(path) as original:
                    if original.width * original.height > 20_000_000:
                        raise ImportProblem("An image is too large for this prototype's text reader.")
                    text = read_photo_text(original)
            except (UnidentifiedImageError, OSError, RuntimeError, pytesseract.TesseractError, Image.DecompressionBombError):
                raise ImportProblem(f"Text could not be read from photo {index}. Try another post or Manual Entry.") from None
            if text:
                parts.append(f"[Photo {index}]\n{text}")
            if sum(len(part) for part in parts) > MAX_TEXT_CHARS:
                raise ImportProblem("This photo post has too much text for this prototype. Use a smaller post or Manual Entry.")
        return "\n\n".join(parts), metadata
    except ImportProblem:
        raise
    except Exception:
        raise ImportProblem("The public photo post could not be processed. Try another post or use Manual Entry.") from None
