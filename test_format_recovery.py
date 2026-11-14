"""Recorded input, explicitly simulated HTTP failures and fallback outputs."""
import json
from pathlib import Path
from unittest.mock import patch
import unittest

from test_tiktok_import import DRAFT, response, VIDEO
from tiktok_import import GroqClient, ImportProblem
from video_pipeline import ImportTask, _process

SOURCE = json.loads((Path(__file__).resolve().parent / "test_fixtures" / "stockdads_request.json").read_text())
ROWS = [dict(DRAFT, asset=name, symbol=symbol, target_type="none", target_value=None,
             time_frame="2024 and 2025", currency=None, evidence=None,
             claim="Bullish for 2024 and 2025.")
        for name, symbol in [("UWM Holdings", "UWMC"), ("Bank of America", "BAC"),
                             ("Albemarle", "ALB"), ("Enphase Energy", "ENPH"), ("Perion Network", "PERI")]]


def rejected():
    return response({"error": {"type": "invalid_request_error", "code": "json_validate_failed",
                               "message": "Fixture output did not match the schema."}}, status=400)


def accepted(rows=ROWS):
    return response({"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"recommendations": rows})}}]})


class FormatRecoveryChecks(unittest.TestCase):
    @patch("tiktok_import.requests.post")
    def test_exact_provider_error_is_retained_and_credentials_redacted(self, post):
        post.return_value = response({"error": {"type": "invalid_request_error", "code": "fixture_code",
                                               "message": "Rejected fixture-private-key", "failed_generation": "fixture-private-key"}}, status=400)
        with self.assertRaises(ImportProblem) as raised:
            GroqClient("fixture-private-key")._post("/chat/completions", body={})
        details = raised.exception.provider_error
        self.assertEqual(details["http_status"], 400)
        self.assertEqual(details["code"], "fixture_code")
        self.assertNotIn("fixture-private-key", json.dumps(details))
        self.assertNotIn("shorter video", str(raised.exception))

    @patch("tiktok_import.requests.post")
    def test_rejected_schema_switches_protocol_once_and_recovers_multiple_assets(self, post):
        post.side_effect = [rejected(), accepted()]
        client = GroqClient("fixture-key")
        rows = client.extract(SOURCE["transcript"], SOURCE["screen_text"])
        self.assertEqual([row["symbol"] for row in rows], ["UWMC", "BAC", "ALB", "ENPH", "PERI"])
        self.assertTrue(all(row["target_type"] == "none" for row in rows))
        self.assertTrue(client.compatibility_mode)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].kwargs["json"]["response_format"]["type"], "json_schema")
        self.assertEqual(post.call_args_list[1].kwargs["json"]["response_format"]["type"], "json_object")
        self.assertEqual(client.extraction_checks[0]["provider_error"]["code"], "json_validate_failed")
        self.assertEqual(client.extraction_checks[1]["status"], "parsed")

    @patch("tiktok_import.requests.post")
    def test_second_rejection_stops_without_loop(self, post):
        post.side_effect = [rejected(), rejected()]
        client = GroqClient("fixture-key")
        with self.assertRaises(ImportProblem):
            client.extract(SOURCE["transcript"], SOURCE["screen_text"])
        self.assertEqual(post.call_count, 2)
        self.assertEqual(len(client.extraction_checks), 2)

    @patch("tiktok_import.requests.post")
    def test_json_mode_output_must_pass_the_same_local_schema(self, post):
        malformed = dict(ROWS[0], unexpected="extra field")
        post.side_effect = [rejected(), accepted([malformed])]
        client = GroqClient("fixture-key")
        with self.assertRaises(ImportProblem):
            client.extract(SOURCE["transcript"], SOURCE["screen_text"])
        self.assertEqual(client.extraction_checks[-1]["status"], "invalid_response")
        self.assertEqual(post.call_count, 2)

    @patch("video_pipeline.prepare_audio")
    @patch("video_pipeline.read_video")
    @patch("tiktok_import.requests.post")
    def test_usage_limit_retry_retains_source_and_accepted_output_protocol(self, post, read, audio):
        limited = response({}, status=429); limited.headers = {"retry-after": "30"}
        post.side_effect = [rejected(), limited, accepted()]
        task = ImportTask({"transcript": SOURCE["transcript"], "screen_text": SOURCE["screen_text"], "metadata": {}})
        first = _process(task, VIDEO, "fixture-key")
        self.assertFalse(first["ok"])
        self.assertTrue(first["data"]["compatibility_mode"])
        self.assertEqual(first["data"]["provider_error"]["http_status"], 429)
        resumed = ImportTask(first["data"])
        second = _process(resumed, VIDEO, "fixture-key")
        self.assertTrue(second["ok"])
        self.assertNotIn("provider_error", second["data"])
        self.assertNotIn("failed_stage", second["data"])
        self.assertEqual(len(second["data"]["drafts"]), 5)
        self.assertEqual(post.call_count, 3)
        self.assertEqual(post.call_args_list[2].kwargs["json"]["response_format"]["type"], "json_object")
        read.assert_not_called(); audio.assert_not_called()


if __name__ == "__main__":
    unittest.main()
