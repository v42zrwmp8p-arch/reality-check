"""Replay the recorded AMC failure and guard against invented financial targets."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch
import unittest

from target_extraction import recover_multiple
from test_tiktok_import import response
from video_pipeline import ImportTask, _process

ROOT = Path(__file__).resolve().parent
FIXTURE = json.loads((ROOT / "test_fixtures" / "amc_extraction.json").read_text())
AMC = FIXTURE["model_response"]["recommendations"][0]


class TargetExtractionChecks(unittest.TestCase):
    def test_recorded_miss_recovers_approximate_multiple_and_preserves_condition(self):
        original = deepcopy(AMC)
        row = recover_multiple([AMC], FIXTURE["transcript"], FIXTURE["screen_text"])[0]
        self.assertEqual((row["target_type"], row["target_value"]), ("multiple", 6))
        self.assertTrue(row["target_approximate"])
        self.assertEqual(row["reference_price"], 2.25)
        self.assertEqual(row["currency"], "USD")
        self.assertIn("if this success continues", row["claim"])
        self.assertIn("tiny punt", row["claim"].lower())
        self.assertIsNone(row["deadline"])
        self.assertIsNone(row["horizon_value"])
        self.assertEqual(AMC, original)

    @patch("tiktok_import.requests.post")
    def test_recorded_provider_response_through_real_processing_code(self, request):
        request.return_value = response({"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(FIXTURE["model_response"])}}]})
        task = ImportTask({"transcript": FIXTURE["transcript"], "screen_text": FIXTURE["screen_text"], "metadata": {}})
        result = _process(task, "https://www.tiktok.com/@fixture/video/123456", "fixture-private-key")
        self.assertTrue(result["ok"])
        row = result["data"]["drafts"][0]
        self.assertEqual(row["symbol"], "AMC")
        self.assertEqual(row["target_value"], 6)
        self.assertTrue(row["target_approximate"])
        self.assertEqual(row["reference_price"] * row["target_value"], 13.5)
        raw = json.loads(result["data"]["extraction_checks"][0]["raw_response_content"])
        self.assertEqual(raw["recommendations"][0]["target_type"], "none")
        self.assertEqual(request.call_count, 1)

    def test_valuation_and_historical_multiples_are_not_targets(self):
        for text in ["AMC could be attractive at 23 times forward earnings.",
                     "AMC could be a buy at 6x revenue.",
                     "AMC previously ran 6x during the last rally."]:
            with self.subTest(text=text):
                self.assertEqual(recover_multiple([AMC], text)[0]["target_type"], "none")

    def test_negated_and_teaching_examples_are_not_targets(self):
        for text in ["AMC could never rise 6x.", "Imagine AMC could rise 6x.",
                     "For example, AMC could rise 6x.", "If you bought AMC last year, it would be 6x."]:
            with self.subTest(text=text):
                self.assertEqual(recover_multiple([AMC], text)[0]["target_type"], "none")

    def test_other_asset_multiple_is_not_attached_to_amc(self):
        self.assertEqual(recover_multiple([AMC], "NVIDIA could rise nearly 6x.")[0]["target_type"], "none")

    def test_multiple_assets_or_competing_scenarios_are_not_guessed(self):
        other = dict(AMC, asset="Crocs", symbol="CROX")
        rows = recover_multiple([AMC, other], FIXTURE["transcript"])
        self.assertTrue(all(row["target_type"] == "none" for row in rows))
        text = "AMC could rise 6x. AMC could rise 10x."
        self.assertEqual(recover_multiple([AMC], text)[0]["target_type"], "none")

    def test_existing_conflicting_target_is_preserved(self):
        row = dict(AMC, target_type="price", target_value=20)
        self.assertEqual(recover_multiple([row], FIXTURE["transcript"])[0]["target_value"], 20)
        row = dict(AMC, target_type="multiple", target_value=10)
        self.assertEqual(recover_multiple([row], FIXTURE["transcript"])[0]["target_value"], 10)

    def test_spoken_number_and_matching_model_target_keep_approximation(self):
        row = recover_multiple([AMC], "AMC could rise nearly sixfold.")[0]
        self.assertEqual(row["target_value"], 6)
        self.assertTrue(row["target_approximate"])
        row = recover_multiple([AMC], "AMC could rise nearly 6x if revenue keeps improving.")[0]
        self.assertEqual(row["target_value"], 6)
        row = recover_multiple([dict(AMC, target_type="multiple", target_value=6)], FIXTURE["transcript"], "USD")[0]
        self.assertEqual(row["reference_price"], 2.25)
        self.assertTrue(row["target_approximate"])

    def test_dollar_sign_alone_does_not_establish_usd(self):
        row = recover_multiple([AMC], FIXTURE["transcript"], "")[0]
        self.assertEqual(row["reference_price"], 2.25)
        self.assertIsNone(row["currency"])


if __name__ == "__main__":
    unittest.main()
