"""Benchmark routing and shared-date math. Price requests are simulated."""
from copy import deepcopy
from unittest.mock import Mock, patch
import unittest

import pandas as pd

from market_data import get_case_histories
from case_analysis import analyse_case
from tracker_core import prediction_record
from test_tracker import app, SimulatedBrowserStore, BASE, ROOT

BTC = dict(BASE, asset='Bitcoin', symbol='BTC-USD', asset_type='Crypto',
           publication_date='2024-02-01', target_type='none', target_value=None,
           horizon_value=None, horizon_unit=None)


def synthetic_frames():
    def frame(dates, values):
        return pd.DataFrame({'Close':values,'Adj Close':values,'High':values,'Stock Splits':0},
                            index=pd.to_datetime(dates))
    return (frame(['2024-02-02','2024-02-03','2024-02-04','2024-02-05','2024-02-06'],[100,110,120,150,160]),
            frame(['2024-02-02','2024-02-05','2024-02-06'],[200,220,240]))


class BitcoinBenchmarkChecks(unittest.TestCase):
    def test_bitcoin_uses_spy_on_shared_dates_and_calculates_a_real_difference(self):
        btc,spy=synthetic_frames()
        fetch=Mock(side_effect=lambda symbol,*args:(btc if symbol=='BTC-USD' else spy,symbol))
        asset,benchmark,symbol,source=get_case_histories(BTC,force_live=True,fetch=fetch)
        summary,periods,chart=analyse_case(BTC,asset,benchmark,symbol)
        self.assertEqual([call.args[0] for call in fetch.call_args_list],['BTC-USD','SPY'])
        self.assertEqual(summary['benchmark_symbol'],'SPY')
        self.assertEqual(list(chart.index),list(spy.index))
        self.assertAlmostEqual(summary['asset_return_pct'],60)
        self.assertAlmostEqual(summary['benchmark_return_pct'],20)
        self.assertAlmostEqual(summary['difference_pp'],40)
        self.assertEqual(chart.iloc[0].tolist(),[100,100])

    def test_saved_bitcoin_comparison_uses_spy_snapshot_without_requests(self):
        fetch=Mock(side_effect=AssertionError('saved observations should cover this case'))
        row=dict(BTC,publication_date='2023-06-26')
        asset,benchmark,symbol,source=get_case_histories(row,fetch=fetch)
        self.assertEqual(symbol,'SPY')
        self.assertEqual(source,'Saved data snapshot')
        self.assertFalse(asset['Adj Close'].equals(benchmark['Adj Close']))
        fetch.assert_not_called()

    def test_btc_alias_other_crypto_and_etf_select_the_expected_comparison(self):
        frame,_=synthetic_frames()
        for ticker,kind,expected_symbol,expected_comparison in [
            ('BTC','Crypto','BTC-USD','SPY'),('KDA','Crypto','KDA-USD','BTC-USD'),('VTI','ETF','VTI','SPY')]:
            with self.subTest(ticker=ticker):
                fetch=Mock(return_value=(frame,ticker))
                row=dict(BTC,symbol=ticker,asset_type=kind)
                _,_,benchmark,_=get_case_histories(row,force_live=True,fetch=fetch)
                self.assertEqual(benchmark,expected_comparison)
                self.assertEqual([call.args[0] for call in fetch.call_args_list],[expected_symbol,expected_comparison])


class BitcoinBenchmarkUiChecks(unittest.TestCase):
    @patch('market_data.download_history')
    def test_manual_bitcoin_displays_spy_comparison(self,download):
        download.side_effect=lambda symbol,*args:(pd.read_csv(ROOT/'prices'/f'{symbol}.csv',index_col='Date',parse_dates=True),symbol)
        at=app();at.radio(key='mode').set_value('Manual Entry').run()
        at.selectbox(key='manual_type').set_value('Crypto').run()
        at.text_input(key='manual_ticker').set_value('BTC').run()
        at.button(key='manual_calculate').click().run()
        self.assertFalse(at.exception);self.assertFalse(at.error)
        self.assertEqual(at.session_state['manual_result']['result'][0]['benchmark_symbol'],'SPY')
        self.assertIn('S&P 500 ETF (SPY) return',[item.label for item in at.metric])

    @patch('tracker_ui._storage')
    @patch('market_data.download_history')
    def test_existing_bitcoin_tracker_record_opens_with_spy(self,download,bridge):
        # The record itself is unchanged; its comparison is selected on opening.
        store=SimulatedBrowserStore();store.items=[prediction_record(dict(BTC,publication_date='2023-06-26'))]
        original=deepcopy(store.items);bridge.side_effect=store
        download.side_effect=lambda symbol,*args:(pd.read_csv(ROOT/'prices'/f'{symbol}.csv',index_col='Date',parse_dates=True),symbol)
        at=app();at.radio(key='mode').set_value('My Tracker').run()
        self.assertFalse(at.exception);self.assertFalse(at.error)
        self.assertIn('S&P 500 ETF (SPY) return',[item.label for item in at.metric])
        self.assertEqual(store.items,original)

    def test_cached_self_comparisons_are_discarded_but_current_results_remain(self):
        at=app()
        for key in ('manual_result','tt_result'):
            at.session_state[key]={'row':BTC,'result':({'benchmark_symbol':'BTC-USD'},None,None)}
        at.run()
        self.assertFalse(at.exception)
        self.assertNotIn('manual_result',at.session_state)
        self.assertNotIn('tt_result',at.session_state)
        for key in ('manual_result','tt_result'):
            at.session_state[key]={'row':BTC,'result':({'benchmark_symbol':'SPY'},None,None)}
        at.run()
        self.assertFalse(at.exception)
        self.assertIn('manual_result',at.session_state)
        self.assertIn('tt_result',at.session_state)


if __name__=='__main__':
    unittest.main()
