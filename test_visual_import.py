"""Recorded OCR facts plus simulated API/reader boundaries; no live AI calls."""
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

from PIL import Image, ImageDraw

from photo_import import read_photo_text
from market_data import provider_symbol
from target_extraction import recover_visual_tables
from tiktok_import import GroqClient, ImportProblem
from test_tiktok_import import DRAFT, response
import video_pipeline as pipeline

ROOT = Path(__file__).resolve().parent
SOURCE = json.loads((ROOT / "test_fixtures" / "visual_slides_ocr.json").read_text())


def model_response(rows):
    return response({"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"recommendations": rows})}}]})


class VisualImportChecks(unittest.TestCase):
    @patch("tiktok_import.requests.post")
    def test_truncated_model_answer_keeps_literal_source_tables_without_an_extra_call(self, post):
        post.return_value = response({"choices": [{"finish_reason": "length", "message": {
            "content": '{"recommendations":['}}]})
        client = GroqClient("fixture-key")
        rows = client.extract(SOURCE["transcript"], SOURCE["text"])
        self.assertEqual(len(rows), 10)
        self.assertEqual(next(r for r in rows if r["symbol"] == "NVDA")["target_value"], 220)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"]["reasoning_effort"], "low")
        self.assertEqual(client.extraction_checks[0]["status"], "invalid_response")
        self.assertTrue(all(r["currency"] is None for r in rows))

    @patch("tiktok_import.requests.post")
    def test_invalid_response_without_source_facts_and_provider_errors_are_not_hidden(self, post):
        post.return_value = response({"choices": [{"finish_reason": "length", "message": {
            "content": '{"recommendations":['}}]})
        with self.assertRaises(ImportProblem):
            GroqClient("fixture-key").extract("Pancake recipe", "")
        post.return_value = response({}, status=429)
        with self.assertRaises(ImportProblem) as raised:
            GroqClient("fixture-key").extract(SOURCE["transcript"], SOURCE["text"])
        self.assertEqual(raised.exception.provider_error["http_status"], 429)

    def test_recorded_ocr_recovers_ten_targets_without_inventing_dates_or_currency(self):
        rows = recover_visual_tables([], SOURCE["text"])
        expected = [[provider_symbol(symbol, "Equity"), target] for symbol, target in SOURCE["expected"]]
        self.assertEqual([[row["symbol"], row["target_value"]] for row in rows], expected)
        for row in rows:
            self.assertEqual(row["time_frame"], "2025")
            self.assertIsNone(row["deadline"])
            self.assertIsNone(row["currency"])
            self.assertLessEqual(len(row["evidence"].split()), 20)

    @patch("tiktok_import.requests.post")
    def test_music_and_empty_model_result_still_recover_literal_screen_predictions(self, post):
        post.return_value = model_response([])
        rows = GroqClient("fixture-key").extract(SOURCE["transcript"], SOURCE["text"])
        self.assertEqual(len(rows), 10)
        self.assertEqual(post.call_count, 1)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "openai/gpt-oss-20b")
        self.assertNotIn("image_url", json.dumps(payload))
        self.assertIn("Sampled on-screen text is an independent source", payload["messages"][0]["content"])

    def test_partial_model_details_and_single_letter_ticker_are_preserved_separately(self):
        amd = dict(DRAFT, asset="AMD", symbol="AMD", claim="Original condition",
                   evidence="AMD NOW:S$119.21", target_type="none")
        rows = recover_visual_tables([amd], SOURCE["text"])
        self.assertEqual(len(rows), 10)
        self.assertEqual(next(row for row in rows if row["symbol"] == "AMD")["claim"], "Original condition")
        self.assertEqual(next(row for row in rows if row["symbol"] == "AMD")["target_value"], 180)
        self.assertEqual(next(row for row in rows if row["symbol"] == "S")["target_value"], 50)
        self.assertEqual(amd["target_type"], "none")

    def test_named_literal_ticker_without_model_symbol_does_not_create_a_duplicate(self):
        missing_symbol = dict(DRAFT, asset="S", symbol=None, target_value=50,
                              evidence="S NOW : $22.43 2025: $50", time_frame="2025")
        rows = recover_visual_tables([missing_symbol], SOURCE["text"])
        self.assertEqual(len(rows), 10)
        matches = [row for row in rows if row["symbol"] == "S"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["currency"], "USD")
        self.assertIsNone(missing_symbol["symbol"])

    def test_renamed_ticker_merges_with_current_model_identity(self):
        block = dict(DRAFT, asset="Block, Inc.", symbol="XYZ", target_value=120,
                     evidence="SQ NOW: $89.65 2025: $120", time_frame="2025")
        rows = recover_visual_tables([block], SOURCE["text"])
        self.assertEqual(len(rows), 10)
        matches = [row for row in rows if row["symbol"] == "XYZ"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["target_value"], 120)
        self.assertEqual(matches[0]["currency"], "USD")

    def test_ambiguous_conflicting_and_negative_tables_are_not_recovered(self):
        table = "[00:01]\nTop growth stocks for 2025\nZZZZ\nNOW: $10\n2025: $20"
        self.assertEqual(len(recover_visual_tables([], table)), 1)
        for invalid in [table.replace("Top growth stocks", "Historical stocks"),
                        table.replace("Top growth stocks", "Top stocks not to buy"),
                        table.replace("ZZZZ", "ZZZZ\nBBBB"),
                        table.replace("NOW: $10", "NOW: $10\nNOW: $11"),
                        table.replace("2025: $20", "2025: $5"),
                        table.replace("2025: $20", "2025: 20"),
                        table + "\n[00:03]\nZZZZ\nNOW: $10\n2025: $30"]:
            with self.subTest(source=invalid):
                self.assertEqual(recover_visual_tables([], invalid), [])
        self.assertEqual(recover_visual_tables([], table, "Do not buy any of these stocks."), [])

    @patch("tiktok_import.requests.post")
    def test_recheck_keeps_later_frames_beyond_two_thousand_characters(self, post):
        post.return_value = model_response([])
        text = "[00:01]\n" + "ordinary screen text " * 180 + "\n[00:29]\nFINAL_FRAME"
        self.assertEqual(GroqClient("fixture-key").extract("Music", text), [])
        self.assertEqual(post.call_count, 2)
        for call in post.call_args_list:
            sent = json.loads(call.kwargs["json"]["messages"][1]["content"])
            self.assertIn("FINAL_FRAME", sent["sampled_screen_text"])

    @patch("video_pipeline.shutil.which", return_value="tesseract")
    @patch("video_pipeline.read_photo_text", side_effect=["first reading", RuntimeError("fixture timeout"), "last reading"])
    @patch("video_pipeline._run_command")
    def test_one_unreadable_frame_does_not_discard_other_source_text(self, command, read, binary):
        with tempfile.TemporaryDirectory() as folder:
            command.side_effect = lambda *args: self._frames(folder, 3)
            text, note = pipeline.read_screen_text(Path("unused.mp4"), 6, folder)
        self.assertIn("[00:01]\nfirst reading", text)
        self.assertIn("[00:05]\nlast reading", text)
        self.assertIn("1 sampled frame", note)

    @patch("video_pipeline.shutil.which", return_value="tesseract")
    @patch("video_pipeline.read_photo_text")
    @patch("video_pipeline._run_command")
    def test_dense_early_readings_keep_the_last_frame_and_highlighted_text(self, command, read, binary):
        read.side_effect = ["x" * 7000 + f"\n[Highlighted text]\nPICK_{i}" for i in range(16)]
        with tempfile.TemporaryDirectory() as folder:
            command.side_effect = lambda *args: self._frames(folder, 16)
            text, _ = pipeline.read_screen_text(Path("unused.mp4"), 32, folder)
        self.assertLessEqual(len(text), 6000)
        for i in range(16):
            self.assertIn(f"PICK_{i}", text)
        self.assertIn("[00:31]", text)

    @patch("photo_import.pytesseract.image_to_string")
    def test_colour_reading_recovers_letters_and_retains_primary_on_timeout(self, read):
        image = Image.new("RGB", (200, 200), "black")
        ImageDraw.Draw(image).rectangle((30, 70, 160, 90), fill=(0, 255, 0))
        read.side_effect = ["Primary chart context", "ABCD NOW: $10 2028: $20"]
        text = read_photo_text(image, light_text=False)
        self.assertIn("Primary chart context", text)
        self.assertIn("[Highlighted text]\nABCD", text)
        read.side_effect = ["Primary chart context", RuntimeError("fixture timeout")]
        self.assertEqual(read_photo_text(image, light_text=False), "Primary chart context")

    @staticmethod
    def _frames(folder, count):
        for i in range(count):
            Image.new("RGB", (80, 80), "white").save(Path(folder) / f"frame-{i + 1:03d}.png")


if __name__ == "__main__":
    unittest.main()
