"""Tracker records and UI flows; browser/API boundaries below are simulated."""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest

from tracker_core import (prediction_record, tracker_document, read_tracker, tracker_records,
                          forecast_status, forecast_label, tracker_comparison, MAX_BYTES)
from test_tiktok_import import VIDEO, DRAFT
from test_tiktok_ui import completed

ROOT = Path(__file__).resolve().parent
BASE = {"asset":"Nvidia", "symbol":"NVDA", "asset_type":"Equity", "publication_date":"2024-01-01",
        "creator":"@fixture", "projection":"Could double within one year.", "video_url":VIDEO,
        "target_type":"multiple", "target_value":2, "reference_type":"entry", "horizon_value":1,
        "horizon_unit":"years", "time_frame":"one year"}


@patch("yfinance.Ticker.get_info", new=lambda self: {})
class RecordChecks(unittest.TestCase):
    def test_only_prediction_facts_survive_backup_round_trip(self):
        source = dict(BASE, transcript="not saved", api_key="fixture-secret", photo_text="not saved",
                      metadata={"private":"not saved"}, task=object(), source_kind="photo")
        row = prediction_record(source)
        data = json.dumps(tracker_document([row])).encode()
        for forbidden in [b'fixture-secret', b'transcript', b'photo_text', b'metadata', b'task']:
            self.assertNotIn(forbidden, data)
        restored = read_tracker(data)
        self.assertEqual(restored, [row])
        self.assertEqual(restored[0]["source_kind"], "photo")
        self.assertEqual(restored[0]["target_value"], 2)

    def test_identity_separates_posts_and_assets_but_updates_target(self):
        original = prediction_record(BASE)
        changed = prediction_record(dict(BASE,target_value=3))
        self.assertEqual(original['tracker_id'], changed['tracker_id'])
        other_asset = prediction_record(dict(BASE,symbol='CROX'))
        other_post = prediction_record(dict(BASE,video_url=VIDEO.replace('/7249072169680948526','/7249072169680948527')))
        self.assertEqual(len({original['tracker_id'],other_asset['tracker_id'],other_post['tracker_id']}),3)
        self.assertEqual(len(tracker_records([original,changed])),1)
        self.assertNotEqual(prediction_record(dict(BASE,video_url='',publication_date='2024-01-01'))['tracker_id'],
                            prediction_record(dict(BASE,video_url='',publication_date='2024-01-02'))['tracker_id'])

    def test_invalid_records_and_unsafe_links_are_rejected_before_storage(self):
        bad = [dict(BASE,publication_date='nonsense'), dict(BASE,publication_date=(date.today()+timedelta(days=1)).isoformat()),
               dict(BASE,symbol='bad/ticker'), dict(BASE,target_value=float('inf')), dict(BASE,target_value=True),
               dict(BASE,reference_type='creator',reference_price=-1), dict(BASE,asset_type='unknown'),
               dict(BASE,deadline='2023-01-01'), dict(BASE,horizon_value=1.5),
               dict(BASE,video_url='javascript:alert(1)'), dict(BASE,video_url='https://user:pw@example.com/x'),
               dict(BASE,projection='x'*2001)]
        for row in bad:
            with self.subTest(row=row), self.assertRaises(ValueError):
                prediction_record(row)
        for data in [b'not json',b'[]',b'{"schema_version":42,"items":[]}', b'x'*(MAX_BYTES+1),
                     json.dumps({'schema_version':1,'items':[BASE]*101}).encode()]:
            with self.assertRaises(ValueError):
                read_tracker(data)

    def test_status_describes_time_not_a_prediction_verdict(self):
        row = prediction_record(BASE)
        self.assertEqual(forecast_status(row,date(2024,12,31)),('Tracking','1 day left · 2025-01-01'))
        self.assertEqual(forecast_status(row,date(2025,1,1)),('Deadline reached','2025-01-01'))
        self.assertEqual(forecast_status(dict(row,horizon_value=None,time_frame='soon'),date(2030,1,1)),('Tracking','soon'))
        self.assertEqual(forecast_label(dict(row,target_type='price',target_value=0.00012)), 'USD 0.00012')

    def test_new_prediction_needs_no_prices_and_one_close_has_no_invented_return(self):
        fetch = Mock()
        row = prediction_record(dict(BASE,publication_date=date.today().isoformat()))
        result, message = tracker_comparison(row,fetch)
        self.assertIsNone(result);fetch.assert_not_called()
        frame = pd.DataFrame({'Adj Close':[100],'Close':[100],'High':[100],'Stock Splits':[0]},
                             index=pd.to_datetime(['2024-01-02']))
        fetch.return_value = {'asset':frame,'benchmarks':{'SPY':frame},'requested':['SPY'],'unavailable':[],'source':'fixture'}
        result,message = tracker_comparison(prediction_record(BASE),fetch)
        self.assertIsNone(result)
        self.assertIn('Not enough',message)

    def test_existing_math_and_forced_current_data_are_used_for_a_tracked_case(self):
        frame = pd.DataFrame({'Adj Close':[100,120],'Close':[100,120],'High':[100,121],'Stock Splits':[0,0]},
                             index=pd.to_datetime(['2024-01-02','2024-01-03']))
        fetch = Mock(return_value={'asset':frame,'benchmarks':{'SPY':frame},'requested':['SPY'],'unavailable':[],'source':'simulated price observations'})
        row = prediction_record(BASE)
        result,_ = tracker_comparison(row,fetch)
        self.assertAlmostEqual(result[0]['asset_return_pct'],20)
        self.assertEqual(result[0]['entry_date'],'2024-01-02')
        fetch.assert_called_once_with(row,force_live=True)

    @unittest.skipUnless(shutil.which('node'), 'Node is needed only for the frontend contract test')
    def test_frontend_storage_contract(self):
        result=subprocess.run(['node',str(ROOT/'test_tracker_storage.mjs')],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Frontend storage contract passed',result.stdout)


class SimulatedBrowserStore:
    def __init__(self):
        self.items=[]
        self.error=None
    def __call__(self,*,data,**kwargs):
        operation=data.get('operation')
        if operation and not self.error:
            by_id={r['tracker_id']:r for r in self.items}
            if operation['kind']=='remove':
                by_id.pop(operation['tracker_id'],None)
            else:
                for row in operation['items']:
                    by_id[row['tracker_id']]=deepcopy(row)
            self.items=list(by_id.values())
        return SimpleNamespace(reply={'request_id':data['request_id'],'items':deepcopy(self.items),'error':self.error})


def app():
    return AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()


@patch("yfinance.Ticker.get_info", new=lambda self: {})
class TrackerUiChecks(unittest.TestCase):
    @patch('tracker_ui._storage')
    @patch('market_data.download_history')
    def test_manual_save_today_reopen_in_new_session_and_remove_without_market_requests(self,download,bridge):
        store=SimulatedBrowserStore();bridge.side_effect=store
        at=app();at.radio(key='mode').set_value('Manual Entry').run()
        at.date_input(key='manual_date').set_value(date.today()).run()
        at.selectbox(key='manual_target_type').set_value('Price multiple').run()
        at.number_input(key='manual_multiple').set_value(3.0).run()
        at.text_input(key='manual_creator').set_value('@fixture').run()
        at.text_area(key='manual_claim').set_value('Could triple.').run()
        at.button(key='manual_track').click().run()
        self.assertFalse(at.exception)
        self.assertEqual(len(store.items),1)
        self.assertEqual(store.items[0]['target_value'],3)
        download.assert_not_called()
        other_session=app();other_session.radio(key='mode').set_value('My Tracker').run()
        self.assertFalse(other_session.exception);self.assertFalse(other_session.error)
        self.assertEqual(len(other_session.session_state['tracker_items']),1)
        self.assertEqual(len(other_session.metric),0)
        self.assertTrue(any('Tracking starts' in item.value for item in other_session.info))
        download.assert_not_called()
        other_session.button(key='tracker_remove').click().run()
        self.assertEqual(store.items,[])
        self.assertFalse(other_session.exception)

    @patch('tracker_ui._storage')
    @patch('tiktok_ui.service_key',return_value='fixture-key')
    @patch('tiktok_ui.submit_import')
    @patch('market_data.download_history')
    def test_only_selected_reviewed_import_is_tracked_without_video_or_price_work(self,download,submit,key,bridge):
        store=SimulatedBrowserStore();bridge.side_effect=store
        submit.return_value=completed([DRAFT,dict(DRAFT,asset='Crocs',symbol='CROX',target_type='multiple',target_value=3,
                                                  reference_price=106,horizon_value=2,horizon_unit='years')]),False
        at=app();at.radio(key='mode').set_value('Import TikTok').run()
        at.text_input(key='tt_link').set_value(VIDEO).run();at.button(key='tt_analyse').click().run()
        at.selectbox(key='tt_choice').select_index(1).run()
        at.button(key='tt_track').click().run()
        self.assertFalse(at.exception);self.assertFalse(at.error)
        self.assertEqual(len(store.items),1)
        self.assertEqual(store.items[0]['symbol'],'CROX')
        self.assertEqual(store.items[0]['reference_price'],106)
        self.assertEqual(store.items[0]['horizon_value'],2)
        self.assertNotIn('transcript',store.items[0]);download.assert_not_called()
        at.text_input(key='tt_review_1_multiple_value').set_value('4').run()
        at.button(key='tt_track').click().run()
        self.assertEqual(len(store.items),1)
        self.assertEqual(store.items[0]['target_value'],4)

    @patch('tracker_ui._storage')
    @patch('market_data.download_history',side_effect=ValueError('Fixture prices unavailable'))
    def test_unavailable_prices_preserve_saved_prediction_and_retry_ui(self,download,bridge):
        store=SimulatedBrowserStore();store.items=[prediction_record(BASE)];bridge.side_effect=store
        at=app();at.radio(key='mode').set_value('My Tracker').run()
        self.assertFalse(at.exception);self.assertFalse(at.error)
        self.assertEqual(len(store.items),1)
        self.assertTrue(any('Fixture prices unavailable' in item.value for item in at.info))
        self.assertEqual(len(at.metric),0)
        at.button(key='tracker_refresh').click().run()
        self.assertGreaterEqual(download.call_count,2)

    @patch('tracker_ui._storage')
    @patch('market_data.download_history')
    def test_historical_tracker_uses_full_existing_results_and_retains_prediction(self,download,bridge):
        store=SimulatedBrowserStore();store.items=[prediction_record(dict(BASE,symbol='CROX'))];bridge.side_effect=store
        # Saved SPY observations serve only as a functional UI fixture.
        frame=pd.read_csv(ROOT/'prices'/'SPY.csv',index_col='Date',parse_dates=True)
        download.side_effect=lambda symbol,*args:(frame.copy(),symbol)
        at=app();at.radio(key='mode').set_value('My Tracker').run()
        self.assertFalse(at.exception);self.assertFalse(at.error)
        self.assertEqual(len(at.metric),4)
        self.assertTrue(any(item.value=='What happened next' for item in at.subheader))
        self.assertEqual(at.session_state['tracker_items'][0]['symbol'],'CROX')
        self.assertNotIn('result',store.items[0])
        self.assertTrue(any('Deadline reached' in item.value for item in at.caption))

    @patch('tracker_ui._storage')
    def test_storage_error_does_not_report_success_or_allow_tracking(self,bridge):
        store=SimulatedBrowserStore();store.error='Fixture browser storage denied';bridge.side_effect=store
        at=app();at.radio(key='mode').set_value('Manual Entry').run()
        self.assertTrue(at.button(key='manual_track').disabled)
        self.assertTrue(any('storage denied' in item.value for item in at.error))
        self.assertEqual(store.items,[])
        self.assertFalse(any('Saved to My Tracker' in item.value for item in at.success))


if __name__=='__main__':
    unittest.main()
