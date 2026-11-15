"""Real-source curated cases and preserved observations; no live API requests."""
from pathlib import Path
import json
import hashlib
from unittest.mock import patch
import unittest

import pandas as pd

import market_data
from market_data import load_examples,get_comparison_histories
from case_analysis import analyse_comparisons
from test_tracker import app,SimulatedBrowserStore
from test_dual_crypto import saved_download

ROOT=Path(__file__).resolve().parent
IDS=['roaring-kitty-gme-20200804','cramer-coinbase-20210413','pompliano-bitcoin-20190624']


def no_network(*args):
    raise AssertionError('saved observations must cover every curated case')


@patch("yfinance.Ticker.get_info", new=lambda self: {})
class SpecialCaseChecks(unittest.TestCase):
    def test_sources_dates_and_saved_histories_are_available(self):
        rows={row['case_id']:row for row in load_examples()}
        sources=json.loads((ROOT/'case_sources.json').read_text())
        for case,entry in zip(sources['cases'],['2020-08-05','2021-04-14','2019-06-25']):
            row=rows[case['case_id']]
            self.assertEqual(row['publication_date'],case['published'])
            self.assertEqual(row['video_url'],case['url'])
            data=get_comparison_histories(row,fetch=no_network)
            summary,periods,chart=analyse_comparisons(row,data)
            self.assertEqual(summary['entry_date'],entry)
            self.assertEqual(summary['latest_close_date'],'2026-11-12')
            self.assertEqual(data['source'],'Saved data snapshot')
            self.assertGreater(len(chart),100)
        self.assertEqual(len(rows),9)

    def test_pompliano_gain_is_separate_from_a_missed_deadline_target(self):
        row=next(row for row in load_examples() if row['case_id']==IDS[2])
        summary,_,_=analyse_comparisons(row,get_comparison_histories(row,fetch=no_network))
        self.assertEqual(summary['forecast_deadline'],'2021-12-31')
        self.assertGreater(summary['deadline_result']['metrics']['asset_return_pct'],0)
        self.assertEqual(summary['price_target']['target_usd'],100000)
        self.assertEqual(summary['price_target']['status'],'Not reached by deadline')
        self.assertIsNone(summary['price_target']['first_intraday_high_date'])

    def test_cramer_purchase_ceiling_and_kitty_bullish_thesis_are_not_numeric_forecasts(self):
        rows={row['case_id']:row for row in load_examples()}
        for case_id in IDS[:2]:
            row=rows[case_id]
            self.assertEqual(row['target_type'],'none')
            self.assertIsNone(row['target_value'])
            summary,_,_=analyse_comparisons(row,get_comparison_histories(row,fetch=no_network))
            self.assertIsNone(summary['price_target']['target_usd'])
            self.assertIsNone(summary['forecast_deadline'])
        self.assertIn('475',rows[IDS[1]]['evidence'])

    def test_recorded_original_price_rows_remain_present_in_extended_files(self):
        info=json.loads((ROOT/'case_sources.json').read_text())
        for extension in info['price_extensions']:
            frame=pd.read_csv(ROOT/'prices'/(extension['symbol']+'.csv'))
            old=frame.loc[frame['Date']>=extension['old_first']]
            self.assertEqual(len(frame)-len(old),extension['added_older_rows'])
            lines=(ROOT/'prices'/(extension['symbol']+'.csv')).read_bytes().splitlines(keepends=True)
            start=next(i for i,line in enumerate(lines) if line.startswith((extension['old_first']+',').encode()))
            recovered=lines[0]+b''.join(lines[start:])
            self.assertEqual(hashlib.sha256(recovered).hexdigest(),extension['previous_sha256'])
            self.assertFalse(frame['Date'].duplicated().any())

    @patch('tracker_ui._storage')
    @patch('market_data.download_history',side_effect=saved_download)
    def test_featured_cases_render_and_newsletter_can_be_saved_to_tracker(self,download,bridge):
        store=SimulatedBrowserStore();bridge.side_effect=store
        at=app();at.radio(key='mode').set_value('Case Database').run()
        self.assertFalse(at.exception);self.assertFalse(at.error)
        self.assertEqual(at.selectbox(key='case_selector').value,IDS[0])
        self.assertEqual(len(at.selectbox(key='case_selector').options),9)
        self.assertIn('Source excerpt',[item.label for item in at.expander])
        for case_id in IDS[1:]:
            at.selectbox(key='case_selector').set_value(case_id).run()
            self.assertFalse(at.exception);self.assertFalse(at.error)
        self.assertTrue(any(item.value=='Target: USD 100,000' for item in at.subheader))
        at.button(key='curated_track').click().run()
        self.assertFalse(at.exception);self.assertFalse(at.error)
        self.assertEqual(store.items[0]['source_kind'],'article')
        self.assertEqual(store.items[0]['target_value'],100000)
        self.assertEqual(store.items[0]['deadline'],'2021-12-31')
        at.radio(key='mode').set_value('My Tracker').run()
        self.assertFalse(at.exception);self.assertFalse(at.error)


if __name__=='__main__':
    unittest.main()
