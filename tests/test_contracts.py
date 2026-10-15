"""Synthetic tests only: no production writes, network or environment-file reads."""
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from analytics import data_access as da, flush, vol, zscores, regime_returns
from analytics.health import coverage_details
from analytics.snapshot import briefing_facts
from collectors import common
from collectors.run_status import collection_succeeded


class ParquetContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(da, 'DATA_DIR', self.root), patch.object(common, 'DATA_DIR', self.root)]
        for replacement in self.patches:
            replacement.start()

    def tearDown(self):
        for replacement in self.patches:
            replacement.stop()
        self.temp.cleanup()

    def write(self, table, name, rows):
        directory = self.root / table
        directory.mkdir(exist_ok=True)
        frame = pd.DataFrame(rows)
        frame['ts'] = pd.to_datetime(frame['ts'], utc=True)
        frame.to_parquet(directory / name, index=False)

    def test_complete_latest_row_wins_without_field_mixing(self):
        base = dict(symbol='BTC', ts='2026-01-01', exchange='binance')
        self.write('funding', 'a.parquet', [base | dict(rate=.008, interval_h=1, ingested_at=pd.Timestamp('2026-01-02', tz='UTC'))])
        self.write('funding', 'b.parquet', [base | dict(rate=.004, interval_h=8, ingested_at=pd.Timestamp('2026-01-03', tz='UTC'))])
        self.assertAlmostEqual(da.load_funding().iloc[0]['rate'], .004)
        selected = da.load_table('funding').iloc[0]
        self.assertEqual(selected['_duplicate_count'], 1)
        self.assertFalse(selected['_legacy'])

    def test_legacy_order_is_deterministic_and_missing_interval_is_excluded(self):
        base = dict(symbol='BTC', ts='2026-01-01', exchange='binance')
        self.write('funding', 'a.parquet', [base | dict(rate=.008, interval_h=1)])
        self.write('funding', 'b.parquet', [base | dict(rate=.004, interval_h=8)])
        self.assertAlmostEqual(da.load_funding().iloc[0]['rate'], .004)
        self.write('funding', 'c.parquet', [base | dict(rate=.02)])
        self.assertTrue(da.load_funding().empty)

    def test_writer_adds_provenance_and_idempotent_key_count(self):
        frame = pd.DataFrame([dict(symbol='BTC',ts=pd.Timestamp('2026-01-01',tz='UTC'),exchange='binance',rate=.01,interval_h=8)])
        self.assertEqual(common.append_parquet(frame, 'funding'), 1)
        self.assertEqual(common.append_parquet(frame, 'funding'), 0)
        selected = da.load_table('funding')
        self.assertEqual(len(selected), 1)
        self.assertTrue(selected['ingested_at'].notna().all())

    def test_liquidation_granularities_do_not_double_count(self):
        from analytics.liquidations import daily_liquidations
        hourly = [dict(symbol='BTC',ts=stamp,interval='1h',long_usd=1.,short_usd=2.) for stamp in pd.date_range('2026-01-01',periods=20,freq='h',tz='UTC')]
        self.write('liquidations','a.parquet',hourly + [dict(symbol='BTC',ts='2026-01-01',interval='1d',long_usd=99.,short_usd=99.)])
        result = daily_liquidations()
        self.assertEqual(len(result),1)
        self.assertEqual(result.iloc[0]['long_usd'],20)

    def test_one_fresh_coin_does_not_hide_stale_or_missing_coins(self):
        pd.DataFrame({'base':['BTC','ETH','SOL'], 'binance_symbol':['BTC','ETH','SOL'], 'bybit_symbol':[None]*3,'hyperliquid_symbol':[None]*3}).to_parquet(self.root/'universe.parquet')
        self.write('funding','a.parquet',[
            dict(symbol='BTC',ts='2026-01-02T12:00Z',exchange='binance',rate=.01,interval_h=8),
            dict(symbol='ETH',ts='2026-01-01T12:00Z',exchange='binance',rate=.01,interval_h=8),
            dict(symbol='OLD',ts='2026-01-01T12:00Z',exchange='binance',rate=.01,interval_h=8)])
        details = coverage_details(pd.Timestamp('2026-01-02T13:00Z'))
        statuses = details[details['table']=='funding'].set_index('symbol')['status'].to_dict()
        self.assertEqual(statuses, {'BTC':'healthy','ETH':'stale','SOL':'missing','OLD':'inactive'})

    def test_missing_tables_return_typed_empty_frames(self):
        for table in da.SCHEMAS:
            self.assertTrue(da.load_table(table).empty)

    def test_empty_project_has_a_usable_snapshot(self):
        from analytics.snapshot import build_snapshot
        result = build_snapshot()
        self.assertTrue(result['cross_section'].empty)
        self.assertEqual(result['health']['options_chain']['missing'], 2)

    def test_catchup_checks_each_symbol(self):
        from collectors.hourly import sweep_candidates
        now = pd.Timestamp('2026-01-02T12:00Z')
        self.write('funding', 'a.parquet', [
            dict(symbol='BTC', ts=now, exchange='binance', rate=.01, interval_h=8),
            dict(symbol='ETH', ts=now-pd.Timedelta(days=1), exchange='binance', rate=.01, interval_h=8)])
        universe = pd.DataFrame({'base':['BTC','ETH'], 'binance_symbol':['BTC/USDT','ETH/USDT']})
        with patch('collectors.hourly.load_universe', return_value=universe):
            self.assertEqual(sweep_candidates('funding','binance',now), {'ETH'})

    def test_membership_is_recorded_without_backdating_or_duplicate_snapshots(self):
        from collectors import universe as collector
        from analytics.universe import membership
        now=pd.Timestamp('2026-01-02T12:00Z')
        frame=pd.DataFrame({'base':['BTC'], 'binance_symbol':['BTC/USDT'], 'bybit_symbol':[None], 'hyperliquid_symbol':[None]})
        with patch.object(collector,'DATA_DIR',self.root):
            collector.record_universe(frame,now)
            collector.record_universe(frame,now+pd.Timedelta(hours=1))
        self.assertEqual(len(list((self.root/'universe_history').glob('*.parquet'))),1)
        index=pd.DatetimeIndex([now-pd.Timedelta(days=1),now+pd.Timedelta(days=1)])
        mask,recorded=membership(index,['BTC','ETH'])
        self.assertFalse(recorded.iloc[0])
        self.assertTrue(recorded.iloc[1])
        self.assertTrue(mask.iloc[0]['ETH'])  # unknown history, not inferred membership
        self.assertFalse(mask.iloc[1]['ETH'])

    def test_legacy_chain_age_is_explicitly_unknown(self):
        self.write('options_chain','a.parquet',[dict(instrument='BTC-27SEP26-80000-C',ts='2026-01-02',currency='BTC')])
        details=coverage_details(pd.Timestamp('2026-01-02T12:00Z'))
        row=details[(details['table']=='options_chain') & (details['symbol']=='BTC')].iloc[0]
        self.assertEqual(row['status'],'unknown time')

    def test_import_never_reads_environment_file(self):
        with patch.object(Path, 'read_text', side_effect=AssertionError('Unexpected file read')):
            importlib.reload(common)


class SignalContracts(unittest.TestCase):
    def test_rr25_requires_observed_delta_brackets(self):
        from analytics import options_metrics
        frame=pd.DataFrame([{'ts':pd.Timestamp('2026-01-01',tz='UTC'),'currency':'BTC',
            'expiry_ts':pd.Timestamp('2026-02-01',tz='UTC'),'strike':strike,'underlying_price':100.,
            'option_type':side,'mark_iv':50.,'tau_years':.1,'open_interest':1.,'_legacy':False}
            for strike in (10.,11.,12.) for side in ('C','P')])
        with patch.object(options_metrics,'load_chain',return_value=frame):
            self.assertTrue(options_metrics.chain_metrics().empty)

    def test_briefing_saves_clean_facts_and_compares_matching_sources_only(self):
        from briefing import generate
        from types import SimpleNamespace
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = {'generated_utc':'2026-01-01', 'cross_section':[
                {'symbol':'BTC','funding_rate':.01,'oi_usd':100.,'oi_src':'binance'}]}
            (root / 'snapshot-2026-01-01.json').write_text(json.dumps(prior), encoding='utf-8')
            current = {'generated_utc':'2026-01-02','cross_section':[
                {'symbol':'BTC','funding_rate':.02,'oi_usd':200.,'oi_src':'coinalyze_agg'}], 'optional':float('nan')}
            with patch.object(generate,'REPORTS_DIR',root), patch.object(generate,'build_context',return_value=current), patch.object(generate.shutil,'which',return_value='fixture'), patch.object(generate.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='Market observations. '*20)):
                generate.main()
            outputs = sorted(root.glob('snapshot-*.json'))
            written = json.loads(outputs[-1].read_text(encoding='utf-8'))
            self.assertIsNone(written['optional'])
            changes = written['since_previous_report']['changes'][0]
            self.assertAlmostEqual(changes['funding_rate_change'], .01)
            self.assertNotIn('oi_usd_change',changes)

    def test_daily_close_does_not_require_unrelated_intraday_candles(self):
        frame = pd.DataFrame({'symbol':['BTC','BTC'],
            'ts':pd.to_datetime(['2020-01-01','2020-01-02'],utc=True),
            'close':[100.,101.], 'hours':[22,22],
            'observed_at':pd.to_datetime(['2020-01-01T23:00Z','2020-01-02T22:00Z'])})
        result = zscores.daily_panel(frame,'close',fill_days=0)
        self.assertEqual(result.iloc[0]['BTC'],100.)
        self.assertTrue(pd.isna(result.iloc[1]['BTC']))

    def test_briefing_excludes_stale_coins_and_legacy_options(self):
        now=pd.Timestamp('2026-01-02T12:00Z')
        snapshot={'generated_at':now, 'gaps':{},
            'health':{name:{'status':'healthy'} for name in ['funding','open_interest','ohlcv','options_dvol','liquidations']},
            'cross_section':pd.DataFrame({'eligible':[False],'data_status':['stale'],'funding_rate':[999.]},index=pd.Index(['OLD'],name='symbol')),
            'regime':pd.DataFrame(), 'liquidations':pd.DataFrame(),
            'dvol':pd.DataFrame({'currency':['BTC','ETH'],'ts':[now,now-pd.Timedelta(days=2)],'close':[50.,999.]}),
            'term':pd.DataFrame({'currency':['BTC'],'ts':[now],'timestamp_quality':['legacy_day_only'],'atm_iv':[999.]})}
        result=briefing_facts(snapshot)
        self.assertEqual(result['cross_section'],[])
        self.assertEqual(result['term'],[])
        self.assertEqual([row['currency'] for row in result['dvol']],['BTC'])
        self.assertIn('regime',result['gaps'])

    def test_options_store_actual_capture_time(self):
        from collectors.hourly import collect_options
        from unittest.mock import MagicMock
        now=pd.Timestamp.now(tz='UTC')
        dvol=MagicMock()
        dvol.json.return_value={'result':{'data':[]}}
        chain=MagicMock()
        chain.json.return_value={'result':[{'instrument_name':'BTC-27SEP26-80000-C','mark_iv':50.,'open_interest':1.,'underlying_price':80000.,'volume':0.}]}
        captured={}
        def append(frame,table):
            captured[table]=frame
            return len(frame)
        with patch('collectors.hourly.httpx.Client') as client, patch('collectors.hourly.append_parquet',side_effect=append):
            client.return_value.get.side_effect=[dvol,chain,dvol,chain]
            collect_options(now.floor('h'))
        self.assertTrue((captured['options_chain']['ts'] >= now).all())
        self.assertTrue((captured['options_chain']['snapshot_day'] == now.floor('D')).all())

    def test_future_observations_do_not_rewrite_flush_signals(self):
        times = pd.date_range('2026-01-01',periods=100,freq='h',tz='UTC')
        original = pd.DataFrame({'symbol':'BTC','ts':times,'long_usd':[1.,2.]*49+[20.,1.], 'short_usd':[2.,3.]*50})
        def oi(frame):
            return frame[['symbol','ts']].assign(oi_usd=100.,oi_src='fixture')
        with patch.object(flush,'load_hourly_liquidations',return_value=original), patch.object(flush,'continuous_hourly_oi',side_effect=oi):
            before=flush.flush_panel()
        future=pd.concat([original,pd.DataFrame({'symbol':['BTC'],'ts':[times[-1]+pd.Timedelta(hours=1)],'long_usd':[10000.],'short_usd':[10000.]})],ignore_index=True)
        with patch.object(flush,'load_hourly_liquidations',return_value=future), patch.object(flush,'continuous_hourly_oi',side_effect=oi):
            after=flush.flush_panel().iloc[:-1].reset_index(drop=True)
        pd.testing.assert_frame_equal(before,after)
        self.assertTrue(before.iloc[98]['long_flush'])

    def test_stale_flush_is_not_current(self):
        panel=pd.DataFrame({'symbol':['BTC'],'ts':[pd.Timestamp('2026-01-01',tz='UTC')]})
        # Empty fresh frames still need the expected metric schema.
        for name in ['long_usd','short_usd','long_ratio','short_ratio','long_z','short_z','oi_usd']:
            panel[name]=1.
        panel['oi_src']='fixture'
        result=flush.top_flush_now(panel,now=pd.Timestamp('2026-02-01',tz='UTC'))
        self.assertTrue(result['long'].empty)

    def test_exact_24h_return_does_not_jump_missing_hours(self):
        start=pd.Timestamp('2026-01-01',tz='UTC')
        panel=pd.DataFrame({'symbol':['BTC'],'ts':[start],'long_z':[4.],'short_z':[4.]})
        closes=pd.DataFrame({'symbol':'BTC','ts':[start,start+pd.Timedelta(hours=25)],'close':[100.,200.]})
        with patch.object(flush,'load_hourly_closes',return_value=closes):
            self.assertEqual(flush.falsifier(panel)['base']['n'],0)

    def test_calendar_volatility_does_not_compress_a_month_gap(self):
        timestamps=pd.date_range('2026-01-01',periods=500,freq='h',tz='UTC').append(pd.date_range('2026-03-01',periods=5,freq='h',tz='UTC'))
        frame=pd.DataFrame({'ts':timestamps,'close':100.+np.arange(505)%7,'high':110.,'low':90.})
        result=vol.realised_vol(frame)
        self.assertTrue(pd.isna(result.iloc[-1]['rv30_close_to_close']))

    def test_regime_bucket_boundaries_use_prior_history(self):
        original=pd.Series(np.sin(np.arange(500)/20),index=pd.date_range('2020-01-01',periods=500,tz='UTC'))
        future=pd.concat([original,pd.Series([1000.],index=[original.index[-1]+pd.Timedelta(days=1)])])
        pd.testing.assert_series_equal(regime_returns.past_only_buckets(original),regime_returns.past_only_buckets(future).iloc[:-1], check_freq=False)
        self.assertTrue(regime_returns.past_only_buckets(original).iloc[:365].isna().all())

    def test_oi_source_does_not_change_when_future_binance_depth_arrives(self):
        times=pd.date_range('2020-01-01',periods=120,tz='UTC')
        agg=pd.DataFrame({'symbol':'BTC','ts':times,'oi_usd':np.arange(120)+100.})
        binance=agg.iloc[50:].copy()
        with patch.object(zscores,'load_open_interest_binance',return_value=binance),patch.object(zscores,'load_open_interest_coinalyze',return_value=agg):
            before=zscores.oi_zscores()
        extension=pd.DataFrame({'symbol':'BTC','ts':pd.date_range(times[-1]+pd.Timedelta(days=1),periods=120,tz='UTC'),'oi_usd':1000.})
        with patch.object(zscores,'load_open_interest_binance',return_value=pd.concat([binance,extension])),patch.object(zscores,'load_open_interest_coinalyze',return_value=pd.concat([agg,extension])):
            after=zscores.oi_zscores()
        self.assertEqual(before['source'],after['source'])
        pd.testing.assert_frame_equal(before['value'],after['value'].reindex(before['value'].index))

    def test_options_failure_is_not_positive_collection(self):
        self.assertFalse(collection_succeeded({'funding':0,'options':'failed'}))
        self.assertFalse(collection_succeeded({'funding':0,'options':'failed'},healthy=True))
        self.assertTrue(collection_succeeded({'funding':0},healthy=True))


if __name__ == '__main__':
    unittest.main()
