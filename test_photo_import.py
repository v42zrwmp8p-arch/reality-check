"""Photo import boundaries. Media/OCR/API fixtures are explicitly simulated."""
from concurrent.futures import Future
from datetime import date
import json
from pathlib import Path
import tempfile
from unittest.mock import Mock, MagicMock, patch
import unittest

from gallery_dl.extractor.common import Message
from PIL import Image, ImageDraw

import photo_import as photos
from test_tiktok_import import DRAFT, response
from tiktok_import import GroqClient, ImportProblem
import video_pipeline as pipeline

PHOTO = "https://www.tiktok.com/@drewhelpss/photo/7453626334099590406"
SOURCE = "[Post caption]\nStocks to watch\n\n[Photo 1]\nPalantir PLTR could grow."
META = {"createdAt": "2024-12-29T00:37:05+00:00", "author": {"username": "@drewhelpss"},
        "stats": {"views": 100}, "photo_count": 1, "source_kind": "photo"}


def fake_extractor(count=2, returned=None):
    post = {"id": PHOTO.rsplit("/", 1)[-1], "createTime": 1735432625,
            "imagePost": {"images": [{} for _ in range(count)]}, "stats": {"playCount": 100},
            "desc": "Stocks to watch", "user": "123456789"}
    messages = [(Message.Directory, "", post)]
    for index in range(count if returned is None else returned):
        url = f"https://p16-common-sign.tiktokcdn-eu.com/photo-{index}.webp"
        messages.append((Message.Url, url, {"type": "image", "num": index + 1,
                         "image": {"imageURL": {"urlList": [url]}}}))
    item = Mock()
    item.__iter__ = Mock(return_value=iter(messages))
    return item


def fake_download(session, url, path, remaining):
    Image.new("RGB", (80, 80), "white").save(path, format="PNG")
    return Path(path).stat().st_size


class PhotoReaderChecks(unittest.TestCase):
    @patch("photo_import.shutil.which", return_value="tesseract")
    @patch("photo_import.extractor.find")
    @patch("photo_import._download_photo")
    @patch("photo_import.pytesseract.image_to_string")
    def test_overlay_reading_restores_buy_context_and_keeps_original_text(self, ocr, download, find, binary):
        # Simulate a readable light headline over a textured/dark cover.
        def cover(session, url, path, remaining):
            image = Image.new("RGB", (200, 200), "darkgreen")
            ImageDraw.Draw(image).rectangle((30, 70, 160, 90), fill="white")
            image.save(path, format="PNG")
            return Path(path).stat().st_size
        download.side_effect = cover
        find.return_value = fake_extractor(count=1)
        ocr.side_effect = ["STOCKS / You should Be), 2 / right now", "STOCKS\nYou should buy\nright now"]
        with tempfile.TemporaryDirectory() as folder:
            text, metadata = photos.read_photo_post(PHOTO, folder)
        self.assertIn("[Photo 1]\nSTOCKS / You should Be)", text)
        self.assertIn("[Additional text reading]\nSTOCKS\nYou should buy\nright now", text)
        self.assertIn("[Post caption]\nStocks to watch", text)
        self.assertEqual(metadata["photo_count"], 1)
        self.assertEqual(ocr.call_count, 2)

    @patch("photo_import.pytesseract.image_to_string")
    def test_optional_overlay_timeout_retains_readable_primary_text(self, ocr):
        image = Image.new("RGB", (200, 200), "darkgreen")
        ImageDraw.Draw(image).rectangle((30, 70, 160, 90), fill="white")
        ocr.side_effect = ["ASML Holding N.V. 708.62", RuntimeError("fixture timeout")]
        self.assertEqual(photos.read_photo_text(image), "ASML Holding N.V. 708.62")
        self.assertEqual(ocr.call_count, 2)

    @patch("photo_import.shutil.which", return_value="tesseract")
    @patch("photo_import.extractor.find")
    @patch("photo_import._download_photo", side_effect=fake_download)
    @patch("photo_import.pytesseract.image_to_string", side_effect=["July 2024 PLTR", "AVGO"])
    def test_every_photo_and_caption_read_with_platform_date_and_url_creator(self, ocr, download, find, binary):
        find.return_value = fake_extractor()
        with tempfile.TemporaryDirectory() as folder:
            text, metadata = photos.read_photo_post(PHOTO, folder)
            self.assertEqual(len(list(Path(folder).iterdir())), 2)
        self.assertIn("[Post caption]\nStocks to watch", text)
        self.assertIn("[Photo 1]\nJuly 2024 PLTR", text)
        self.assertIn("[Photo 2]\nAVGO", text)
        self.assertTrue(metadata["createdAt"].startswith("2024-12-29"))
        self.assertEqual(metadata["author"]["username"], "@drewhelpss")
        self.assertEqual(metadata["photo_count"], 2)
        self.assertNotIn("tiktokcdn", json.dumps(metadata))
        self.assertEqual(download.call_count, 2)
        with self.assertRaises(ImportProblem):
            find.return_value._solve_challenge("blocked")

    @patch("photo_import.shutil.which", return_value="tesseract")
    @patch("photo_import.extractor.find")
    @patch("photo_import._download_photo")
    def test_large_or_incomplete_carousel_rejected_before_download(self, download, find, binary):
        for count, returned in [(16, 16), (2, 1), (0, 0)]:
            find.return_value = fake_extractor(count, returned)
            with self.subTest(count=count), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ImportProblem):
                    photos.read_photo_post(PHOTO, folder)
        download.assert_not_called()

    @patch("photo_import.shutil.which", return_value="tesseract")
    @patch("photo_import.extractor.find")
    @patch("photo_import._download_photo", side_effect=fake_download)
    @patch("photo_import.pytesseract.image_to_string", side_effect=RuntimeError("fixture timeout"))
    def test_ocr_failure_does_not_return_a_silent_partial_result(self, ocr, download, find, binary):
        find.return_value = fake_extractor()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ImportProblem, "photo 1"):
                photos.read_photo_post(PHOTO, folder)

    def test_image_url_and_redirect_boundaries(self):
        self.assertTrue(photos._public_image_url("https://p16.tiktokcdn-eu.com/image?signature=fixture"))
        session = MagicMock()
        for url in ["http://p16.tiktokcdn.com/image", "https://127.0.0.1/image",
                    "https://p16.tiktokcdn.com.evil.test/image", "https://user@p16.tiktokcdn.com/image"]:
            with self.subTest(url=url), self.assertRaises(ImportProblem):
                photos._download_photo(session, url, "unused", 100)
        session.get.assert_not_called()
        reply = Mock(status_code=302, headers={"Location": "https://evil.test/image"})
        session.get.return_value.__enter__.return_value = reply
        with self.assertRaises(ImportProblem):
            photos._download_photo(session, "https://p16.tiktokcdn.com/image", "unused", 100)
        self.assertEqual(session.get.call_count, 1)

    def test_streamed_image_limit_is_enforced(self):
        session = MagicMock()
        reply = Mock(status_code=200)
        reply.iter_content.return_value = [b"123", b"456"]
        session.get.return_value.__enter__.return_value = reply
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ImportProblem, "limit"):
                photos._download_photo(session, "https://p16.tiktokcdn.com/image", Path(folder) / "x", 5)
        self.assertIsNot(session.get.call_args.kwargs["verify"], False)


class PhotoPipelineChecks(unittest.TestCase):
    def setUp(self):
        with pipeline._LOCK:
            pipeline._TASKS.clear()

    @patch("video_pipeline.read_video")
    @patch("video_pipeline.prepare_audio")
    @patch("video_pipeline.read_photo_post")
    @patch("video_pipeline.GroqClient")
    def test_photo_uses_ocr_only_and_retains_text_for_extraction_retry(self, client, read, audio, video):
        folders = []
        def reader(url, folder, progress):
            folders.append(Path(folder))
            (Path(folder) / "fixture.png").write_bytes(b"fixture")
            return SOURCE, META
        read.side_effect = reader
        client.return_value.extract.side_effect = [ImportProblem("fixture limit", retry_after=1), [DRAFT], [DRAFT]]
        first, _ = pipeline.submit_import(PHOTO, "fixture-key")
        self.assertFalse(first.future.result(timeout=5)["ok"])
        self.assertTrue(all(not path.exists() for path in folders))
        first.retry_at = 0
        retried, _ = pipeline.submit_import(PHOTO, "fixture-key")
        data = retried.future.result(timeout=5)["data"]
        self.assertEqual(data["source_kind"], "photo")
        self.assertEqual(data["photo_text"], SOURCE)
        self.assertEqual(read.call_count, 1)
        client.return_value.extract.assert_called_with(SOURCE, "", source_kind="photo")
        client.return_value.transcribe.assert_not_called()
        video.assert_not_called(); audio.assert_not_called()
        retried.created -= 60
        refreshed, _ = pipeline.submit_import(PHOTO, "fixture-key", refresh=True)
        self.assertTrue(refreshed.future.result(timeout=5)["ok"])
        self.assertEqual(read.call_count, 1)

    @patch("video_pipeline.read_photo_post", return_value=("", META))
    @patch("video_pipeline.GroqClient")
    def test_blank_photo_post_does_not_call_model(self, client, read):
        task, _ = pipeline.submit_import(PHOTO, "fixture-key")
        self.assertEqual(task.future.result(timeout=5)["data"]["drafts"], [])
        client.return_value.extract.assert_not_called()

    @patch("tiktok_import.requests.post")
    def test_photo_text_sent_once_and_photo_evidence_preserved(self, request):
        draft = dict(DRAFT, evidence_time="Photo 2")
        request.return_value = response({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"recommendations": [draft]})}}]})
        rows = GroqClient("fixture-key").extract(SOURCE, "", source_kind="photo")
        payload = request.call_args.kwargs["json"]
        self.assertEqual(json.loads(payload["messages"][1]["content"]), {"photo_text": SOURCE})
        self.assertEqual(rows[0]["evidence_time"], "Photo 2")
        self.assertEqual(request.call_count, 1)


class PhotoUiChecks(unittest.TestCase):
    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    @patch("market_data.download_history")
    def test_photo_review_calculation_report_clear_and_switch_back_to_video(self, download, submit, key):
        import pandas as pd
        from test_tiktok_ui import app, completed, ROOT
        from tiktok_ui import import_report
        task = pipeline.ImportTask(); task.future = Future()
        task.future.set_result({"ok": True, "data": {"metadata": dict(META, photo_count=5),
                               "source_kind": "photo", "source_text": SOURCE, "photo_text": SOURCE,
                               "photo_count": 5, "drafts": [DRAFT, dict(DRAFT, asset="Crocs", symbol="CROX")]}})
        submit.return_value = task, False
        # Saved SPY observations are only a functional UI fixture, not a photo-stock backtest.
        frame = pd.read_csv(ROOT / "prices" / "SPY.csv", index_col="Date", parse_dates=True)
        download.side_effect = lambda *args: (frame.copy(), args[0])
        at = app(); at.text_input(key="tt_link").set_value(PHOTO).run()
        at.button(key="tt_analyse").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.date_input(key="tt_review_0_published").value, date(2024, 12, 29))
        self.assertEqual(at.text_input(key="tt_review_0_creator").value, "@drewhelpss")
        self.assertIn("Extracted text", [x.label for x in at.expander])
        self.assertNotIn("Transcript", [x.label for x in at.expander])
        self.assertTrue(any(x.value == "5 photos · 2 recommendations found" for x in at.caption))
        report = import_report(at.session_state["tt_import"])
        self.assertEqual(report["photo_text"], SOURCE)
        self.assertEqual(report["source_kind"], "photo")
        self.assertEqual(len(at.selectbox(key="tt_choice").options), 2)
        at.button(key="tt_calculate").click().run()
        self.assertFalse(at.exception); self.assertFalse(at.error)
        self.assertEqual(at.session_state["tt_result"]["row"]["source_kind"], "photo")
        at.button(key="tt_clear").click().run()
        self.assertEqual(at.text_input(key="tt_link").value, "")
        submit.return_value = completed([DRAFT]), False
        from test_tiktok_import import VIDEO
        at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        self.assertIn("Transcript", [x.label for x in at.expander])
        self.assertNotIn("Extracted text", [x.label for x in at.expander])
        self.assertFalse(at.exception)


if __name__ == "__main__":
    unittest.main()
