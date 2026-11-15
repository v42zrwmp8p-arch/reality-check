"""Functional UI checks with simulated Groq tasks and saved market observations."""
from concurrent.futures import Future
from datetime import date
from pathlib import Path
import time
from unittest.mock import patch
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest

from test_tiktok_import import VIDEO, METADATA, DRAFT
from tiktok_import import ImportProblem
from video_pipeline import ImportTask
from asset_resolution import complete_drafts

ROOT = Path(__file__).resolve().parent


def app():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    at.radio(key="mode").set_value("Import TikTok").run()
    return at


def completed(rows):
    task = ImportTask()
    task.future = Future()
    task.future.set_result({"ok": True, "data": {"metadata": METADATA, "drafts": rows,
                           "transcript": "Fixture transcript; not a real Groq response.",
                           "screen_text": "MRVL 142", "screen_note": "Fixture sampled OCR.",
                           "analysed_at": "2026-11-14T00:00:00+00:00"}})
    return task


class ImportUiChecks(unittest.TestCase):
    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    @patch("market_data.download_history")
    def test_switching_recommendations_keeps_edits_and_calculates_selected_asset_once(self, download, submit, key):
        download.side_effect = lambda symbol, *args: (
            pd.read_csv(ROOT / "prices" / f"{symbol}.csv", index_col="Date", parse_dates=True), symbol)
        crocs = dict(DRAFT, asset="Crocs", symbol="CROX", target_type="multiple", target_value=3,
                     reference_price=106, time_frame="2 years", horizon_value=2, horizon_unit="years")
        task = completed([dict(DRAFT), crocs])
        submit.return_value = (task, False)
        at = app(); at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        at.button(key="tt_calculate").click().run()
        self.assertEqual(at.session_state["tt_result"]["row"]["symbol"], "MRVL")
        at.selectbox(key="tt_choice").select_index(1).run()
        self.assertNotIn("tt_result", at.session_state)
        at.text_input(key="tt_review_1_asset").set_value("Crocs reviewed").run()
        at.text_input(key="tt_review_1_multiple_value").set_value("4").run()
        at.text_input(key="tt_review_1_duration").set_value("3").run()
        at.text_area(key="tt_review_1_claim").set_value("Private reviewed second recommendation").run()
        at.button(key="tt_calculate").click().run()
        self.assertEqual(at.selectbox(key="tt_choice").value, 1)
        self.assertEqual(at.session_state["tt_result"]["row"]["symbol"], "CROX")
        at.selectbox(key="tt_choice").select_index(0).run()
        at.selectbox(key="tt_choice").select_index(1).run()
        self.assertEqual(at.text_input(key="tt_review_1_asset").value, "Crocs reviewed")
        self.assertEqual(at.text_input(key="tt_review_1_multiple_value").value, "4")
        self.assertEqual(at.text_input(key="tt_review_1_duration").value, "3")
        self.assertEqual(at.text_area(key="tt_review_1_claim").value, "Private reviewed second recommendation")
        at.button(key="tt_calculate").click().run()
        self.assertFalse(at.exception)
        self.assertFalse(at.error)
        self.assertEqual(at.selectbox(key="tt_choice").value, 1)
        result = at.session_state["tt_result"]["result"][0]
        self.assertEqual(result["symbol"], "CROX")
        self.assertEqual(result["price_target"]["target_usd"], 424)
        self.assertEqual(result["forecast_deadline"], "2026-06-26")
        self.assertEqual(task.future.result()["data"]["drafts"][1]["target_value"], 3)
        self.assertEqual(submit.call_count, 1)

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    def test_selected_recommendation_survives_temporarily_hidden_import(self, submit, key):
        submit.return_value = (completed([dict(DRAFT), dict(DRAFT, asset="Crocs", symbol="CROX")]), False)
        at = app(); at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        at.selectbox(key="tt_choice").select_index(1).run()
        at.text_input(key="tt_review_1_price_value").set_value("175").run()
        at.radio(key="mode").set_value("Manual Entry").run()
        at.radio(key="mode").set_value("Import TikTok").run()
        at.text_input(key="tt_link").set_value(VIDEO).run()
        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox(key="tt_choice").value, 1)
        self.assertEqual(at.text_input(key="tt_review_1_price_value").value, "175")

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    def test_conditional_review_fields_keep_values_when_reopened(self, submit, key):
        submit.return_value = (completed([dict(DRAFT)]), False)
        at = app(); at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        at.text_input(key="tt_review_0_price_value").set_value("175").run()
        at.selectbox(key="tt_review_0_target_type").set_value("multiple").run()
        at.text_input(key="tt_review_0_multiple_value").set_value("5").run()
        at.selectbox(key="tt_review_0_target_type").set_value("price").run()
        self.assertEqual(at.text_input(key="tt_review_0_price_value").value, "175")
        at.selectbox(key="tt_review_0_target_type").set_value("multiple").run()
        self.assertEqual(at.text_input(key="tt_review_0_multiple_value").value, "5")
        at.selectbox(key="tt_review_0_window_type").set_value("Duration from publication").run()
        at.text_input(key="tt_review_0_duration").set_value("7").run()
        at.selectbox(key="tt_review_0_unit").set_value("years").run()
        at.selectbox(key="tt_review_0_window_type").set_value("Exact deadline").run()
        at.date_input(key="tt_review_0_deadline").set_value(date(2028, 6, 26)).run()
        at.selectbox(key="tt_review_0_window_type").set_value("Duration from publication").run()
        self.assertEqual(at.text_input(key="tt_review_0_duration").value, "7")
        self.assertEqual(at.selectbox(key="tt_review_0_unit").value, "years")
        at.selectbox(key="tt_review_0_window_type").set_value("Exact deadline").run()
        self.assertEqual(at.date_input(key="tt_review_0_deadline").value, date(2028, 6, 26))
        self.assertFalse(at.exception)

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    def test_new_import_resets_persisted_selection_and_review_values(self, submit, key):
        submit.side_effect = [(completed([dict(DRAFT), dict(DRAFT, asset="Crocs", symbol="CROX")]), False),
                              (completed([dict(DRAFT, asset="Taiwan Semiconductor", symbol="TSM")]), False)]
        at = app(); at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        at.selectbox(key="tt_choice").select_index(1).run()
        at.text_input(key="tt_review_1_price_value").set_value("999").run()
        at.button(key="tt_clear").click().run()
        self.assertNotIn("tt_choice", at.session_state)
        self.assertFalse(any(name.startswith("tt_review_") for name in at.session_state))
        at.text_input(key="tt_link").set_value(VIDEO.replace("7249072169680948526", "7249072169680948527")).run()
        at.button(key="tt_analyse").click().run()
        self.assertEqual(at.selectbox(key="tt_choice").value, 0)
        self.assertEqual(at.text_input(key="tt_review_0_symbol").value, "TSM")
        self.assertEqual(at.text_input(key="tt_review_0_price_value").value, "142")
        self.assertFalse(at.exception)

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    @patch("market_data.download_history")
    def test_imported_and_manual_etf_comparisons_use_spy(self, download, submit, key):
        from asset_resolution import explicit_etf_candidates
        from test_etf_import import SOURCE
        rows = explicit_etf_candidates(SOURCE["transcript"])
        submit.return_value = (completed(rows), False)
        # Use a saved series only as a functional UI fixture, not ETF performance.
        frame = pd.read_csv(ROOT / "prices" / "SPY.csv", index_col="Date", parse_dates=True)
        download.side_effect = lambda symbol, *args: (frame.copy(), symbol)
        at = app(); at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        self.assertEqual(len(at.selectbox(key="tt_choice").options), 3)
        self.assertEqual(at.selectbox(key="tt_review_0_kind").value, "ETF")
        at.button(key="tt_calculate").click().run()
        self.assertFalse(at.exception)
        self.assertFalse(at.error)
        self.assertEqual(at.session_state["tt_result"]["result"][0]["benchmark_symbol"], "SPY")
        at.radio(key="mode").set_value("Manual Entry").run()
        at.text_input(key="manual_ticker").set_value("VTI").run()
        at.selectbox(key="manual_type").set_value("ETF").run()
        at.button(key="manual_calculate").click().run()
        self.assertFalse(at.exception)
        self.assertFalse(at.error)
        self.assertEqual(at.session_state["manual_result"]["row"]["asset_type"], "ETF")

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    @patch("market_data.download_history")
    def test_recorded_amc_target_review_and_approximate_result(self, download, submit, key):
        from test_target_extraction import FIXTURE, AMC
        from target_extraction import recover_multiple
        row = recover_multiple([AMC], FIXTURE["transcript"], FIXTURE["screen_text"])[0]
        submit.return_value = (completed([row]), False)
        # Synthetic prices only exercise the display, not real AMC performance.
        dates = pd.to_datetime(["2023-06-27", "2023-06-28", "2023-06-29"])
        frame = pd.DataFrame({"Close": [2.25, 3.0, 14.0], "Adj Close": [2.25, 3.0, 14.0],
                              "High": [2.3, 3.1, 14.1], "Stock Splits": [0, 0, 0]}, index=dates)
        download.side_effect = lambda symbol, *args: (frame.copy(), symbol)
        at = app(); at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        self.assertEqual(at.selectbox(key="tt_review_0_target_type").value, "multiple")
        self.assertEqual(float(at.text_input(key="tt_review_0_multiple_value").value), 6)
        self.assertTrue(at.checkbox(key="tt_review_0_approximate").value)
        self.assertEqual(float(at.text_input(key="tt_review_0_reference_price").value), 2.25)
        at.button(key="tt_calculate").click().run()
        self.assertFalse(at.exception)
        self.assertFalse(at.error)
        self.assertTrue(any(item.value == "Target: ~6× (USD 13.5)" for item in at.subheader))
        self.assertTrue(at.session_state["tt_result"]["row"]["target_approximate"])

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    def test_failed_extraction_still_offers_transcript_and_diagnostic_report(self, submit, key):
        task = ImportTask(); task.future = Future(); task.retry_at = time.time() + 120
        task.future.set_result({"ok": False, "error": "Fixture unreadable response", "retry_after": 120,
                                "data": {"transcript": "Public completed speech", "metadata": METADATA,
                                         "extraction_checks": [{"raw_response_content": "unreadable"}]}})
        submit.return_value = (task, False)
        at = app(); at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("unreadable response" in item.value for item in at.error))
        self.assertIn("Import details", [item.label for item in at.expander])
        self.assertTrue(any("Public completed speech" in item.value for item in at.text))
        self.assertEqual(len(at.metric), 0)

    @patch("tiktok_ui.service_key", return_value="")
    def test_missing_key_does_not_break_existing_modes(self, key):
        at = app()
        self.assertFalse(at.exception)
        self.assertTrue(at.button(key="tt_analyse").disabled)
        captions = [item.value for item in at.caption]
        words = " ".join(captions + [item.value for item in at.markdown])
        self.assertIn("If a post has already been analysed, the app can reuse the saved result for up to 24 hours.", captions)
        for removed in ["A forecast without a deadline is not labelled false", "Vague time frames are retained as text", "The curated collection is illustrative"]:
            self.assertNotIn(removed, words)
        self.assertEqual(at.radio(key="mode").options, ["Import TikTok", "Manual Entry", "My Tracker", "Case Database"])
        at.radio(key="mode").set_value("Manual Entry").run()
        self.assertIsNotNone(at.text_input(key="manual_ticker"))
        at.radio(key="mode").set_value("Case Database").run()
        for index in range(len(at.selectbox(key="case_selector").options)):
            at.selectbox(key="case_selector").select_index(index).run()
            self.assertFalse(at.exception)
            self.assertFalse(at.error)

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    @patch("market_data.download_history")
    def test_multiple_recommendations_review_and_calculation(self, download, submit, key):
        def downloaded(symbol, publication_date, end_date):
            return pd.read_csv(ROOT / "prices" / f"{symbol}.csv", index_col="Date", parse_dates=True), symbol
        download.side_effect = downloaded
        crocs = dict(DRAFT, asset="Crocs", symbol="CROX", target_type="multiple", target_value=3,
                     reference_price=106, time_frame="2 years", horizon_value=2, horizon_unit="years")
        finished = completed([DRAFT, crocs])
        pending = ImportTask(); pending.future = Future()
        submit.return_value = (pending, False)
        at = app()
        at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        self.assertEqual(at.session_state["tt_import"]["status"], "pending")
        pending.future.set_result(finished.future.result())
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox(key="tt_choice").options, ["Marvell", "Crocs"])
        self.assertEqual(at.text_input(key="tt_review_0_symbol").value, "MRVL")
        self.assertEqual(at.date_input(key="tt_review_0_published").value, date(2023, 6, 26))
        self.assertTrue(any("Fixture transcript" in x.value for x in at.text))
        self.assertNotIn("Sampled screen text", [x.label for x in at.expander])
        self.assertIn("Import details", [x.label for x in at.expander])
        self.assertTrue(any("Import version: 2026-11-15.4" == x.value for x in at.caption))
        at.date_input(key="tt_review_0_published").set_value(None).run()
        at.button(key="tt_calculate").click().run()
        self.assertTrue(any("publication date" in x.value for x in at.error))
        self.assertEqual(download.call_count, 0)
        at.date_input(key="tt_review_0_published").set_value(date(2023, 6, 26)).run()
        at.button(key="tt_calculate").click().run()
        self.assertFalse(at.error)
        self.assertEqual(len(at.metric), 4)
        self.assertEqual(at.session_state["tt_result"]["result"][0]["price_target"]["target_usd"], 142)
        at.text_input(key="tt_review_0_price_value").set_value("150").run()
        self.assertEqual(len(at.metric), 0)
        at.selectbox(key="tt_review_0_target_type").set_value("multiple").run()
        self.assertEqual(at.text_input(key="tt_review_0_multiple_value").value, "")
        at.selectbox(key="tt_choice").select_index(1).run()
        at.button(key="tt_calculate").click().run()
        self.assertFalse(at.exception)
        self.assertFalse(at.error)
        result = at.session_state["tt_result"]["result"][0]
        self.assertEqual(result["price_target"]["target_usd"], 318)
        self.assertEqual(result["forecast_deadline"], "2025-06-26")
        self.assertTrue(any(x.value == "Target: 3× (USD 318)" for x in at.subheader))
        self.assertFalse(any("3× means" in x.value or "106.000000" in x.value or "Derived from 3" in x.value for x in at.caption))
        self.assertEqual(submit.call_count, 1)
        at.button(key="tt_clear").click().run()
        self.assertNotIn("tt_import", at.session_state)
        self.assertNotIn("tt_result", at.session_state)
        self.assertEqual(at.text_input(key="tt_link").value, "")
        self.assertFalse(any(x.key and x.key.startswith("tt_review_") for x in at.text_input))

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    def test_empty_predictions_and_private_edits(self, submit, key):
        submit.return_value = (completed([]), False)
        at = app()
        at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("No recommendation identified" in x.value for x in at.info))
        self.assertEqual(len(at.metric), 0)
        self.assertNotIn("tt_import", app().session_state)
        source = completed([DRAFT]); submit.return_value = (source, True)
        at.button(key="tt_clear").click().run()
        at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        at.text_area(key="tt_review_0_claim").set_value("Private edited claim").run()
        at.session_state["tt_import"]["drafts"][0]["asset"] = "Local edit"
        self.assertEqual(source.future.result()["data"]["drafts"][0]["asset"], "Marvell")
        other = app(); other.text_input(key="tt_link").set_value(VIDEO).run()
        other.button(key="tt_analyse").click().run()
        self.assertEqual(other.text_area(key="tt_review_0_claim").value, DRAFT["claim"])
        self.assertTrue(any("Loaded a saved analysis" in x.value for x in other.caption))

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    @patch("market_data.download_history")
    def test_marvel_confirmation_and_bitcoin_missing_ticker(self, download, submit, key):
        def downloaded(symbol, publication_date, end_date):
            return pd.read_csv(ROOT / "prices" / f"{symbol}.csv", index_col="Date", parse_dates=True), symbol
        download.side_effect = downloaded
        rows = complete_drafts([dict(DRAFT, asset="Marvel", symbol=None),
                                dict(DRAFT, asset="Bitcoin", symbol=None, asset_type="Crypto", target_type="none", target_value=None)])
        submit.return_value = (completed(rows), False)
        at = app(); at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        self.assertTrue(at.button(key="tt_calculate").disabled)
        self.assertEqual(at.text_input(key="tt_review_0_symbol").value, "")
        self.assertEqual(at.text_input(key="tt_review_0_symbol").label, "Yahoo Finance ticker (required)")
        self.assertTrue(any("Select a suggested match above or enter a ticker to continue." in x.value for x in at.caption))
        self.assertFalse(at.error)
        at.button(key="tt_review_0_match_0").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.text_input(key="tt_review_0_asset").value, "Marvell Technology")
        self.assertEqual(at.text_input(key="tt_review_0_symbol").value, "MRVL")
        self.assertFalse(at.button(key="tt_calculate").disabled)
        self.assertFalse(any("ticker to continue." in x.value for x in at.caption))
        at.text_input(key="tt_review_0_symbol").set_value(" ").run()
        self.assertTrue(at.button(key="tt_calculate").disabled)
        self.assertTrue(any("ticker to continue." in x.value for x in at.caption))
        at.text_input(key="tt_review_0_symbol").set_value("MRVL").run()
        self.assertFalse(at.button(key="tt_calculate").disabled)
        at.button(key="tt_calculate").click().run()
        self.assertFalse(at.error)
        at.selectbox(key="tt_choice").select_index(1).run()
        self.assertEqual(at.text_input(key="tt_review_1_symbol").value, "BTC-USD")
        at.button(key="tt_calculate").click().run()
        self.assertFalse(at.error)
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["tt_result"]["row"]["symbol"], "BTC-USD")
        self.assertEqual(at.session_state["tt_result"]["result"][0]["benchmark_symbol"], "SPY")

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    def test_empty_result_has_manual_recovery_and_transcript_recheck(self, submit, key):
        source = completed([]); source.created -= 60
        submit.side_effect = [(source, False), (completed([DRAFT]), False)]
        at = app(); at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        at.button(key="tt_add").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(at.button(key="tt_calculate").disabled)
        self.assertEqual(source.future.result()["data"]["drafts"], [])
        at.text_input(key="tt_review_0_symbol").set_value("TSM").run()
        self.assertFalse(at.button(key="tt_calculate").disabled)
        at.button(key="tt_refresh").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.text_input(key="tt_review_0_symbol").value, "MRVL")
        self.assertTrue(submit.call_args.kwargs["refresh"])

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    def test_bad_links_and_queue_errors(self, submit, key):
        at = app()
        at.text_input(key="tt_link").set_value("https://example.invalid/private").run()
        at.button(key="tt_analyse").click().run()
        self.assertFalse(at.exception)
        submit.assert_not_called()
        submit.side_effect = ImportProblem("Fixture queue busy")
        at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("queue busy" in x.value for x in at.error))

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    def test_limit_wait_retry_and_changed_link(self, submit, key):
        limited = ImportTask(); limited.future = Future(); limited.retry_at = time.time() + 120
        limited.future.set_result({"ok": False, "error": "The shared Groq usage limit was reached.", "retry_after": 120})
        submit.side_effect = [(limited, False), (completed([DRAFT]), False)]
        at = app(); at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("usage limit" in x.value for x in at.error))
        self.assertTrue(at.button(key="tt_analyse").disabled)
        at.run(); self.assertEqual(submit.call_count, 1)
        at.session_state["tt_import"]["retry_at"] = time.time() - 1
        at.run(); self.assertFalse(at.button(key="tt_analyse").disabled)
        at.button(key="tt_analyse").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.text_input(key="tt_review_0_symbol").value, "MRVL")
        at.text_input(key="tt_link").set_value(VIDEO.replace("7249072169680948526", "7249072169680948527")).run()
        self.assertFalse(any(x.key == "tt_review_0_symbol" for x in at.text_input))
        self.assertEqual(submit.call_count, 2)


if __name__ == "__main__":
    unittest.main()
