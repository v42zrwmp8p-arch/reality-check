"""Active iconic collection, reviewed split basis and context-only handling."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import json
from unittest.mock import patch
import unittest

import pandas as pd

from analysis_core import check_price_target, validated_split_review
from market_data import load_examples,get_comparison_histories
from case_analysis import analyse_comparisons
from tracker_core import prediction_record
from test_tracker import app,SimulatedBrowserStore,ROOT
from test_dual_crypto import saved_download

CATHIE='ark-tesla-20210319'
BEAR='cramer-bear-stearns-context-20080311'


def no_network(*args):raise AssertionError('all active numeric cases should use saved observations')


class IconicCaseChecks(unittest.TestCase):
    def test_only_iconic_additions_are_active(self):
        rows=load_examples();by_symbol={row['symbol']:row for row in rows}
        self.assertEqual(set(by_symbol),{'GME','COIN','TSLA','BTC-USD','BSC'})
        self.assertEqual(by_symbol['BSC']['case_type'],'context')
        self.assertFalse({'HD','LOW','CROX','MRVL','TSM','MU','NKLA','HERO','KDA','MTV'} & set(by_symbol))

    def test_cathie_target_has_verified_share_basis_and_explicit_year_end_convention(self):
        row=next(row for row in load_examples() if row['case_id']==CATHIE)
        self.assertEqual(row['target_value'],3000/3)
        self.assertEqual(row['reviewed_splits'],{'2022-08-25':3})
        self.assertIn('no exact day was stated',row['deadline_basis'])
        summary,_,_=analyse_comparisons(row,get_comparison_histories(row,fetch=no_network))
        self.assertEqual(summary['entry_date'],'2021-03-22')
        self.assertEqual(summary['deadline_result']['label'],'Evaluation date')
        self.assertTrue(summary['price_target']['split_adjustment_reviewed'])
        self.assertEqual(summary['price_target']['target_usd'],1000)
        self.assertEqual(summary['price_target']['status'],'Not reached by deadline')
        self.assertIsNone(summary['price_target']['creator_deadline'])
        self.assertEqual(summary['price_target']['evaluation_deadline'],'2025-12-31')

    def test_unreviewed_mismatched_or_extra_splits_still_block_target_evaluation(self):
        frame=pd.DataFrame({'Close':[200,210,220],'High':[205,215,225],'Stock Splits':[0,3,0]},
                           index=pd.to_datetime(['2022-08-24','2022-08-25','2022-08-26']))
        for review in (None,{'2022-08-25':4},{'2022-08-24':3}):
            result=check_price_target(frame,frame.index[0],frame.index[-1],1000,'fixture',reviewed_splits=review)
            self.assertIn('Manual split adjustment',result['status'])
        result=check_price_target(frame,frame.index[0],frame.index[-1],1000,'fixture',reviewed_splits={'2022-08-25':3})
        self.assertTrue(result['split_adjustment_reviewed'])
        frame.iloc[-1,frame.columns.get_loc('Stock Splits')]=2
        self.assertIn('Manual split adjustment',check_price_target(frame,frame.index[0],frame.index[-1],1000,'fixture',reviewed_splits={'2022-08-25':3})['status'])
        for invalid in ('not json',[],{'bad-date':3},{'2022-08-25':True},{'2022-08-25':0}):
            with self.assertRaises(ValueError):validated_split_review(invalid)

    def test_review_and_evaluation_basis_survive_tracking(self):
        source=next(row for row in load_examples() if row['case_id']==CATHIE)
        tracked=prediction_record(source)
        self.assertEqual(tracked['reviewed_splits'],source['reviewed_splits'])
        self.assertEqual(tracked['deadline_basis'],source['deadline_basis'])
        self.assertEqual(tracked['target_basis'],source['target_basis'])
        summary,_,_=analyse_comparisons(tracked,get_comparison_histories(tracked,fetch=no_network))
        self.assertTrue(summary['price_target']['split_adjustment_reviewed'])
        self.assertEqual(summary['deadline_result']['label'],'Evaluation date')

    @patch('market_data.download_history',side_effect=AssertionError('context case must not request prices'))
    def test_context_case_has_no_equity_returns_and_retired_selection_resets(self,download):
        at=app();at.session_state['case_selector']='6930016692546358533-HD'
        at.radio(key='mode').set_value('Case Database').run()
        self.assertFalse(at.exception);self.assertFalse(at.error)
        self.assertEqual(at.selectbox(key='case_selector').value,'roaring-kitty-gme-20200804')
        at.selectbox(key='case_selector').set_value(BEAR).run()
        self.assertFalse(at.exception);self.assertFalse(at.error)
        self.assertEqual(len(at.metric),0)
        self.assertTrue(any('Context case' in item.value for item in at.info))
        self.assertNotIn('curated_track',[item.key for item in at.button])
        self.assertTrue(any('Statement 2008-03-11' in item.value for item in at.caption))
        charts=at.get('vega_lite_chart')
        self.assertEqual(len(charts),1)
        spec=json.loads(charts[0].proto.spec)
        self.assertEqual(spec['layer'][0]['encoding']['y']['title'],'Share price (USD)')
        all_rows=[record for rows in spec.get('datasets',{}).values() for record in rows]
        all_rows += [record for layer in spec['layer'] for record in layer.get('data',{}).get('values',[])]
        self.assertTrue(any(row.get('Date')=='2008-03-11' and row.get('Label')=='Cramer statement' for row in all_rows))
        closes=[row for row in all_rows if 'Close' in row]
        self.assertTrue(any(row['Date']=='2008-03-17' and row['Close']==4.81 for row in closes))
        self.assertFalse(any(row['Close']==2 for row in closes))
        download.assert_not_called()

    @patch('tracker_ui._storage')
    @patch('market_data.download_history',side_effect=saved_download)
    def test_cathie_view_and_tracker_keep_evaluation_label_and_adjusted_target(self,download,bridge):
        store=SimulatedBrowserStore();bridge.side_effect=store
        at=app();at.radio(key='mode').set_value('Case Database').run()
        at.selectbox(key='case_selector').set_value(CATHIE).run()
        self.assertFalse(at.exception);self.assertFalse(at.error)
        self.assertTrue(any(item.value=='Target: USD 1,000' for item in at.subheader))
        self.assertTrue(any('Evaluation date: 2025-12-31' in item.value for item in at.caption))
        at.button(key='curated_track').click().run()
        self.assertEqual(store.items[0]['reviewed_splits'],{'2022-08-25':3})
        at.radio(key='mode').set_value('My Tracker').run()
        self.assertFalse(at.exception);self.assertFalse(at.error)
        self.assertTrue(any('Evaluation date: 2025-12-31' in item.value for item in at.caption))
        self.assertFalse(any('Manual split adjustment required' in item.value for item in at.markdown))

    def test_batch_skips_bear_context_and_calculates_four_cases(self):
        import analyse_examples
        def histories(row,force_live=False):return get_comparison_histories(row,False,fetch=no_network)
        with tempfile.TemporaryDirectory() as folder:
            with patch('analyse_examples.ROOT',Path(folder)),patch('analyse_examples.get_comparison_histories',side_effect=histories),redirect_stdout(StringIO()):
                analyse_examples.main()
            path=Path(folder)/'results'
            summary=pd.read_csv(path/'current_summary.csv')
            status=pd.read_csv(path/'case_status.csv')
            self.assertEqual(len(summary),4)
            self.assertEqual(len(status),5)
            self.assertIn('Context case',status.loc[status['case_id']==BEAR,'status'].iloc[0])
            self.assertFalse((path/BEAR/'summary.json').exists())


if __name__=='__main__':unittest.main()
