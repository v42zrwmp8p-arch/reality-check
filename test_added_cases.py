"""Source timing, original-security archives and their browser tracker routes."""
from copy import deepcopy
import json
from unittest.mock import Mock, patch
import unittest

import pandas as pd

import market_data
from market_data import load_examples, get_comparison_histories, get_case_histories
from case_analysis import analyse_comparisons
from tracker_core import prediction_record, tracker_records
from test_tracker import app, SimulatedBrowserStore, ROOT

DOGE = 'musk-dogecoin-20210428'
SAFE = 'portnoy-safemoon-20210517'
PELOSI = 'pelosi-nvidia-20231222'
BBBY = 'cohen-bbby-20220307'


def cases(): return {r['case_id']: r for r in load_examples()}


class AddedCaseChecks(unittest.TestCase):
    def test_public_dates_and_option_terms_do_not_become_price_forecasts(self):
        rows = cases()
        expected = {DOGE: '2021-04-29', SAFE: '2021-05-18', PELOSI: '2023-12-26', BBBY: '2022-03-08'}
        for key, entry in expected.items():
            row = rows[key]
            data = get_comparison_histories(row, fetch=Mock(side_effect=AssertionError('saved observations expected')))
            result, _, _ = analyse_comparisons(row, data)
            self.assertEqual(result['entry_date'], entry)
            self.assertIsNone(result['price_target']['target_usd'])
            self.assertIsNone(result['forecast_deadline'])
        self.assertGreater(rows[PELOSI]['publication_date'], '2023-11-22')
        self.assertIn('120', rows[PELOSI]['projection'])
        self.assertIn('2024', rows[PELOSI]['projection'])
        self.assertIn('not a price target', rows[PELOSI]['case_note'])
        self.assertIn('No USD 1 target', rows[DOGE]['case_note'])

    def test_refresh_never_substitutes_a_modern_token_or_reused_ticker(self):
        fetch = Mock(side_effect=AssertionError('no live asset or benchmark request needed'))
        for key, end, file_symbol in [(SAFE, '2021-10-04', 'SAFEMOON-V1'), (BBBY, '2023-05-02', 'BBBY-LEGACY')]:
            row = cases()[key]
            data = get_comparison_histories(row, force_live=True, fetch=fetch)
            expected = market_data.saved_history(file_symbol, row['publication_date'])
            pd.testing.assert_frame_equal(data['asset'], expected)
            self.assertEqual(data['return_basis'], 'price')
            for frame in data['benchmarks'].values():
                self.assertTrue(frame['Adj Close'].equals(frame['Close']))
            result, _, _ = analyse_comparisons(row, data)
            self.assertEqual(result['latest_close_date'], end)
            self.assertIn('history_note', result)
            legacy, _, _, _ = get_case_histories(row, force_live=True, fetch=fetch)
            pd.testing.assert_frame_equal(legacy, expected)
        fetch.assert_not_called()

    def test_wrong_or_missing_archive_fails_without_live_asset_fallback(self):
        fetch = Mock(side_effect=AssertionError('an archive failure must not request the current ticker'))
        row = cases()[BBBY]
        with patch('market_data.saved_history', return_value=None):
            with self.assertRaisesRegex(ValueError, 'archive is unavailable'):
                get_comparison_histories(row, True, fetch)
        for change in ({'history_archive': 'unknown'}, {'history_archive': {}}, {'history_archive': []}, {'symbol': 'NVDA'}, {'asset_type': 'Crypto'}):
            with self.assertRaisesRegex(ValueError, 'does not match'):
                get_comparison_histories(dict(row, **change), True, fetch)
        fetch.assert_not_called()

    def test_archived_quotes_match_source_checkpoints_and_zero_is_not_fabricated(self):
        frame = market_data.saved_history('BBBY-LEGACY', '2022-03-07')
        for day, close in [('2022-03-07', 21.71), ('2022-08-17', 23.08), ('2022-08-18', 18.55), ('2022-08-19', 11.03)]:
            self.assertAlmostEqual(frame.loc[day, 'Close'], close)
        self.assertTrue((frame['Close'] > 0).all())
        self.assertLess(frame.index[-1], pd.Timestamp('2023-09-29'))
        data = get_comparison_histories(cases()[BBBY])
        result, _, _ = analyse_comparisons(cases()[BBBY], data)
        self.assertIn('cancelled without value', result['terminal_status'])
        self.assertNotEqual(result['asset_return_pct'], -100)
        safe = market_data.saved_history('SAFEMOON-V1', '2021-05-17')
        self.assertAlmostEqual(safe.loc['2021-05-18', 'Close'], 0.00000847)
        self.assertTrue(safe['High'].isna().all())
        self.assertLess(safe.index[-1], pd.Timestamp('2021-12-01'))

    def test_archive_identity_survives_browser_record_validation(self):
        for key in (SAFE, BBBY):
            row = cases()[key]
            record = prediction_record(row)
            round_trip = tracker_records(json.loads(json.dumps([record])))[0]
            self.assertEqual(round_trip['history_archive'], row['history_archive'])
            self.assertNotEqual(round_trip['case_id'], row['case_id'])
            data = get_comparison_histories(round_trip, True, fetch=Mock(side_effect=AssertionError('no live fallback')))
            self.assertEqual(data['return_basis'], 'price')

    @patch('tracker_ui._storage')
    @patch('market_data.download_history', side_effect=AssertionError('all new views and archived tracker use saved data'))
    def test_new_views_and_archived_tracker_show_the_correct_history_limits(self, download, bridge):
        store = SimulatedBrowserStore(); bridge.side_effect = store
        at = app(); at.radio(key='mode').set_value('Case Database').run()
        for key in (DOGE, PELOSI, SAFE, BBBY):
            at.selectbox(key='case_selector').set_value(key).run()
            self.assertFalse(at.exception); self.assertFalse(at.error)
            self.assertTrue(at.get('vega_lite_chart'))
            if key in (SAFE, BBBY):
                self.assertIn('Asset price change', [m.label for m in at.metric])
                self.assertNotIn('update_prices', [b.key for b in at.button])
            else:
                self.assertIn('Asset return', [m.label for m in at.metric])
        self.assertTrue(any('cancelled without value' in x.value for x in at.info))
        for key, end in [(SAFE, '2021-10-04'), (BBBY, '2023-05-02')]:
            at.selectbox(key='case_selector').set_value(key).run()
            at.button(key='curated_track').click().run()
            at.radio(key='mode').set_value('My Tracker').run()
            self.assertFalse(at.exception); self.assertFalse(at.error)
            self.assertTrue(at.button(key='tracker_refresh').disabled)
            self.assertTrue(any(end in x.value for x in at.caption))
            at.radio(key='mode').set_value('Case Database').run()
        self.assertEqual(len(store.items), 2)
        download.assert_not_called()


if __name__ == '__main__': unittest.main()
