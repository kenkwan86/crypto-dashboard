import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from analytics import data_access as da
from analytics.health import coverage_details
from analytics.liquidations import daily_liquidations
from collectors import common, hourly

NOW = pd.Timestamp('2026-10-15T12:00:00Z')


def point(ts, long_usd=1.0, short_usd=2.0):
    return {'t': int(pd.Timestamp(ts).timestamp()), 'l': long_usd, 's': short_usd}


class StubClient:
    markets = []
    mapping = {}

    def perp_symbols_for_bases(self, bases):
        return dict(self.mapping)

    def liquidation_history(self, symbols, interval, start_s, end_s):
        return list(self.markets)

    def open_interest_history(self, symbols, interval, start_s, end_s):
        return []


class LiquidationFill(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.patches = [patch.object(da, 'DATA_DIR', self.root), patch.object(common, 'DATA_DIR', self.root),
                        patch.dict(os.environ, {'COINALYZE_API_KEY': 'dummy-key'}),
                        patch('collectors.coinalyze_client.CoinalyzeClient', StubClient)]
        for replacement in self.patches:
            replacement.start()
        StubClient.mapping = {'BTCUSD_PERP.A': 'BTC'}
        StubClient.markets = []

    def tearDown(self):
        for replacement in self.patches:
            replacement.stop()
        self.temp.cleanup()

    def collect(self, now=NOW, capture=True):
        captured = []

        def fake_append(frame, table):
            if table == 'liquidations':
                captured.append(frame.copy())
            return len(frame)

        universe = pd.DataFrame({'base': ['BTC', 'ETH']})
        with contextlib.redirect_stdout(io.StringIO()):
            if capture:
                with patch.object(hourly, 'append_parquet', fake_append):
                    hourly.collect_coinalyze(universe, now)
            else:
                hourly.collect_coinalyze(universe, now)
        return captured[0] if captured else pd.DataFrame(columns=['symbol', 'ts', 'long_usd', 'short_usd', 'interval'])

    def test_missing_hours_are_stored_as_zero(self):
        StubClient.markets = [{'symbol': 'BTCUSD_PERP.A',
                               'history': [point('2026-10-15T03:00Z', 5.0, 6.0), point('2026-10-15T09:00Z', 7.0, 8.0)]}]
        frame = self.collect()
        btc = frame[frame['symbol'] == 'BTC']
        self.assertEqual(len(btc), 24)
        zero = btc[(btc['long_usd'] == 0.0) & (btc['short_usd'] == 0.0)]
        self.assertEqual(len(zero), 22)
        self.assertTrue((btc['interval'] == '1h').all())

    def test_current_hour_point_is_dropped(self):
        StubClient.markets = [{'symbol': 'BTCUSD_PERP.A',
                               'history': [point('2026-10-15T11:00Z', 3.0, 4.0), point(NOW, 9.0, 9.0)]}]
        frame = self.collect()
        self.assertFalse((pd.to_datetime(frame['ts'], utc=True) >= NOW).any())
        self.assertEqual(len(frame), 24)

    def test_empty_history_is_all_zero(self):
        StubClient.markets = [{'symbol': 'BTCUSD_PERP.A', 'history': []}]
        frame = self.collect()
        self.assertEqual(len(frame), 24)
        self.assertTrue((frame['long_usd'] == 0.0).all() and (frame['short_usd'] == 0.0).all())

    def test_absent_market_is_not_filled(self):
        StubClient.mapping = {'BTCUSD_PERP.A': 'BTC', 'ETHUSD_PERP.A': 'ETH'}
        StubClient.markets = [{'symbol': 'BTCUSD_PERP.A', 'history': []}]
        frame = self.collect()
        self.assertEqual(set(frame['symbol']), {'BTC'})
        self.assertEqual(len(frame), 24)

    def test_malformed_history_is_not_filled(self):
        StubClient.mapping = {'BTCUSD_PERP.A': 'BTC', 'ETHUSD_PERP.A': 'ETH'}
        StubClient.markets = [{'symbol': 'BTCUSD_PERP.A', 'history': []},
                              {'symbol': 'ETHUSD_PERP.A', 'history': None}]
        frame = self.collect()
        self.assertEqual(set(frame['symbol']), {'BTC'})
        self.assertEqual(len(frame), 24)

    def test_two_markets_one_base_sum(self):
        StubClient.mapping = {'BTCUSD_PERP.A': 'BTC', 'BTCUSDT_PERP.A': 'BTC'}
        StubClient.markets = [{'symbol': 'BTCUSD_PERP.A', 'history': [point('2026-10-15T05:00Z', 5.0, 6.0)]},
                              {'symbol': 'BTCUSDT_PERP.A', 'history': []}]
        frame = self.collect()
        self.assertEqual(len(frame), 24)
        row = frame[pd.to_datetime(frame['ts'], utc=True) == pd.Timestamp('2026-10-15T05:00Z')].iloc[0]
        self.assertEqual((row['long_usd'], row['short_usd']), (5.0, 6.0))

    def test_quiet_coin_is_healthy_after_fill(self):
        pd.DataFrame({'base': ['BTC'], 'binance_symbol': ['BTC'], 'bybit_symbol': [None],
                      'hyperliquid_symbol': [None]}).to_parquet(self.root / 'universe.parquet')
        StubClient.markets = [{'symbol': 'BTCUSD_PERP.A', 'history': []}]
        self.collect(capture=False)
        details = coverage_details(NOW + pd.Timedelta(hours=1))
        row = details[(details['table'] == 'liquidations') & (details['symbol'] == 'BTC')].iloc[0]
        self.assertEqual(row['status'], 'healthy')

    def test_quiet_day_survives_daily_totals(self):
        day_end = pd.Timestamp('2026-10-16T00:00:00Z')
        StubClient.markets = [{'symbol': 'BTCUSD_PERP.A',
                               'history': [point('2026-10-15T03:00Z', 100.0, 50.0), point('2026-10-15T09:00Z', 20.0, 5.0)]}]
        self.collect(now=day_end, capture=False)
        result = daily_liquidations()
        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        self.assertEqual(pd.Timestamp(row['day']), pd.Timestamp('2026-10-15T00:00:00Z'))
        self.assertEqual((row['long_usd'], row['short_usd']), (120.0, 55.0))


if __name__ == '__main__':
    unittest.main()
