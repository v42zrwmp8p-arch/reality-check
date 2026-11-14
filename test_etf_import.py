"""Recorded ETF scope failure plus generic ticker and holdings safeguards."""
import json
from pathlib import Path
from unittest.mock import patch
import unittest

from asset_resolution import explicit_etf_candidates, search_candidates
from test_tiktok_import import DRAFT, response
from tiktok_import import GroqClient, EXTRACTION_SCHEMA, reviewed_case

SOURCE = json.loads((Path(__file__).resolve().parent / "test_fixtures" / "etf_extraction.json").read_text())


class EtfChecks(unittest.TestCase):
    def test_recorded_source_recovers_funds_without_holdings_or_historical_targets(self):
        rows = explicit_etf_candidates(SOURCE["transcript"])
        self.assertEqual({row["symbol"] for row in rows}, {"XLE", "SMH", "XLV"})
        self.assertTrue(all(row["asset_type"] == "ETF" for row in rows))
        self.assertTrue(all(row["target_type"] == "none" for row in rows))
        self.assertTrue(all(row["horizon_value"] is None for row in rows))
        self.assertTrue(all(row["time_frame"] == "long term" for row in rows))

    @patch("tiktok_import.requests.post")
    def test_recorded_empty_model_answer_is_recovered_without_another_api_call(self, post):
        post.return_value = response({"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(SOURCE["model_response"])}}]})
        client = GroqClient("fixture-key")
        rows = client.extract(SOURCE["transcript"], SOURCE["screen_text"])
        self.assertEqual({row["symbol"] for row in rows}, {"XLE", "SMH", "XLV"})
        self.assertEqual(post.call_count, 1)
        self.assertEqual(client.extraction_checks[0]["detected_assets"], [])
        prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertNotIn("Only include individual stocks and cryptocurrencies", prompt)
        self.assertIn("ETFs are explicitly supported", prompt)
        self.assertIn("ETF", EXTRACTION_SCHEMA["properties"]["recommendations"]["items"]["properties"]["asset_type"]["enum"])

    def test_etf_recovery_is_not_tied_to_the_three_reported_tickers(self):
        text = "You can buy ETFs for long term investing. A dividend ETF ticker symbol VYM. An index ETF ticker symbol VTI."
        self.assertEqual({row["symbol"] for row in explicit_etf_candidates(text)}, {"VYM", "VTI"})

    def test_holdings_negative_advice_and_explicit_leverage_are_not_recovered(self):
        texts = ["You should not buy ETFs. An energy ETF ticker symbol XLE.",
                 "You can buy ETFs. This ETF holds NVIDIA ticker symbol NVDA and AMD ticker symbol AMD.",
                 "You can buy ETFs. A leveraged ETF ticker symbol TQQQ."]
        for text in texts:
            with self.subTest(text=text):
                self.assertEqual(explicit_etf_candidates(text), [])

    @patch("yfinance.Search")
    def test_fund_lookup_and_review_accept_etf_type(self, search):
        search.return_value.quotes = [{"symbol": "XLE", "quoteType": "ETF", "exchange": "PCX", "longname": "Energy ETF"}]
        rows = search_candidates("Energy ETF", "ETF")
        self.assertEqual(rows[0]["asset_type"], "ETF")
        row = reviewed_case(dict(DRAFT, asset="Energy ETF", symbol="XLE", asset_type="ETF", publication_date="2024-01-23", target_type="none"),
                            "https://www.tiktok.com/@fixture/video/123456")
        self.assertEqual(row["symbol"], "XLE")
        self.assertEqual(row["asset_type"], "ETF")

    @patch("tiktok_import.requests.post")
    def test_model_fund_is_not_duplicated_and_keeps_its_name(self, post):
        draft = dict(DRAFT, asset="Energy Select Sector Fund", symbol="XLE", asset_type="ETF", target_type="none", target_value=None)
        post.return_value = response({"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"recommendations": [draft]})}}]})
        rows = GroqClient("fixture-key").extract(SOURCE["transcript"], SOURCE["screen_text"])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["asset"], "Energy Select Sector Fund")


if __name__ == "__main__":
    unittest.main()
