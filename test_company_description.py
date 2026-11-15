"""Optional provider profiles must not change or block comparison results."""
import unittest
from unittest.mock import patch

import streamlit as st

from market_data import download_company_description
from test_tiktok_ui import app, completed
from test_tiktok_import import DRAFT, VIDEO
from test_tracker import SimulatedBrowserStore
from test_dual_crypto import saved_download


class CompanyDescriptionChecks(unittest.TestCase):
    @patch("yfinance.Ticker")
    def test_current_profile_keeps_company_name_and_only_two_sentences(self, ticker):
        ticker.return_value.get_info.return_value = {
            "symbol": "XYZ", "quoteType": "EQUITY",
            "longBusinessSummary": "Block, Inc. builds payment tools.  It serves businesses. A third sentence."}
        self.assertEqual(download_company_description("SQ"),
                         "Block, Inc. builds payment tools. It serves businesses.")
        ticker.assert_called_once_with("XYZ")

    @patch("yfinance.Ticker")
    def test_missing_wrong_or_failed_profiles_are_optional(self, ticker):
        for info in [{}, {"symbol": "OTHER", "quoteType": "EQUITY", "longBusinessSummary": "Wrong company."},
                     {"symbol": "DEMO", "quoteType": "ETF", "longBusinessSummary": "A fund."}]:
            ticker.return_value.get_info.return_value = info
            self.assertEqual(download_company_description("DEMO"), "")
        ticker.return_value.get_info.side_effect = TimeoutError("Fixture provider timeout")
        self.assertEqual(download_company_description("DEMO"), "")

    @patch("tracker_ui._storage")
    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    @patch("market_data.download_history", side_effect=saved_download)
    @patch("yfinance.Ticker.get_info", return_value={"symbol": "CROX", "quoteType": "EQUITY",
           "longBusinessSummary": "Crocs, Inc. makes footwear. It sells shoes worldwide. Not shown."})
    def test_profile_appears_in_manual_import_and_tracker_but_not_reused_archive(self, info, history, submit, key, bridge):
        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        store = SimulatedBrowserStore(); bridge.side_effect = store
        line = "Crocs, Inc. makes footwear. It sells shoes worldwide. · Yahoo Finance"
        at = app(); at.radio(key="mode").set_value("Manual Entry").run()
        at.text_input(key="manual_ticker").set_value("CROX").run()
        at.button(key="manual_calculate").click().run()
        self.assertFalse(at.exception); self.assertFalse(at.error)
        self.assertIn(line, [c.value for c in at.caption])
        at.button(key="manual_track").click().run()
        at.radio(key="mode").set_value("My Tracker").run()
        self.assertFalse(at.exception); self.assertIn(line, [c.value for c in at.caption])
        submit.return_value = (completed([dict(DRAFT, asset="Crocs", symbol="CROX")]), False)
        at.radio(key="mode").set_value("Import TikTok").run()
        at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        at.button(key="tt_calculate").click().run()
        self.assertFalse(at.exception); self.assertFalse(at.error)
        self.assertIn(line, [c.value for c in at.caption])
        at.radio(key="mode").set_value("Case Database").run()
        info.reset_mock()
        at.selectbox(key="case_selector").set_value("cohen-bbby-20220307").run()
        self.assertFalse(at.exception); self.assertFalse(at.error)
        info.assert_not_called()


if __name__ == "__main__":
    unittest.main()
