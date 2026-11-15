"""Recorded source disagreements and unseen tickers; model/price calls simulated."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch
import unittest

import pandas as pd

from target_extraction import review_screen_targets
from tiktok_import import GroqClient
from test_tiktok_import import DRAFT, VIDEO, response
from test_tiktok_ui import app, completed

ROOT = Path(__file__).resolve().parent
SOURCE = json.loads((ROOT / "test_fixtures/crypto_target_conflicts.json").read_text())


def checked_rows():
    return review_screen_targets(SOURCE["model_rows"], SOURCE["screen_text"])


def saved_prices(*args):
    return pd.read_csv(ROOT / "prices/CROX.csv", index_col="Date", parse_dates=True), "UI fixture"


class SourceConflictChecks(unittest.TestCase):
    def test_report_replay_flags_three_conflicts_and_preserves_raw_model_values(self):
        original = deepcopy(SOURCE["model_rows"])
        rows = checked_rows(); by_symbol = {r["symbol"]: r for r in rows}
        self.assertEqual({r["symbol"] for r in rows if r.get("target_review")}, {"SOL", "LINK", "INJ"})
        self.assertEqual(by_symbol["SOL"]["target_value"], 720000)
        self.assertEqual(by_symbol["SOL"]["target_review"]["suggested_value"], 720)
        self.assertEqual(by_symbol["LINK"]["target_review"]["suggested_value"], 120)
        self.assertIsNone(by_symbol["INJ"]["target_review"]["suggested_value"])
        self.assertEqual(set(by_symbol["INJ"]["target_review"]["screen_values"]), {2, 22, 220})
        self.assertTrue(all(r["time_frame"] == "2025" and r["deadline"] is None for r in rows))
        self.assertEqual(SOURCE["model_rows"], original)

    def test_unseen_tickers_and_consistent_written_targets_use_the_same_rule(self):
        text = "[00:01]\nMy 2028 price targets\n$ZZZZ - $150\n$YYYY - $42\n" * 1
        text += "[00:04]\nMy 2028 price targets\n$ZZZZ - $150\n$YYYY - $42\n"
        rows = review_screen_targets([dict(DRAFT, symbol="ZZZZ", target_value=150000),
                                      dict(DRAFT, symbol="YYYY-USD", target_value=42)], text)
        self.assertEqual(rows[0]["target_review"]["suggested_value"], 150)
        self.assertNotIn("target_review", rows[1])
        self.assertEqual(rows[1]["time_frame"], "2028")

    def test_current_or_historical_prices_duplicate_frames_and_different_years_are_not_votes(self):
        body = "\nMy 2028 price targets\n$ZZZZ - $150\n$YYYY - $42\n"
        row = dict(DRAFT, symbol="ZZZZ", target_value=150000)
        for text in ["[00:01]" + body, "[00:01]" + body + "[00:01]" + body,
                     "[00:01]" + body + "[00:04]" + body.replace("2028", "2029"),
                     ("[00:01]" + body + "[00:04]" + body).replace("My 2028 price targets", "Historical 2028 price targets"),
                     ("[00:01]" + body + "[00:04]" + body).replace("My 2028 price targets", "2028 chart prices")]:
            with self.subTest(text=text):
                self.assertNotIn("target_review", review_screen_targets([row], text)[0])
        text = "[00:01]" + body + "[00:04]" + body
        for timing in [dict(deadline="2030-01-01"), dict(horizon_value=3, horizon_unit="years")]:
            result = review_screen_targets([dict(row, **timing)], text)[0]
            self.assertIsNone(result["time_frame"])

    @patch("tiktok_import.requests.post")
    def test_model_and_photo_paths_apply_source_checks_without_extra_calls(self, post):
        for photo in [False, True]:
            with self.subTest(photo=photo):
                post.reset_mock()
                post.return_value = response({"choices": [{"finish_reason": "stop", "message": {
                    "content": json.dumps({"recommendations": SOURCE["model_rows"]})}}]})
                text = SOURCE["screen_text"]
                if photo:
                    import re
                    text = re.sub(r"\[\d{2}:\d{2}\]", lambda m: f"[Photo {int(m[0][4:6]) + 1}]", text)
                rows = GroqClient("fixture-key").extract(text if photo else SOURCE["transcript"],
                                                        "" if photo else text,
                                                        source_kind="photo" if photo else "video")
                self.assertEqual(len(rows), 13)
                self.assertEqual(sum(bool(r.get("target_review")) for r in rows), 3)
                self.assertEqual(post.call_count, 1)
                prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
                self.assertIn("Speech recognition can add or mishear", prompt)


class ConflictUiChecks(unittest.TestCase):
    @patch("market_data.download_history", side_effect=saved_prices)
    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    def test_conflicting_target_requires_explicit_choice_and_updates_its_summary(self, submit, key, download):
        sol = next(r for r in checked_rows() if r["symbol"] == "SOL")
        submit.return_value = (completed([sol]), False)
        at = app(); at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        self.assertTrue(at.button(key="tt_calculate").disabled)
        self.assertEqual(at.text_input(key="tt_review_0_price_value").value, "")
        self.assertEqual(at.number_input(key="tt_review_0_year").value, 2025)
        at.button(key="tt_review_0_screen_target_0").click().run()
        self.assertFalse(at.button(key="tt_calculate").disabled)
        self.assertEqual(at.text_input(key="tt_review_0_price_value").value, "720")
        self.assertIn("$720", at.text_area(key="tt_review_0_claim").value)
        self.assertNotIn("$720,000", at.text_area(key="tt_review_0_claim").value)
        self.assertFalse(at.warning)
        at.button(key="tt_calculate").click().run()
        self.assertFalse(at.exception); self.assertFalse(at.error)
        result = at.session_state["tt_result"]["result"][0]
        self.assertEqual(result["price_target"]["target_usd"], 720)
        self.assertEqual(result["forecast_deadline"], "2025-12-31")
        self.assertEqual(sol["target_value"], 720000)

    @patch("market_data.download_history", side_effect=saved_prices)
    @patch("tiktok_ui.service_key", return_value="fixture-key")
    @patch("tiktok_ui.submit_import")
    def test_user_can_enter_a_personal_counterforecast_and_selections_stay_separate(self, submit, key, download):
        rows = [r for r in checked_rows() if r["symbol"] in {"SOL", "LINK"}]
        submit.return_value = (completed(rows), False)
        at = app(); at.text_input(key="tt_link").set_value(VIDEO).run()
        at.button(key="tt_analyse").click().run()
        at.text_input(key="tt_review_0_price_value").set_value("690").run()
        at.text_area(key="tt_review_0_claim").set_value("Creator's own USD 690 counterforecast.").run()
        at.selectbox(key="tt_choice").select_index(1).run()
        self.assertTrue(at.button(key="tt_calculate").disabled)
        self.assertEqual(at.text_input(key="tt_review_1_price_value").value, "")
        at.selectbox(key="tt_review_1_target_type").set_value("none").run()
        self.assertFalse(at.button(key="tt_calculate").disabled)
        at.selectbox(key="tt_choice").select_index(0).run()
        self.assertEqual(at.text_input(key="tt_review_0_price_value").value, "690")
        at.button(key="tt_calculate").click().run()
        self.assertFalse(at.exception); self.assertFalse(at.error)
        self.assertEqual(at.session_state["tt_result"]["result"][0]["price_target"]["target_usd"], 690)


if __name__ == "__main__":
    unittest.main()
