"""Synthetic tests only: completed-day metrics are fresh inside the latest completed UTC day."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from analytics import data_access as da
from analytics.snapshot import annotate_cross_section
from collectors import common


class CompletedDayFreshness(unittest.TestCase):
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

    def annotate(self, now, inputs, oi_rows=None):
        symbols = list(inputs)
        pd.DataFrame(dict(base=symbols, binance_symbol=symbols, bybit_symbol=[None] * len(symbols),
                          hyperliquid_symbol=[None] * len(symbols))).to_parquet(self.root / 'universe.parquet')
        funding, oi, ohlcv = [], [], []
        for symbol, day in inputs.items():
            funding.append(dict(symbol=symbol, ts=f'{day}T16:00Z', exchange='binance', rate=.0001, interval_h=8))
            oi.append(dict(symbol=symbol, ts=f'{day}T23:00Z', exchange='binance', oi_usd=1e9))
            ohlcv.append(dict(symbol=symbol, ts=f'{day}T23:00Z', exchange='binance',
                              open=100., high=101., low=99., close=100., volume=10.))
        self.write('funding', 'a.parquet', funding)
        self.write('open_interest', 'a.parquet', oi if oi_rows is None else oi_rows)
        self.write('ohlcv', 'a.parquet', ohlcv)
        table = pd.DataFrame({'funding_rate': .0001, 'funding_z90': 1.0, 'oi_usd': 1e9, 'oi_src': 'binance',
                              'oi_z90': 1.0, 'return_30d': .1}, index=pd.Index(symbols, name='symbol'))
        rows = [(name, symbol, source, 'healthy') for symbol in symbols
                for name, source in (('funding', 'binance'), ('ohlcv', 'binance'), ('open_interest', 'binance'))]
        details = pd.DataFrame(rows, columns=['table', 'symbol', 'source', 'status']).assign(expected=True)
        return annotate_cross_section(table, details, pd.Timestamp(now))

    def test_completed_day_inputs_are_eligible_at_2330_utc(self):
        result = self.annotate('2026-01-02T23:30Z', {'BTC': '2026-01-01'})
        self.assertTrue(result.loc['BTC', 'eligible'])
        self.assertEqual(result.loc['BTC', 'data_status'], 'healthy')

    def test_inputs_from_two_days_ago_are_stale(self):
        result = self.annotate('2026-01-02T23:30Z', {'BTC': '2025-12-31'})
        self.assertFalse(result.loc['BTC', 'eligible'])
        self.assertEqual(result.loc['BTC', 'data_status'], 'stale')

    def test_age_column_reports_actual_age(self):
        result = self.annotate('2026-01-02T23:30Z', {'BTC': '2026-01-01'})
        self.assertAlmostEqual(result.loc['BTC', 'funding_age_h'], 31.5)
        self.assertAlmostEqual(result.loc['BTC', 'oi_age_h'], 24.5)

    def test_just_after_midnight_uses_new_completed_day(self):
        result = self.annotate('2026-01-03T00:30Z', {'BTC': '2026-01-02', 'ETH': '2026-01-01'})
        self.assertEqual(result.loc['BTC', 'data_status'], 'healthy')
        self.assertEqual(result.loc['ETH', 'data_status'], 'stale')

    def test_missing_completed_day_input_is_not_eligible(self):
        other_source = [dict(symbol='BTC', ts='2026-01-01T23:00Z', exchange='coinalyze_agg', oi_usd=1e9),
                        dict(symbol='BTC', ts='2026-01-02T23:00Z', exchange='binance', oi_usd=1e9)]
        result = self.annotate('2026-01-02T23:30Z', {'BTC': '2026-01-01'}, oi_rows=other_source)
        self.assertFalse(result.loc['BTC', 'eligible'])
        self.assertEqual(result.loc['BTC', 'data_status'], 'missing')


if __name__ == '__main__':
    unittest.main()
