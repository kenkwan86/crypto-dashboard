"""Synthetic tests only: daily funding is a fixed-hour Binance mean."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from analytics import data_access as da, zscores
from analytics.snapshot import annotate_cross_section
from collectors import common


class DailyFundingContracts(unittest.TestCase):
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

    def value(self, day, symbol='BTC'):
        panel = zscores.funding_zscores()['value']
        return panel.loc[pd.Timestamp(day, tz='UTC'), symbol]

    def settlement(self, day, rates, exchange='binance', interval_h=8, hours=(0, 8, 16), symbol='BTC'):
        return [dict(symbol=symbol, ts=f'{day}T{hour:02d}:00Z', exchange=exchange, rate=rate, interval_h=interval_h)
                for hour, rate in zip(hours, rates)]

    def test_daily_funding_uses_binance_settlement_mean(self):
        rows = self.settlement('2026-01-01', [.0001, .0002, .0003])
        rows.append(dict(symbol='BTC', ts='2026-01-01T23:00Z', exchange='hyperliquid', rate=.0005, interval_h=1))
        self.write('funding', 'a.parquet', rows)
        self.assertAlmostEqual(self.value('2026-01-01'), .0002, places=9)
        daily = da.load_daily_funding()
        self.assertEqual(list(daily.columns), ['symbol', 'ts', 'rate', 'observed_at'])
        self.assertAlmostEqual(daily.iloc[0]['rate'], .0002, places=9)

    def test_live_sample_hour_is_excluded(self):
        rows = self.settlement('2026-01-01', [.0001, .0002, .0003])
        rows.append(dict(symbol='BTC', ts='2026-01-01T13:00Z', exchange='binance', rate=.01, interval_h=8))
        self.write('funding', 'a.parquet', rows)
        self.assertAlmostEqual(self.value('2026-01-01'), .0002, places=9)

    def test_four_hour_coin_uses_00_08_16(self):
        rows = self.settlement('2026-01-01', [.0001, .0002, .0003, .0004, .0005, .0006],
                               interval_h=4, hours=(0, 4, 8, 12, 16, 20))
        self.write('funding', 'a.parquet', rows)
        self.assertAlmostEqual(self.value('2026-01-01'), .0006, places=9)

    def test_interval_change_keeps_same_hours(self):
        rows = self.settlement('2026-01-01', [.0001, .0002, .0003, .0004, .0005, .0006],
                               interval_h=4, hours=(0, 4, 8, 12, 16, 20))
        rows += self.settlement('2026-01-02', [.0001, .0002, .0003])
        self.write('funding', 'a.parquet', rows)
        self.assertAlmostEqual(self.value('2026-01-01'), .0006, places=9)
        self.assertAlmostEqual(self.value('2026-01-02'), .0002, places=9)

    def test_duplicate_writer_uses_newest_ingestion(self):
        older = pd.Timestamp('2026-01-02', tz='UTC')
        newer = pd.Timestamp('2026-01-03', tz='UTC')
        rows = [row | dict(ingested_at=older) for row in self.settlement('2026-01-01', [.0001, .0002, .0003])]
        self.write('funding', 'b.parquet', rows)
        self.write('funding', 'a.parquet', [dict(symbol='BTC', ts='2026-01-01T08:00Z', exchange='binance',
                                                  rate=.0008, interval_h=8, ingested_at=newer)])
        self.assertAlmostEqual(self.value('2026-01-01'), .0004, places=9)

    def annotate(self, universe, funding_rows, details_rows):
        now = pd.Timestamp('2026-01-03T06:00Z')
        pd.DataFrame(universe).to_parquet(self.root / 'universe.parquet')
        self.write('funding', 'a.parquet', funding_rows)
        self.write('open_interest', 'a.parquet', [
            dict(symbol='BTC', ts='2026-01-02T23:00Z', exchange='binance', oi_usd=1e9)])
        self.write('ohlcv', 'a.parquet', [
            dict(symbol='BTC', ts='2026-01-02T23:00Z', exchange='binance', open=100., high=101., low=99., close=100., volume=10.)])
        table = pd.DataFrame({'funding_rate': [.0001], 'funding_z90': [1.0], 'oi_usd': [1e9], 'oi_src': ['binance'],
                              'oi_z90': [1.0], 'return_30d': [.1]}, index=pd.Index(['BTC'], name='symbol'))
        details = pd.DataFrame(details_rows, columns=['table', 'symbol', 'source', 'status']).assign(expected=True)
        return annotate_cross_section(table, details, now)

    def test_stale_binance_with_fresh_hyperliquid_is_not_eligible(self):
        universe = dict(base=['BTC'], binance_symbol=['BTC'], bybit_symbol=[None], hyperliquid_symbol=[None])
        funding = self.settlement('2025-12-30', [.0001, .0002, .0003])
        funding += self.settlement('2026-01-02', [.0001], exchange='hyperliquid', interval_h=1, hours=(23,))
        details = [('funding', 'BTC', 'binance', 'healthy'), ('funding', 'BTC', 'hyperliquid', 'healthy'),
                   ('ohlcv', 'BTC', 'binance', 'healthy'), ('open_interest', 'BTC', 'binance', 'healthy')]
        result = self.annotate(universe, funding, details)
        self.assertFalse(result.loc['BTC', 'eligible'])
        self.assertEqual(result.loc['BTC', 'data_status'], 'stale')

    def test_fresh_binance_with_missing_hyperliquid_is_eligible(self):
        universe = dict(base=['BTC'], binance_symbol=['BTC'], bybit_symbol=[None], hyperliquid_symbol=['BTC'])
        funding = self.settlement('2026-01-02', [.0001, .0002, .0003])
        details = [('funding', 'BTC', 'binance', 'healthy'), ('funding', 'BTC', 'hyperliquid', 'missing'),
                   ('ohlcv', 'BTC', 'binance', 'healthy'), ('open_interest', 'BTC', 'binance', 'healthy')]
        result = self.annotate(universe, funding, details)
        self.assertTrue(result.loc['BTC', 'eligible'])
        self.assertEqual(result.loc['BTC', 'data_status'], 'healthy')


if __name__ == '__main__':
    unittest.main()
