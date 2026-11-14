"""Pipeline lifecycle/cache checks. API and download responses are fixtures."""
from pathlib import Path
import tempfile
from threading import Event
import time
from unittest.mock import patch
import unittest

from test_tiktok_import import VIDEO, DRAFT
from tiktok_import import ImportProblem
import video_pipeline as pipeline


class PipelineChecks(unittest.TestCase):
    def setUp(self):
        with pipeline._LOCK:
            pipeline._TASKS.clear()

    @patch("video_pipeline.GroqClient")
    @patch("video_pipeline.read_screen_text", return_value=("MRVL 142", "Fixture OCR"))
    @patch("video_pipeline.prepare_audio")
    @patch("video_pipeline.read_video")
    def test_cleanup_completed_cache_and_key_rotation(self, read, audio, screen, client):
        folders = []
        def video(url, folder):
            folders.append(Path(folder)); p = Path(folder) / "video.mp4"; p.write_bytes(b"fixture")
            return p, {"duration": 60, "createdAt": "2023-06-26", "author": {}, "stats": {}}
        def prepare(video, folder):
            p = Path(folder) / "audio.mp3"; p.write_bytes(b"fixture"); return p
        read.side_effect = video; audio.side_effect = prepare
        client.return_value.transcribe.return_value = "Marvell could reach 142"
        client.return_value.extract.return_value = [DRAFT]
        first, reused = pipeline.submit_import(VIDEO, "fixture-key")
        self.assertFalse(reused)
        self.assertTrue(first.future.result(timeout=5)["ok"])
        self.assertTrue(all(not folder.exists() for folder in folders))
        second, reused = pipeline.submit_import(VIDEO + "?tracking=remove", "fixture-key")
        self.assertIs(first, second); self.assertTrue(reused)
        self.assertEqual(client.return_value.transcribe.call_count, 1)
        rotated, reused = pipeline.submit_import(VIDEO, "different-fixture-key")
        self.assertFalse(reused); self.assertTrue(rotated.future.result(timeout=5)["ok"])
        self.assertEqual(client.return_value.transcribe.call_count, 2)
        self.assertTrue(all(not folder.exists() for folder in folders))

    @patch("video_pipeline.GroqClient")
    @patch("video_pipeline.read_screen_text", return_value=("", "Fixture"))
    @patch("video_pipeline.prepare_audio", return_value=Path("unused-fixture.mp3"))
    @patch("video_pipeline.read_video", return_value=(Path("unused-fixture.mp4"), {"duration": 60}))
    def test_limit_resumes_without_repeating_completed_transcription(self, read, audio, screen, client):
        client.return_value.transcribe.return_value = "Marvell could reach 142"
        client.return_value.extract.side_effect = [ImportProblem("Fixture limit", retry_after=120), [DRAFT]]
        first, _ = pipeline.submit_import(VIDEO, "fixture-key")
        self.assertFalse(first.future.result(timeout=5)["ok"])
        held, reused = pipeline.submit_import(VIDEO, "fixture-key")
        self.assertIs(first, held); self.assertTrue(reused)
        first.retry_at = time.time() - 1
        resumed, reused = pipeline.submit_import(VIDEO, "fixture-key")
        self.assertFalse(reused); self.assertTrue(resumed.future.result(timeout=5)["ok"])
        self.assertEqual(read.call_count, 1)
        self.assertEqual(client.return_value.transcribe.call_count, 1)
        self.assertEqual(client.return_value.extract.call_count, 2)

    @patch("video_pipeline._process")
    def test_duplicate_inflight_requests_share_work(self, process):
        waiting = Event(); release = Event()
        def work(*args):
            waiting.set(); release.wait(timeout=5)
            return {"ok": True, "data": {}}
        process.side_effect = work
        try:
            first, _ = pipeline.submit_import(VIDEO, "fixture-key")
            self.assertTrue(waiting.wait(timeout=2))
            duplicate, reused = pipeline.submit_import(VIDEO, "fixture-key")
            self.assertIs(first, duplicate); self.assertTrue(reused)
        finally:
            release.set()
        self.assertTrue(first.future.result(timeout=5)["ok"])
        self.assertEqual(process.call_count, 1)

    @patch("video_pipeline.GroqClient")
    @patch("video_pipeline.read_screen_text", return_value=("", "Fixture"))
    @patch("video_pipeline.prepare_audio", return_value=Path("unused-fixture.mp3"))
    @patch("video_pipeline.read_video", return_value=(Path("unused-fixture.mp4"), {"duration": 60}))
    def test_silent_empty_video_does_not_invent_recommendations(self, read, audio, screen, client):
        client.return_value.transcribe.return_value = ""
        task, _ = pipeline.submit_import(VIDEO, "fixture-key")
        result = task.future.result(timeout=5)
        self.assertTrue(result["ok"]); self.assertEqual(result["data"]["drafts"], [])
        client.return_value.extract.assert_not_called()

    @patch("video_pipeline.yt_dlp.YoutubeDL")
    def test_long_video_rejected_before_download(self, downloader):
        extractor = downloader.return_value.__enter__.return_value
        extractor.extract_info.return_value = {"duration": 181}
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ImportProblem, "three minutes"):
                pipeline.read_video(VIDEO, folder)
        extractor.process_info.assert_not_called()

    @patch("video_pipeline._SLOTS.acquire", return_value=False)
    def test_busy_queue_returns_a_message(self, acquire):
        with self.assertRaisesRegex(ImportProblem, "queued"):
            pipeline.submit_import(VIDEO, "fixture-key")

    @patch("video_pipeline.GroqClient")
    @patch("video_pipeline.read_screen_text", return_value=("", "Fixture"))
    @patch("video_pipeline.prepare_audio", return_value=Path("unused-fixture.mp3"))
    @patch("video_pipeline.read_video", return_value=(Path("unused-fixture.mp4"), {"duration": 60}))
    def test_explicit_recheck_reuses_media_and_has_cooldown(self, read, audio, screen, client):
        client.return_value.transcribe.return_value = "Fixture speech"
        client.return_value.extract.side_effect = [[], [DRAFT]]
        task, _ = pipeline.submit_import(VIDEO, "fixture-key")
        self.assertEqual(task.future.result(timeout=5)["data"]["drafts"], [])
        held, reused = pipeline.submit_import(VIDEO, "fixture-key", refresh=True)
        self.assertIs(held, task); self.assertTrue(reused)
        task.created -= 60
        refreshed, reused = pipeline.submit_import(VIDEO, "fixture-key", refresh=True)
        self.assertFalse(reused)
        self.assertEqual(refreshed.future.result(timeout=5)["data"]["drafts"][0]["symbol"], "MRVL")
        self.assertEqual(read.call_count, 1)
        self.assertEqual(audio.call_count, 1)
        self.assertEqual(client.return_value.transcribe.call_count, 1)
        self.assertEqual(client.return_value.extract.call_count, 2)


if __name__ == "__main__":
    unittest.main()
