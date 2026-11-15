"""Target-relative closing gaps, distinct from investment returns and target hits."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from analysis_core import check_price_target
from case_analysis import analyse_case
from market_data import load_examples, get_comparison_histories
from test_tracker import app, SimulatedBrowserStore, ROOT
from test_dual_crypto import saved_download

CATHIE = 'ark-tesla-20210319'


def frame(values=(50, 80, 100, 300)):
    dates = pd.date_range('2024-01-02', periods=len(values))
    return pd.DataFrame({'Close': values, 'Adj Close': [10*x for x in values],
                         'High': [1.1*x for x in values], 'Stock Splits': 0}, index=dates)


@patch("yfinance.Ticker.get_info", new=lambda self: {})
class TargetGapChecks(unittest.TestCase):
    def test_profitable_investment_can_miss_target_by_50_percent_at_deadline(self):
        asset = frame()
        benchmark = frame((100, 105, 110, 115))
        row = dict(asset='Example', symbol='TEST', asset_type='Equity', publication_date='2024-01-01',
                   target_type='price', target_value=200, deadline='2024-01-04')
        result, _, _ = analyse_case(row, asset, benchmark, 'SPY')
        self.assertAlmostEqual(result['deadline_result']['metrics']['asset_return_pct'], 100)
        target = result['price_target']
        self.assertEqual(target['status'], 'Not reached by deadline')
        self.assertEqual(target['close_comparison'], dict(date='2024-01-04', close_usd=100,
                         difference_usd=-100, difference_pct=-50, period='deadline'))

    def test_running_and_unspecified_deadlines_use_latest_close_not_a_final_miss(self):
        asset = frame()
        for deadline in (None, '2025-01-01'):
            result = check_price_target(asset, asset.index[0], asset.index[-1], 400, 'test', deadline)
            self.assertEqual(result['close_comparison']['period'], 'latest')
            self.assertEqual(result['close_comparison']['date'], '2024-01-05')
            self.assertAlmostEqual(result['close_comparison']['difference_pct'], -25)
            self.assertNotEqual(result['status'], 'Not reached by deadline')

    def test_previous_target_hit_remains_a_hit_even_if_last_close_is_below(self):
        asset = frame((50, 100, 80)); asset.loc['2024-01-03', 'High'] = 250
        result = check_price_target(asset, asset.index[0], asset.index[-1], 200, 'test', '2024-01-04')
        self.assertEqual(result['status'], 'Reached by cutoff')
        self.assertEqual(result['first_intraday_high_date'], '2024-01-03')
        self.assertAlmostEqual(result['close_comparison']['difference_pct'], -60)
        asset = frame((50, 60, 30))
        result = check_price_target(asset, asset.index[0], asset.index[-1], 40, 'test')
        self.assertEqual(result['status'], 'At or above target at entry close')
        self.assertAlmostEqual(result['close_comparison']['difference_pct'], -25)

    def test_no_invented_gap_with_missing_prices_no_target_or_unreviewed_split(self):
        asset = frame()
        self.assertNotIn('close_comparison', check_price_target(asset, asset.index[0], asset.index[-1], None, 'test'))
        self.assertNotIn('close_comparison', check_price_target(asset, asset.index[0], asset.index[-1], 200, 'test', '2024-01-01'))
        asset.loc['2024-01-03', 'Stock Splits'] = 2
        self.assertNotIn('close_comparison', check_price_target(asset, asset.index[0], asset.index[-1], 200, 'test'))
        asset['Stock Splits'] = 0
        for missing in (float('nan'), float('inf'), 0, -1):
            asset.loc[asset.index[-1], 'Close'] = missing
            self.assertNotIn('close_comparison', check_price_target(asset, asset.index[0], asset.index[-1], 200, 'test'))
        for invalid in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                check_price_target(frame(), asset.index[0], asset.index[-1], invalid, 'test')

    @patch('tracker_ui._storage')
    @patch('market_data.download_history', side_effect=saved_download)
    def test_cathie_ui_and_tracker_show_year_end_close_and_gap(self, download, bridge):
        store = SimulatedBrowserStore(); bridge.side_effect = store
        at = app(); at.radio(key='mode').set_value('Case Database').run()
        at.selectbox(key='case_selector').set_value(CATHIE).run()
        self.assertFalse(at.exception); self.assertFalse(at.error)
        line = next(x.value for x in at.markdown if 'below target' in x.value)
        self.assertIn('2025-12-31', line)
        self.assertIn('USD 449.72', line)
        self.assertIn('55.03% below target', line)
        at.button(key='curated_track').click().run()
        at.radio(key='mode').set_value('My Tracker').run()
        self.assertFalse(at.exception); self.assertFalse(at.error)
        self.assertTrue(any(x.value == line for x in at.markdown))

    def test_old_target_results_are_discarded_but_current_split_review_states_remain(self):
        row = next(r for r in load_examples() if r['case_id'] == CATHIE)
        at = app(); at.radio(key='mode').set_value('Case Database').run()
        summary = dict(benchmark_symbol='SPY', price_target=dict(target_usd=1000))
        for key in ('manual_result', 'tt_result'):
            at.session_state[key] = dict(row=row, result=(deepcopy(summary), None, None))
        at.run(); self.assertFalse(at.exception)
        for key in ('manual_result', 'tt_result'): self.assertNotIn(key, at.session_state)
        summary['price_target'].update(close_comparison_version=1, status='Manual split adjustment required before target evaluation')
        for key in ('manual_result', 'tt_result'):
            at.session_state[key] = dict(row=row, result=(deepcopy(summary), None, None))
        at.run(); self.assertFalse(at.exception)
        for key in ('manual_result', 'tt_result'): self.assertIn(key, at.session_state)

    def test_batch_csv_exposes_the_same_target_relative_gap(self):
        import analyse_examples
        row = next(r for r in load_examples() if r['case_id'] == CATHIE)
        def histories(row, force_live=False):
            return get_comparison_histories(row, fetch=lambda *args: self.fail('saved prices expected'))
        with tempfile.TemporaryDirectory() as folder:
            with patch('analyse_examples.ROOT', Path(folder)), patch('analyse_examples.load_examples', return_value=[row]), \
                 patch('analyse_examples.get_comparison_histories', side_effect=histories), redirect_stdout(StringIO()):
                analyse_examples.main()
            result = pd.read_csv(Path(folder)/'results/current_summary.csv').iloc[0]
            self.assertEqual(result['target_close_date'], '2025-12-31')
            self.assertAlmostEqual(result['target_close_usd'], 449.72, places=2)
            self.assertAlmostEqual(result['target_difference_usd'], -550.28, places=2)
            self.assertAlmostEqual(result['target_difference_pct'], -55.028, places=3)


if __name__ == '__main__': unittest.main()
