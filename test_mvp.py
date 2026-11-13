"""Focused checks for the arithmetic and the expandable case table."""
from pathlib import Path
import tempfile
import unittest
import pandas as pd
from analysis_core import compare_prices, period_metrics, horizon_table, check_price_target
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
        added["target_usd"] = ""
        added["target_basis"] = ""
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path = Path(folder) / "twenty.csv"
            pd.concat([original, added], ignore_index=True).to_csv(path, index=False)
            records = load_examples(path)
        self.assertEqual(len(records), 20)
        self.assertEqual(len({r["case_id"] for r in records}), 20)
        marvell = [r for r in records if r["symbol"] == "MRVL"]
        self.assertEqual(len(marvell), 2)
        self.assertEqual(marvell[0]["target_usd"], 142)
        self.assertIsNone(marvell[1]["target_usd"])
        asset, benchmark, symbol, _ = get_case_histories(marvell[1])
        result, _, _ = analyse_case(marvell[1], asset, benchmark, symbol)
        self.assertIsNone(result["price_target"]["target_usd"])

    def test_repeated_stock_different_dates(self):
        row = next(r for r in load_examples() if r["symbol"] == "MRVL")
        asset, benchmark, symbol, _ = get_case_histories(row)
        first, _, _ = analyse_case(row, asset, benchmark, symbol)
        later = dict(row, case_id="different-marvell-video", publication_date="2024-01-02", target_usd=None, projection="Another claim")
        second, _, _ = analyse_case(later, asset, benchmark, symbol)
        self.assertNotEqual(first["entry_date"], second["entry_date"])
        self.assertNotEqual(first["asset_return_pct"], second["asset_return_pct"])
        self.assertIsNone(second["price_target"]["target_usd"])


if __name__ == "__main__":
    unittest.main()
