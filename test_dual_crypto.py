"""Dual crypto comparisons using synthetic/saved observations and mocked APIs."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch
import unittest

import pandas as pd

from market_data import get_comparison_histories
from case_analysis import analyse_comparisons, comparison_dates
from charts import comparison_chart
from tracker_core import prediction_record
from test_tracker import app, ROOT, BASE, SimulatedBrowserStore
from test_tiktok_ui import completed
from test_tiktok_import import DRAFT, VIDEO

ALT = dict(BASE, case_id='fixture-kda', asset='Kadena', symbol='KDA-USD', asset_type='Crypto',
           publication_date='2024-02-01', target_type='none', target_value=None,
           deadline='2024-02-05', horizon_value=None, horizon_unit=None)


def frames():
    def make(dates, values):
        return pd.DataFrame({'Close':values,'Adj Close':values,'High':values,'Stock Splits':0},index=pd.to_datetime(dates))
    daily=['2024-02-02','2024-02-03','2024-02-04','2024-02-05','2024-02-06']
    return {'KDA-USD':make(daily,[100,180,130,150,160]),
            'BTC-USD':make(daily,[100,110,120,125,130]),
            'SPY':make(['2024-02-02','2024-02-05','2024-02-06'],[100,105,110])}


def synthetic_data(row=ALT):
    values=frames()
    return get_comparison_histories(row,force_live=True,fetch=lambda symbol,*args:(values[symbol],symbol))


def saved_download(symbol,*args):
    return pd.read_csv(ROOT/'prices'/f'{symbol}.csv',index_col='Date',parse_dates=True),symbol


class DualMathChecks(unittest.TestCase):
    def test_three_series_same_dates_returns_differences_deadline_and_chart(self):
        data=synthetic_data()
        summary,table,chart=analyse_comparisons(ALT,data)
        self.assertEqual(list(data['benchmarks']),['BTC-USD','SPY'])
        self.assertEqual(list(chart.index),list(data['benchmarks']['SPY'].index))
        self.assertEqual(chart.iloc[0].tolist(),[100,100,100])
        self.assertAlmostEqual(summary['asset_return_pct'],60)
        self.assertAlmostEqual(summary['comparisons']['BTC-USD']['return_pct'],30)
        self.assertAlmostEqual(summary['comparisons']['BTC-USD']['difference_pp'],30)
        self.assertAlmostEqual(summary['comparisons']['SPY']['return_pct'],10)
        self.assertAlmostEqual(summary['comparisons']['SPY']['difference_pp'],50)
        self.assertAlmostEqual(summary['comparisons']['SPY']['deadline_result']['metrics']['difference_pp'],45)
        self.assertIn('SPY_return_pct',table)
        self.assertIn('difference_vs_SPY_pp',table)
        self.assertAlmostEqual(table.iloc[-1]['difference_vs_SPY_pp'],50)
        spec=comparison_chart(chart,'KDA-USD','Bitcoin',summary['deadline_result'],{'Benchmark_SPY':'S&P 500 ETF (SPY)'}).to_dict()
        self.assertEqual(spec['layer'][0]['encoding']['color']['scale']['domain'],['KDA-USD','Bitcoin','S&P 500 ETF (SPY)'])
        self.assertTrue(any(layer.get('mark',{}).get('type')=='rule' for layer in spec['layer']))
        json.dumps(summary)  # The summary and per-benchmark deadline metadata must not be circular.

    def test_weekend_target_hit_remains_available_with_a_weekday_comparison(self):
        row=dict(ALT,target_type='price',target_value=170)
        summary,_,chart=analyse_comparisons(row,synthetic_data(row))
        self.assertNotIn(pd.Timestamp('2024-02-03'),chart.index)
        self.assertEqual(summary['price_target']['first_intraday_high_date'],'2024-02-03')
        self.assertEqual(summary['price_target']['status'],'Reached by cutoff')

    def test_saved_data_and_bitcoin_keep_the_expected_number_of_comparisons(self):
        fetch=Mock(side_effect=AssertionError('saved data should cover these examples'))
        for symbol,expected in [('KDA-USD',['BTC-USD','SPY']),('BTC-USD',['SPY'])]:
            row=dict(ALT,symbol=symbol,publication_date='2023-06-26',deadline=None)
            data=get_comparison_histories(row,fetch=fetch)
            self.assertEqual(list(data['benchmarks']),expected)
            self.assertEqual(data['source'],'Saved data snapshot')
        fetch.assert_not_called()

    def test_a_missing_reference_keeps_the_other_comparison_without_fabricating_values(self):
        values=frames()
        for missing in ['SPY','BTC-USD']:
            def fetch(symbol,*args):
                if symbol==missing:raise ValueError('simulated unavailable reference')
                return values[symbol],symbol
            data=get_comparison_histories(ALT,force_live=True,fetch=fetch)
            summary,table,chart=analyse_comparisons(ALT,data)
            self.assertEqual(summary['requested_benchmark_symbols'],['BTC-USD','SPY'])
            self.assertEqual(summary['unavailable_benchmarks'],[missing])
            self.assertNotIn(missing,summary['comparisons'])
            self.assertEqual(len(chart.columns),2)
            self.assertNotIn('SPY_return_pct',table)

    def test_both_reference_failures_and_insufficient_common_history_do_not_produce_returns(self):
        values=frames()
        def fetch(symbol,*args):
            if symbol!='KDA-USD':raise ValueError('simulated reference failure')
            return values[symbol],symbol
        with self.assertRaisesRegex(ValueError,'Comparison prices'):
            get_comparison_histories(ALT,force_live=True,fetch=fetch)
        data=synthetic_data();data['benchmarks']['SPY']=data['benchmarks']['SPY'].iloc[:1]
        self.assertEqual(len(comparison_dates(ALT,data)),1)
        with self.assertRaisesRegex(ValueError,'two positive'):
            analyse_comparisons(ALT,data)

    def test_batch_exports_both_references_to_summary_chart_and_period_files(self):
        import analyse_examples
        with tempfile.TemporaryDirectory() as folder:
            with patch('analyse_examples.ROOT',Path(folder)), patch('analyse_examples.load_examples',return_value=[ALT]), patch('analyse_examples.get_comparison_histories',return_value=synthetic_data()), redirect_stdout(StringIO()):
                analyse_examples.main()
            path=Path(folder)/'results'/ALT['case_id']
            summary=json.loads((path/'summary.json').read_text())
            self.assertEqual(set(summary['comparisons']),{'BTC-USD','SPY'})
            self.assertIn('Benchmark_SPY',pd.read_csv(path/'chart_data.csv'))
            self.assertIn('difference_vs_SPY_pp',pd.read_csv(path/'periods.csv'))
            self.assertIn('SPY_return_pct',pd.read_csv(Path(folder)/'results'/'current_summary.csv'))


@patch("yfinance.Ticker.get_info", new=lambda self: {})
class DualUiChecks(unittest.TestCase):
    @patch('market_data.download_history',side_effect=saved_download)
    def test_manual_altcoin_shows_two_references_six_metrics_and_export_columns(self,download):
        at=app();at.radio(key='mode').set_value('Manual Entry').run()
        at.selectbox(key='manual_type').set_value('Crypto').run()
        at.text_input(key='manual_ticker').set_value('KDA').run()
        at.button(key='manual_calculate').click().run()
        self.assertFalse(at.exception);self.assertFalse(at.error)
        self.assertEqual(len(at.metric),6)
        labels=[item.label for item in at.metric]
        self.assertIn('Bitcoin return',labels);self.assertIn('S&P 500 ETF (SPY) return',labels)
        self.assertIn('Difference vs Bitcoin',labels);self.assertIn('Difference vs SPY',labels)
        stored=at.session_state['manual_result']['result']
        self.assertEqual(set(stored[0]['comparisons']),{'BTC-USD','SPY'})
        self.assertIn('Benchmark_SPY',stored[2]);self.assertIn('SPY_return_pct',stored[1])

    @patch('tracker_ui._storage')
    @patch('market_data.download_history',side_effect=saved_download)
    def test_existing_tracker_has_both_comparisons_and_record_is_not_rewritten(self,download,bridge):
        store=SimulatedBrowserStore();store.items=[prediction_record(dict(ALT,publication_date='2023-06-26',deadline=None))]
        original=deepcopy(store.items);bridge.side_effect=store
        at=app();at.radio(key='mode').set_value('My Tracker').run()
        self.assertFalse(at.exception);self.assertFalse(at.error)
        self.assertEqual(len(at.metric),6)
        self.assertEqual(store.items,original)

    @patch('tiktok_ui.service_key',return_value='fixture-key')
    @patch('tiktok_ui.submit_import')
    @patch('market_data.download_history',side_effect=saved_download)
    def test_imported_crypto_has_both_comparisons_after_review(self,download,submit,key):
        row=dict(DRAFT,asset='Kadena',symbol='KDA-USD',asset_type='Crypto',target_type='none',target_value=None)
        submit.return_value=completed([row]),False
        at=app();at.text_input(key='tt_link').set_value(VIDEO).run();at.button(key='tt_analyse').click().run()
        at.button(key='tt_calculate').click().run()
        self.assertFalse(at.exception);self.assertFalse(at.error)
        self.assertEqual(set(at.session_state['tt_result']['result'][0]['comparisons']),{'BTC-USD','SPY'})
        self.assertEqual(len(at.metric),6)

    def test_old_single_reference_crypto_session_results_are_invalidated(self):
        at=app()
        for key in ('manual_result','tt_result'):
            at.session_state[key]={'row':ALT,'result':({'benchmark_symbol':'BTC-USD'},None,None)}
        at.run()
        self.assertFalse(at.exception)
        self.assertNotIn('manual_result',at.session_state);self.assertNotIn('tt_result',at.session_state)
        # A current partial result is valid; unavailable references are explicit.
        for key in ('manual_result','tt_result'):
            at.session_state[key]={'row':ALT,'result':({'benchmark_symbol':'BTC-USD','requested_benchmark_symbols':['BTC-USD','SPY']},None,None)}
        at.run()
        self.assertFalse(at.exception)
        self.assertIn('manual_result',at.session_state);self.assertIn('tt_result',at.session_state)


if __name__=='__main__':
    unittest.main()
