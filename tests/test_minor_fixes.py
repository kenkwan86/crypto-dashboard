"""Synthetic tests for the 2026-10-15 minor fixes: settled funding wins over a
live sample at the same key, one funding-rates call per venue, and
latest_spread reading one whole row. No network or environment-file reads."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from analytics import data_access as da, vol
from collectors import common, hourly

BTC = dict(symbol='BTC', ts=pd.Timestamp('2026-01-01T08:00Z'), exchange='binance', interval_h=8.0)


class FundingKindContracts(unittest.TestCase):
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

    def append(self, **row):
        common.append_parquet(pd.DataFrame([BTC | row]), 'funding')

    def test_settled_row_survives_a_later_live_sample(self):
        self.append(rate=.0001, kind='settled')
        self.append(rate=.0009, kind='live')
        stored = pd.read_parquet(self.root / 'funding' / '2026-local.parquet')
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored.iloc[0]['kind'], 'settled')
        self.assertAlmostEqual(stored.iloc[0]['rate'], .0001)

    def test_settled_row_replaces_an_earlier_live_sample(self):
        self.append(rate=.0009, kind='live')
        self.append(rate=.0001, kind='settled')
        self.assertAlmostEqual(da.load_table('funding').iloc[0]['rate'], .0001)

    def test_live_sample_is_kept_when_no_settled_row_exists(self):
        self.append(rate=.0009, kind='live')
        self.assertAlmostEqual(da.load_table('funding').iloc[0]['rate'], .0009)

    def test_newer_settled_row_replaces_older_settled_row(self):
        self.append(rate=.0001, kind='settled')
        self.append(rate=.0002, kind='settled')
        self.assertAlmostEqual(da.load_table('funding').iloc[0]['rate'], .0002)

    def test_loader_prefers_settled_across_writer_files(self):
        directory = self.root / 'funding'
        directory.mkdir()
        older = pd.Timestamp('2026-01-01T09:00Z')
        newer = pd.Timestamp('2026-01-01T10:00Z')
        pd.DataFrame([BTC | dict(rate=.0001, kind='settled', ingested_at=older)]).to_parquet(directory / '2026-cloud.parquet')
        pd.DataFrame([BTC | dict(rate=.0009, kind='live', ingested_at=newer)]).to_parquet(directory / '2026-local.parquet')
        selected = da.load_table('funding')
        self.assertEqual(len(selected), 1)
        self.assertAlmostEqual(selected.iloc[0]['rate'], .0001)

    def test_legacy_rows_without_kind_still_load(self):
        directory = self.root / 'funding'
        directory.mkdir()
        pd.DataFrame([BTC | dict(rate=.0003)]).to_parquet(directory / '2026.parquet')
        self.assertAlmostEqual(da.load_daily_funding().iloc[0]['rate'], .0003)


class CollectorCalls(unittest.TestCase):
    def test_collect_funding_fetches_rates_once_per_venue(self):
        exchange = MagicMock()
        exchange.id = 'bybit'
        exchange.has = {'fetchFundingIntervals': False}
        exchange.fetch_funding_rates.return_value = {
            'BTC/USDT:USDT': {'fundingRate': .0001, 'interval': '8h'}}
        universe = pd.DataFrame({'base': ['BTC'], 'bybit_symbol': ['BTC/USDT:USDT']})
        captured = {}

        def append(frame, table):
            captured[table] = frame
            return len(frame)

        with patch.object(hourly, 'append_parquet', side_effect=append):
            hourly.collect_funding({'bybit': exchange}, universe, pd.Timestamp('2026-01-01T08:00Z'))
        self.assertEqual(exchange.fetch_funding_rates.call_count, 1)
        row = captured['funding'].iloc[0]
        self.assertEqual(row['kind'], 'live')
        self.assertEqual(row['interval_h'], 8.0)


class LatestSpread(unittest.TestCase):
    def test_latest_spread_takes_one_whole_row(self):
        times = pd.to_datetime(['2026-01-01T00:00Z', '2026-01-01T01:00Z'])
        history = pd.DataFrame({'currency': ['BTC', 'BTC'], 'ts': times, 'dvol': [50., 51.],
                                'rv30_close_to_close': [40., 41.], 'rv30_parkinson': [39., 40.],
                                'spread': [10., 10.], 'spread_pct': [75., np.nan]})
        with patch.object(vol, 'vol_spread', return_value=history):
            latest = vol.latest_spread()
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest.iloc[0]['ts'], times[1])
        self.assertTrue(pd.isna(latest.iloc[0]['spread_pct']))
        self.assertEqual(latest.iloc[0]['reading'], 'not enough history')


if __name__ == '__main__':
    unittest.main()
