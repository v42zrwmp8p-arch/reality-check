"""Focused checks for the arithmetic and the expandable case table."""
from pathlib import Path
import tempfile
import unittest
import pandas as pd
from analysis_core import (compare_prices, period_metrics, horizon_table, check_price_target,
                           resolve_target, resolve_deadline, deadline_performance)
from charts import comparison_chart
from case_analysis import analyse_case
from market_data import load_examples, get_case_histories

ROOT = Path(__file__).resolve().parent


class MvpChecks(unittest.TestCase):
    def test_returns_and_drawdown(self):
        dates = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
        a = pd.Series([50, 100, 150, 75, 120], index=dates)
        b = pd.Series([50, 100, 110, 90, 105], index=dates)
        prices = compare_prices(a, b, "2024-01-01")
        self.assertEqual(prices.index[0], pd.Timestamp("2024-01-02"))
        result = period_metrics(prices)
        for key, expected in [("asset_return_pct", 20), ("benchmark_return_pct", 5), ("difference_pp", 15), ("max_drawdown_pct", -50)]:
            self.assertAlmostEqual(result[key], expected)

    def test_calendar_horizons(self):
        prices = pd.DataFrame({"Asset": [100, 110, 120], "Benchmark": [100, 105, 110]},
                              index=pd.to_datetime(["2024-01-31", "2024-02-28", "2024-03-01"]))
        table = horizon_table(prices)
        self.assertEqual(list(table["period"]), ["1 month", "Latest available"])
        self.assertEqual(table.iloc[0]["target_date"], "2024-02-29")
        self.assertEqual(table.iloc[0]["observation_date"], "2024-02-28")

    def test_targets_and_deadlines(self):
        frame = pd.DataFrame({"Close": [100, 110, 150], "High": [200, 145, 151], "Stock Splits": [0, 0, 0]},
                             index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]))
        hit = check_price_target(frame, frame.index[0], frame.index[-1], 142, "test")
        self.assertEqual(hit["first_intraday_high_date"], "2024-01-03")
        missed = check_price_target(frame, frame.index[0], frame.index[-1], 149, "test", "2024-01-03")
        self.assertEqual(missed["status"], "Not reached by deadline")
        frame.loc[frame.index[-1], "Stock Splits"] = 2
        split = check_price_target(frame, frame.index[0], frame.index[-1], 149, "test", "2024-01-03")
        self.assertIn("Manual split adjustment", split["status"])

    def test_table_can_grow_to_twenty(self):
        original = pd.read_csv(ROOT / "predictions.csv", keep_default_na=False)
        added = original.copy()
        added["case_id"] = ""
        added["video_url"] = [f"https://example.invalid/video/additional-{i}" for i in range(10)]
        added["projection"] = "Additional test claim"
        added["target_type"] = "none"
        added["target_value"] = ""
        added["reference_type"] = ""
        added["reference_price"] = ""
        added["target_basis"] = ""
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path = Path(folder) / "twenty.csv"
            pd.concat([original, added], ignore_index=True).to_csv(path, index=False)
            records = load_examples(path)
        self.assertEqual(len(records), 20)
        self.assertEqual(len({r["case_id"] for r in records}), 20)
        marvell = [r for r in records if r["symbol"] == "MRVL"]
        self.assertEqual(len(marvell), 2)
        self.assertEqual(marvell[0]["target_value"], 142)
        self.assertEqual(marvell[1]["target_type"], "none")
        asset, benchmark, symbol, _ = get_case_histories(marvell[1])
        result, _, _ = analyse_case(marvell[1], asset, benchmark, symbol)
        self.assertIsNone(result["price_target"]["target_usd"])

    def test_repeated_stock_different_dates(self):
        row = next(r for r in load_examples() if r["symbol"] == "MRVL")
        asset, benchmark, symbol, _ = get_case_histories(row)
        first, _, _ = analyse_case(row, asset, benchmark, symbol)
        later = dict(row, case_id="different-marvell-video", publication_date="2024-01-02", target_type="none", target_value=None, projection="Another claim")
        second, _, _ = analyse_case(later, asset, benchmark, symbol)
        self.assertNotEqual(first["entry_date"], second["entry_date"])
        self.assertNotEqual(first["asset_return_pct"], second["asset_return_pct"])
        self.assertIsNone(second["price_target"]["target_usd"])

    def test_explicit_multiples_and_reference_prices(self):
        for multiple, expected in [(2, 100), (10, 500)]:
            goal = resolve_target({"target_type": "multiple", "target_value": multiple, "reference_type": "entry"}, 50)
            self.assertEqual(goal["target_usd"], expected)
            self.assertEqual(goal["reference_price"], 50)
        creator = resolve_target({"target_type": "multiple", "target_value": 3, "reference_type": "creator", "reference_price": 106}, 110)
        self.assertEqual(creator["target_usd"], 318)
        self.assertEqual(creator["reference_price"], 106)
        absolute = resolve_target({"target_type": "price", "target_value": 142}, 60)
        self.assertEqual(absolute["target_usd"], 142)
        self.assertIsNone(absolute["reference_price"])

    def test_prose_is_not_a_target_and_invalid_goals_fail(self):
        self.assertIsNone(resolve_target({"projection": "10x", "asset_type": "Crypto"}, 10)["target_usd"])
        for value in [0, 1, -2, float("inf"), float("nan")]:
            with self.assertRaises(ValueError):
                resolve_target({"target_type": "multiple", "target_value": value}, 50)
        with self.assertRaises(ValueError):
            resolve_target({"target_type": "multiple", "target_value": 2, "reference_type": "creator"}, 50)

    def test_structured_horizon_and_vague_horizon(self):
        deadline, _ = resolve_deadline({"publication_date": "2024-12-21", "horizon_value": 10, "horizon_unit": "years"})
        self.assertEqual(deadline, "2034-12-21")
        self.assertIsNone(resolve_deadline({"publication_date": "2024-01-01", "time_frame": "next few weeks"})[0])
        self.assertEqual(resolve_deadline({"publication_date": "2024-01-31", "horizon_value": 1, "horizon_unit": "months"})[0], "2024-02-29")

    def test_weekend_deadline_and_later_history(self):
        prices = pd.DataFrame({"Asset": [100, 120, 80], "Benchmark": [100, 110, 115]},
                              index=pd.to_datetime(["2024-01-04", "2024-01-05", "2024-01-08"]))
        result = deadline_performance(prices, "2024-01-07")
        self.assertEqual(result["status"], "elapsed")
        self.assertEqual(result["observation_date"], "2024-01-05")
        self.assertAlmostEqual(result["metrics"]["asset_return_pct"], 20)
        self.assertAlmostEqual(period_metrics(prices)["asset_return_pct"], -20)
        self.assertIsNone(deadline_performance(prices, "2030-01-01")["metrics"])
        self.assertEqual(deadline_performance(prices, "2024-01-01")["status"], "before_entry")
        spec = comparison_chart(100 * prices / prices.iloc[0], "Asset", "Benchmark", result).to_dict()
        self.assertTrue(any(layer.get("mark", {}).get("type") == "rule" for layer in spec["layer"]))
        future = comparison_chart(prices, "Asset", "Benchmark", deadline_performance(prices, "2030-01-01")).to_dict()
        self.assertFalse(any(layer.get("mark", {}).get("type") == "rule" for layer in future["layer"]))

    def test_curated_results_preserved_and_targets_migrated(self):
        for row in load_examples():
            if row["symbol"] == "VTIQ / NKLA":
                continue
            asset, benchmark, symbol, _ = get_case_histories(row)
            summary, _, _ = analyse_case(row, asset, benchmark, symbol)
            if row["symbol"] == "MRVL":
                self.assertAlmostEqual(summary["asset_return_pct"], 174.27790278366473)
                self.assertEqual(summary["price_target"]["target_usd"], 142)
            elif row["symbol"] == "CROX":
                self.assertEqual(summary["price_target"]["target_usd"], 318)
            elif row["asset_type"] == "Crypto":
                self.assertEqual(summary["price_target"]["target_value"], 10)
            elif row["symbol"] in {"TSM", "MU"}:
                self.assertEqual(summary["forecast_deadline"], "2034-12-21")
                self.assertEqual(summary["deadline_result"]["status"], "not_covered")


if __name__ == "__main__":
    unittest.main()
