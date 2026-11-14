"""Regression checks using the user's failing transcript, without a live AI claim."""
from copy import deepcopy
import json
from unittest.mock import patch
import unittest

from asset_resolution import complete_drafts, explicit_buy_list_candidates, search_candidates
from tiktok_import import GroqClient, metadata_details
from test_tiktok_import import DRAFT, response
from video_pipeline import creator_name

AI_BUY_LIST = """[00:00] Here are the top three AI stocks to buy for the next decade, according to famous AI stock
[00:04] researcher, ticker symbol U. Although NVIDIA is frequently talked about by his team, these
[00:10] stocks will be more so focused on the future of AI, with stocks that haven't gotten as
[00:14] much attention as NVIDIA. So at number one, we have Taiwan Semiconductor, ticker symbol
[00:19] TSM. TSMC is a pure play semiconductor foundry that manufactures chips for companies like
[00:25] Apple, NVIDIA, and AMD, and unlike Intel, it does not design its own chips, which allows it to focus
[00:31] entirely on chip fabrication and serve multiple clients without competing with them. The company
[00:36] produces 90% of the world's most advanced microchips, including Apple's A-Series and M-Series
[00:41] chips and NVIDIA's GPUs, and the best part is that the stock trades at a valuation of 23 times
[00:47] forward earnings. The next stock on this list is Micron, ticker symbol MU. Micron is making a
[00:53] remarkable comeback by positioning itself as the lead enabler of the AI revolution.
[00:57] Micron was once focused on old school memory but struggled to compete. But now, they're pivoting
[01:02] towards high bandwidth memory production, a critical component for AI chips. And they're
[01:07] locking in long-term supply deals with major AI players like NVIDIA, Google, and Meta. The company
[01:12] did 93% in revenue growth and 160% in EPS growth in Q4 and has put out good forward guidance for
[01:19] next year. The stock is also trading at an 11 times forward earnings. And finally, for the last
[01:25] stock, it's one that you've probably never heard of, so follow me and comment newsletter to find
[01:29] out what it is."""


class ResolutionChecks(unittest.TestCase):
    def test_user_transcript_recovers_only_two_actual_picks(self):
        rows = explicit_buy_list_candidates(AI_BUY_LIST)
        self.assertEqual([row["symbol"] for row in rows], ["TSM", "MU"])
        for row in rows:
            self.assertEqual((row["horizon_value"], row["horizon_unit"]), (10, "years"))
            self.assertEqual(row["target_type"], "none")
            self.assertIsNone(row["target_value"])
            self.assertLessEqual(len(row["evidence"].split()), 20)

    def test_buy_list_fallback_ignores_negation_and_incidental_mentions(self):
        self.assertEqual(explicit_buy_list_candidates(AI_BUY_LIST.replace("Here are", "Never believe these claims. Here are")), [])
        self.assertEqual(explicit_buy_list_candidates("NVIDIA supplies chips to Micron, ticker symbol MU."), [])
        self.assertEqual(explicit_buy_list_candidates("Top stocks to buy. Our customers include Apple, ticker AAPL."), [])

    @patch("tiktok_import.requests.post")
    def test_empty_ai_answers_cannot_erase_explicit_supported_list_items(self, post):
        post.return_value = response({"choices": [{"finish_reason": "stop", "message": {"content": '{"recommendations": []}'}}]})
        rows = GroqClient("fixture-key").extract(AI_BUY_LIST, "")
        self.assertEqual([row["symbol"] for row in rows], ["TSM", "MU"])
        self.assertEqual(post.call_count, 1)

    @patch("tiktok_import.requests.post")
    def test_partial_answer_keeps_claim_and_adds_missed_list_item(self, post):
        draft = dict(DRAFT, asset="Micron", symbol="MU", target_type="none", target_value=None, claim="Original supported claim")
        post.return_value = response({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"recommendations": [draft]})}}]})
        rows = GroqClient("fixture-key").extract(AI_BUY_LIST, "")
        self.assertEqual({row["symbol"] for row in rows}, {"TSM", "MU"})
        self.assertEqual(rows[0]["claim"], "Original supported claim")
        self.assertEqual(rows[0]["horizon_value"], 10)
        self.assertEqual(post.call_count, 1)

    @patch("tiktok_import.requests.post")
    def test_unrelated_video_stays_empty_after_one_check(self, post):
        post.return_value = response({"choices": [{"finish_reason": "stop", "message": {"content": '{"recommendations": []}'}}]})
        self.assertEqual(GroqClient("fixture-key").extract("How to make pancakes.", ""), [])
        self.assertEqual(post.call_count, 2)
        self.assertIn("Independently recheck", post.call_args.kwargs["json"]["messages"][0]["content"])

    def test_bitcoin_missing_or_wrong_ticker_is_filled_without_search(self):
        source = [dict(DRAFT, asset="Bitcoin", symbol=None, asset_type="Crypto"),
                  dict(DRAFT, asset="Ethereum", symbol="ETH", asset_type="Unknown")]
        original = deepcopy(source)
        def forbidden(*args):
            self.fail("Known identifiers must not require a network search")
        rows = complete_drafts(source, lookup=forbidden)
        self.assertEqual([row["symbol"] for row in rows], ["BTC-USD", "ETH-USD"])
        self.assertEqual(source, original)
        self.assertEqual(complete_drafts([dict(source[0], symbol="WRONG")])[0]["symbol"], "BTC-USD")

    def test_marvel_is_a_suggestion_not_a_silent_replacement(self):
        row = complete_drafts([dict(DRAFT, asset="Marvel", symbol=None)])[0]
        self.assertEqual(row["asset"], "Marvel")
        self.assertIsNone(row["symbol"])
        self.assertEqual(row["ticker_suggestions"][0]["symbol"], "MRVL")

    def test_unknown_asset_search_has_a_bound_and_does_not_choose_first_result(self):
        calls = []
        def lookup(name, kind):
            calls.append(name)
            return [{"asset": "Example Industries", "symbol": "EXM", "asset_type": "Equity"}]
        rows = complete_drafts([dict(DRAFT, asset=f"Unknown company {i}", symbol=None) for i in range(9)], lookup=lookup)
        self.assertEqual(len(calls), 6)
        self.assertTrue(all(row["symbol"] is None for row in rows))
        self.assertEqual(rows[0]["ticker_suggestions"][0]["symbol"], "EXM")

    @patch("yfinance.Search")
    def test_search_filters_non_us_listings_and_non_usd_crypto(self, search):
        search.return_value.quotes = [
            {"symbol": "PLTR", "longname": "Palantir Technologies", "quoteType": "EQUITY", "exchange": "NMS"},
            {"symbol": "PLTR.DE", "quoteType": "EQUITY", "exchange": "GER"},
            {"symbol": "BTC-EUR", "quoteType": "CRYPTOCURRENCY"},
            {"symbol": "BTC-USD", "longname": "Bitcoin USD", "quoteType": "CRYPTOCURRENCY"},
        ]
        self.assertEqual([row["symbol"] for row in search_candidates("Palantir", "Equity")], ["PLTR"])
        self.assertEqual([row["symbol"] for row in search_candidates("Bitcoin", "Crypto")], ["BTC-USD"])

    def test_creator_uses_handle_instead_of_numeric_uid(self):
        url = "https://www.tiktok.com/@quantjason/video/7026749642477964549"
        self.assertEqual(creator_name({"uploader_id": "6628757945272909830"}, url), "@quantjason")
        self.assertEqual(creator_name({"uploader_id": "123456", "webpage_url": url}, "https://vm.tiktok.com/ABC123"), "@quantjason")
        self.assertEqual(creator_name({"uploader_id": "123456"}, "https://vm.tiktok.com/ABC123"), "")
        self.assertEqual(metadata_details({"author": {"username": "6628757945272909830"}})["creator"], "")


if __name__ == "__main__":
    unittest.main()
