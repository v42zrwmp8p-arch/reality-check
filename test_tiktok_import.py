"""API-boundary and review checks. Provider responses below are test fixtures."""
from datetime import date
from unittest.mock import Mock, patch
import unittest

from analysis_core import resolve_deadline
from tiktok_import import (ImportProblem, SupadataClient, clean_tiktok_url, metadata_details,
                           recommendations, reviewed_case, transcript_text)

VIDEO = "https://www.tiktok.com/@fixture/video/7249072169680948526"
METADATA = {"platform": "tiktok", "type": "video", "createdAt": "2023-06-26T18:00:00Z",
            "author": {"username": "fixture-creator"}, "stats": {"views": 12345}}
DRAFT = {"asset": "Marvell", "symbol": "MRVL", "asset_type": "Equity", "claim": "Could rise to USD 142.",
         "evidence": "142", "evidence_time": "00:12", "target_type": "price", "target_value": 142,
         "reference_price": None, "currency": "USD", "time_frame": None, "deadline": None,
         "horizon_value": None, "horizon_unit": None}


def response(data, status=200):
    result = Mock(status_code=status, content=b"{}")
    result.json.return_value = data
    return result


class ImportChecks(unittest.TestCase):
    def test_video_links_and_tracking_cleanup(self):
        self.assertEqual(clean_tiktok_url(VIDEO + "?tracking=remove#ignored"), VIDEO)
        self.assertEqual(clean_tiktok_url("https://vm.tiktok.com/ABC123/"), "https://vm.tiktok.com/ABC123")
        for url in ["http://www.tiktok.com/@a/video/12345", "https://tiktok.com.evil.test/@a/video/12345",
                    "https://user:password@www.tiktok.com/@a/video/12345", "https://127.0.0.1/video",
                    "https://www.tiktok.com/@a", "https://www.tiktok.com:8443/@a/video/12345",
                    "https://www.tiktok.com/@a/photo/12345", "https://www.tiktok.com@evil.test/video/12345"]:
            with self.subTest(url=url), self.assertRaises(ImportProblem):
                clean_tiktok_url(url)

    def test_metadata_does_not_invent_missing_dates_or_reach(self):
        details = metadata_details(METADATA)
        self.assertEqual(details["publication_date"], date(2023, 6, 26))
        self.assertEqual(details["creator"], "fixture-creator")
        self.assertEqual(details["video_views"], 12345)
        missing = metadata_details({"author": None, "stats": {"views": -1}, "createdAt": "not a date"})
        self.assertIsNone(missing["publication_date"])
        self.assertIsNone(missing["video_views"])

    def test_review_requires_date_and_known_asset_type(self):
        base = {**DRAFT, "publication_date": None}
        with self.assertRaisesRegex(ImportProblem, "publication date"):
            reviewed_case(base, VIDEO)
        with self.assertRaisesRegex(ImportProblem, "Equity or Crypto"):
            reviewed_case(dict(base, publication_date="2023-06-26", asset_type="Unknown"), VIDEO)

    def test_targets_horizons_and_currency_are_checked(self):
        values = {**DRAFT, "publication_date": "2023-06-26", "target_type": "multiple", "target_value": 3,
                  "reference_type": "creator", "reference_price": 106, "horizon_value": 2, "horizon_unit": "years"}
        row = reviewed_case(values, VIDEO)
        self.assertEqual(row["reference_price"], 106)
        self.assertEqual(resolve_deadline(row)[0], "2025-06-26")
        self.assertFalse(row["curated"])
        self.assertTrue(row["imported"])
        with self.assertRaisesRegex(ImportProblem, "USD"):
            reviewed_case(dict(values, currency="Other / unclear"), VIDEO)
        with self.assertRaises(ValueError):
            reviewed_case(dict(values, target_value=1), VIDEO)
        with self.assertRaises(ValueError):
            reviewed_case(dict(values, horizon_value=1.5), VIDEO)
        no_target = reviewed_case(dict(values, target_type="none", reference_type=None, horizon_value=None, horizon_unit=None), VIDEO)
        self.assertIsNone(no_target["target_value"])
        self.assertIsNone(resolve_deadline(no_target)[0])

    def test_ambiguous_and_multiple_recommendations(self):
        other = dict(DRAFT, asset="Micron", symbol="MU", target_type="none", target_value=None,
                     time_frame="next few weeks")
        rows = recommendations({"data": {"recommendations": [DRAFT, other]}})
        self.assertEqual(len(rows), 2)
        reviewed = reviewed_case(dict(rows[1], publication_date="2023-06-26"), VIDEO)
        self.assertIsNone(reviewed["target_value"])
        self.assertIsNone(resolve_deadline(reviewed)[0])
        self.assertEqual(recommendations({"data": {"recommendations": []}}), [])
        with self.assertRaises(ImportProblem):
            recommendations({"data": {"recommendations": "not a list"}})

    def test_transcript_sync_async_and_silent_audio(self):
        self.assertEqual(transcript_text({"content": "speech"}), "speech")
        self.assertEqual(transcript_text({"status": "completed", "result": {"content": "speech"}}), "speech")
        self.assertEqual(transcript_text({"content": [{"text": "hello"}, {"text": "world"}]}), "hello world")
        with self.assertRaises(ImportProblem):
            transcript_text({"content": []})

    @patch("tiktok_import.RATE_INTERVAL", 0)
    @patch("tiktok_import.requests.request")
    def test_provider_protocol_and_jobs(self, request):
        request.side_effect = [response(METADATA), response({"jobId": "test-job"}, 202),
                               response({"status": "queued"}), response({"status": "completed", "data": {"recommendations": [DRAFT]}}),
                               response({"jobId": "transcript-job"}, 202)]
        client = SupadataClient("fixture-key")
        self.assertEqual(client.metadata(VIDEO), METADATA)
        self.assertEqual(client.start_analysis(VIDEO), "test-job")
        self.assertEqual(client.job("extract", "test-job")["status"], "queued")
        self.assertEqual(len(recommendations(client.job("extract", "test-job"))), 1)
        self.assertEqual(client.start_transcript(VIDEO)["jobId"], "transcript-job")
        post = request.call_args_list[1]
        self.assertEqual(post.args, ("POST", "https://api.supadata.ai/v1/extract"))
        self.assertIn("schema", post.kwargs["json"])
        self.assertFalse(post.kwargs["allow_redirects"])
        self.assertEqual(request.call_args_list[-1].kwargs["params"]["mode"], "auto")

    @patch("tiktok_import.RATE_INTERVAL", 0)
    @patch("tiktok_import.requests.request")
    def test_provider_errors_are_safe_and_no_retry_post(self, request):
        for status in [206, 400, 401, 402, 403, 404, 429, 500]:
            request.reset_mock()
            request.return_value = response({"details": "fixture-key should not be shown"}, status)
            with self.assertRaises(ImportProblem) as raised:
                SupadataClient("fixture-key").start_analysis(VIDEO)
            self.assertNotIn("fixture-key", str(raised.exception))
            self.assertEqual(request.call_count, 1)
        with self.assertRaises(ImportProblem):
            SupadataClient("")
        with self.assertRaises(ImportProblem):
            SupadataClient("fixture-key").job("extract", "../secrets")


if __name__ == "__main__":
    unittest.main()
