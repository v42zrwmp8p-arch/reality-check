"""Functional UI checks with mocked Supadata responses and saved price data.

These are not evidence of live TikTok/provider availability.
"""
from datetime import date
from pathlib import Path
from unittest.mock import patch
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest

from test_tiktok_import import VIDEO, METADATA, DRAFT
from tiktok_import import ImportProblem

ROOT = Path(__file__).resolve().parent


def app():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    at.radio(key="mode").set_value("Import TikTok").run()
    return at


class ImportUiChecks(unittest.TestCase):
    @patch("tiktok_ui.service_key", return_value="")
    def test_missing_key_does_not_break_existing_modes(self, key):
        at = app()
        self.assertFalse(at.exception)
        self.assertTrue(at.button(key="tt_analyse").disabled)
        self.assertTrue(any("not been connected" in x.value for x in at.info))
        at.radio(key="mode").set_value("Your own case").run()
        self.assertIsNotNone(at.text_input(key="manual_ticker"))
        at.radio(key="mode").set_value("TikTok examples").run()
        for case in at.selectbox(key="case_selector").options:
            # The widget exposes formatted labels; select by their current index.
            index = at.selectbox(key="case_selector").options.index(case)
            at.selectbox(key="case_selector").select_index(index).run()
            self.assertFalse(at.exception)
            self.assertFalse(at.error)

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.SupadataClient")
    @patch("market_data.download_history")
    def test_review_calculation_multiple_assets_transcript_and_no_restarts(self, download, client_type, key):
        # app.histories uses its own cached wrapper; patch the shared provider function.
        def downloaded(symbol, publication_date, end_date):
            return pd.read_csv(ROOT / "prices" / f"{symbol}.csv", index_col="Date", parse_dates=True), symbol
        download.side_effect = downloaded
        client = client_type.return_value
        client.metadata.return_value = METADATA
        client.start_analysis.return_value = "analysis-job"
        crocs = dict(DRAFT, asset="Crocs", symbol="CROX", claim="Could triple from USD 106.",
                     target_type="multiple", target_value=3, reference_price=106,
                     time_frame="2 years", horizon_value=2, horizon_unit="years")
        calls = {"extract": 0, "transcript": 0}
        def poll(kind, job_id):
            calls[kind] += 1
            if calls[kind] == 1:
                return {"status": "queued"}
            if kind == "extract":
                return {"status": "completed", "data": {"recommendations": [DRAFT, crocs]}}
            return {"status": "completed", "result": {"content": "Fixture transcript, not a real provider response."}}
        client.job.side_effect = poll
        client.start_transcript.return_value = {"jobId": "transcript-job"}
        at = app()
        at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        self.assertFalse(at.exception)
        self.assertNotIn("drafts", at.session_state["tt_import"])
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(at.text_input(key="tt_review_0_symbol").value, "MRVL")
        self.assertEqual(at.date_input(key="tt_review_0_published").value, date(2023, 6, 26))
        self.assertEqual(at.selectbox(key="tt_choice").options, ["Marvell", "Crocs"])
        self.assertEqual(client.start_analysis.call_count, 1)
        self.assertEqual(client.start_transcript.call_count, 0)

        at.date_input(key="tt_review_0_published").set_value(None).run()
        at.button(key="tt_calculate").click().run()
        self.assertTrue(any("publication date" in x.value for x in at.error))
        self.assertEqual(download.call_count, 0)
        at.date_input(key="tt_review_0_published").set_value(date(2023, 6, 26)).run()
        at.button(key="tt_calculate").click().run()
        self.assertFalse(at.exception)
        self.assertFalse(at.error)
        self.assertEqual(len(at.metric), 4)
        self.assertEqual(at.session_state["tt_result"]["result"][0]["price_target"]["target_usd"], 142)

        at.text_input(key="tt_review_0_price_value").set_value("150").run()
        self.assertEqual(len(at.metric), 0)
        self.assertTrue(any("apply the changed" in x.value for x in at.info))
        at.selectbox(key="tt_review_0_target_type").set_value("multiple").run()
        self.assertEqual(at.text_input(key="tt_review_0_multiple_value").value, "")
        at.selectbox(key="tt_choice").select_index(1).run()
        self.assertEqual(at.text_input(key="tt_review_1_symbol").value, "CROX")
        at.button(key="tt_calculate").click().run()
        self.assertFalse(at.exception)
        self.assertFalse(at.error)
        result = at.session_state["tt_result"]["result"][0]
        self.assertEqual(result["price_target"]["target_usd"], 318)
        self.assertEqual(result["forecast_deadline"], "2025-06-26")
        self.assertEqual(result["deadline_result"]["status"], "elapsed")

        at.button(key="tt_transcribe").click().run()
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(client.start_transcript.call_count, 1)
        self.assertIn("Fixture transcript", at.session_state["tt_import"]["transcript"]["text"])
        self.assertEqual(client.start_analysis.call_count, 1)
        self.assertEqual(client.metadata.call_count, 1)
        at.button(key="tt_clear").click().run()
        self.assertFalse(at.exception)
        self.assertNotIn("tt_import", at.session_state)
        self.assertNotIn("tt_result", at.session_state)
        self.assertNotIn("tt_choice", at.session_state)

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.SupadataClient")
    def test_empty_predictions_and_session_isolation(self, client_type, key):
        client = client_type.return_value
        client.metadata.return_value = dict(METADATA, createdAt=None)
        client.start_analysis.return_value = "empty-job"
        client.job.return_value = {"status": "completed", "data": {"recommendations": []}}
        at = app()
        at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("No supported" in x.value for x in at.info))
        self.assertEqual(len(at.metric), 0)
        separate = app()
        self.assertNotIn("tt_import", separate.session_state)
        self.assertNotIn("tt_result", separate.session_state)

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.SupadataClient")
    def test_bad_links_and_service_errors(self, client_type, key):
        at = app()
        at.text_input(key="tt_link").set_value("https://example.invalid/private").run()
        at.button(key="tt_analyse").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("TikTok" in x.value for x in at.error))
        client_type.assert_not_called()
        client_type.return_value.metadata.side_effect = ImportProblem("Fixture provider unavailable")
        at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("provider unavailable" in x.value for x in at.error))
        client_type.return_value.start_analysis.assert_not_called()

    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.SupadataClient")
    def test_resume_existing_job_after_error_and_hide_changed_link(self, client_type, key):
        client = client_type.return_value
        client.metadata.return_value = METADATA
        client.start_analysis.return_value = "retry-job"
        client.job.side_effect = [ImportProblem("Fixture temporary limit"),
                                  {"status": "completed", "data": {"recommendations": [DRAFT]}}]
        at = app()
        at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("temporary limit" in x.value for x in at.warning))
        at.run()
        self.assertEqual(client.job.call_count, 1)
        at.button(key="tt_retry_extract").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.text_input(key="tt_review_0_symbol").value, "MRVL")
        self.assertEqual(client.start_analysis.call_count, 1)
        at.text_input(key="tt_link").set_value(VIDEO.replace("7249072169680948526", "7249072169680948527")).run()
        self.assertFalse(at.exception)
        self.assertFalse(any(x.key == "tt_review_0_symbol" for x in at.text_input))
        self.assertEqual(client.start_analysis.call_count, 1)


if __name__ == "__main__":
    unittest.main()
