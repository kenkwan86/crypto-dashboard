"""Coverage against current membership, rather than the newest row in a table."""
from __future__ import annotations

import pandas as pd
from analytics import data_access as da
from analytics.universe import current_universe

LIMITS = {'funding': 3, 'open_interest': 3, 'ohlcv': 3, 'liquidations': 3,
          'options_dvol': 30, 'options_chain': 30}


def coverage_details(now: pd.Timestamp | None = None) -> pd.DataFrame:
    now = pd.Timestamp.now(tz='UTC') if now is None else now
    universe = current_universe()
    expected = []
    for table in LIMITS:
        if table.startswith('options_'):
            expected.extend((table, currency, 'deribit') for currency in ('BTC','ETH'))
            continue
        venues = ('binance','bybit','hyperliquid') if table in ('funding','open_interest') else ('binance',) if table == 'ohlcv' else ('coinalyze_agg',)
        if table == 'open_interest':
            venues += ('coinalyze_agg',)
        for venue in venues:
            bases = universe['base'] if venue == 'coinalyze_agg' else universe.loc[universe[f'{venue}_symbol'].notna(), 'base']
            expected.extend((table, str(base), venue) for base in bases)
    wanted = pd.DataFrame(expected, columns=['table','symbol','source']).assign(expected=True)
    observations = []
    for table in LIMITS:
        symbol = 'currency' if table.startswith('options_') else 'symbol'
        source = "'deribit'" if table.startswith('options_') else "'coinalyze_agg'" if table == 'liquidations' else 'exchange'
        where = "WHERE interval = '1h'" if table == 'liquidations' else ''
        frame = da.query(f"""SELECT {symbol} AS symbol, {source} AS source,
            max(ts) AS observed_at, sum(_duplicate_count) AS duplicate_rows,
            arg_max(_legacy, ts) AS legacy_timestamp
            FROM ({da.deduped_sql(table)}) {where} GROUP BY 1, 2""")
        frame['table'] = table
        observations.append(frame)
    actual = pd.concat(observations, ignore_index=True)
    frame = wanted.merge(actual, on=['table','symbol','source'], how='outer')
    frame['expected'] = frame['expected'].eq(True)
    frame['observed_at'] = pd.to_datetime(frame['observed_at'], utc=True)
    frame['age_h'] = (now - frame['observed_at']).dt.total_seconds() / 3600
    frame['status'] = 'healthy'
    frame.loc[frame['age_h'] > frame['table'].map(LIMITS), 'status'] = 'stale'
    frame.loc[frame['age_h'] < 0, 'status'] = 'future timestamp'
    frame.loc[frame['observed_at'].isna(), 'status'] = 'missing'
    frame.loc[(frame['table'] == 'options_chain') & frame['legacy_timestamp'].eq(True), 'status'] = 'unknown time'
    frame.loc[~frame['expected'], 'status'] = 'inactive'
    return frame.sort_values(['table','source','symbol']).reset_index(drop=True)


def summarize(details: pd.DataFrame) -> dict[str, dict]:
    out = {}
    for table in LIMITS:
        rows = details[(details['table'] == table) & details['expected']]
        healthy = int(rows['status'].eq('healthy').sum())
        newest = rows['observed_at'].max()
        out[table] = {'expected': len(rows), 'healthy': healthy,
                      'stale': int(rows['status'].eq('stale').sum()),
                      'missing': int(rows['status'].eq('missing').sum()),
                      'unknown_time': int(rows['status'].eq('unknown time').sum()),
                      'status': 'healthy' if len(rows) and healthy == len(rows) else 'degraded',
                      'max_ts': None if pd.isna(newest) else str(newest),
                      'age_hours': None if rows['age_h'].dropna().empty else float(rows['age_h'].min()),
                      'duplicate_rows': int(rows['duplicate_rows'].fillna(0).sum())}
    return out


def collection_health(now: pd.Timestamp | None = None) -> dict[str, dict]:
    return summarize(coverage_details(now))
