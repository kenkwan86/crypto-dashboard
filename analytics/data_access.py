"""DuckDB access helpers for the parquet tables in data/.

Rows for the same key can exist in several files (legacy backfill files plus
per-writer -local / -cloud files), so every loader dedupes on the table's key
before aggregating.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from collectors.common import DATA_DIR

# duckdb returns timestamptz in the session timezone; keep everything UTC.
duckdb.sql("SET timezone = 'UTC'")


def query(sql: str) -> pd.DataFrame:
    return duckdb.sql(sql).df()


def table_path(table: str) -> str:
    return str(DATA_DIR / table / "*.parquet").replace("\\", "/")


def table_exists(table: str) -> bool:
    return any((DATA_DIR / table).glob("*.parquet"))


def load_funding() -> pd.DataFrame:
    """Funding per (symbol, ts): mean rate across exchanges, normalised to a
    per-8h rate. The stored rate is per interval_h hours (1h hyperliquid
    snapshots, 4h/8h binance settlements), so rate * 8 / interval_h puts every
    row on the same footing before averaging."""
    return query(f"""
        WITH deduped AS (
            SELECT symbol, ts, exchange, max(rate) AS rate, max(interval_h) AS interval_h
            FROM read_parquet('{table_path('funding')}', union_by_name=true)
            GROUP BY symbol, ts, exchange
        )
        SELECT symbol, ts, avg(rate * 8.0 / interval_h) AS rate
        FROM deduped
        WHERE interval_h IS NOT NULL
        GROUP BY symbol, ts ORDER BY symbol, ts
    """)


def load_open_interest_binance() -> pd.DataFrame:
    """Binance-only OI: one continuous series across backfill and live rows.
    Use this for change/z-score computations - the total series mixes
    source sets across time."""
    return query(f"""
        SELECT symbol, ts, max(oi_usd) AS oi_usd
        FROM read_parquet('{table_path('open_interest')}', union_by_name=true)
        WHERE exchange = 'binance'
        GROUP BY symbol, ts ORDER BY symbol, ts
    """)


def load_open_interest_coinalyze() -> pd.DataFrame:
    """Coinalyze aggregated OI only - the fallback continuous series for coins
    without deep Binance OI history."""
    return query(f"""
        SELECT symbol, ts, max(oi_usd) AS oi_usd
        FROM read_parquet('{table_path('open_interest')}', union_by_name=true)
        WHERE exchange = 'coinalyze_agg'
        GROUP BY symbol, ts ORDER BY symbol, ts
    """)


def load_daily_closes() -> pd.DataFrame:
    return query(f"""
        WITH deduped AS (
            SELECT symbol, ts, exchange, max(close) AS close, max(volume) AS volume
            FROM read_parquet('{table_path('ohlcv')}', union_by_name=true)
            GROUP BY symbol, ts, exchange
        )
        SELECT symbol, date_trunc('day', ts) AS ts, last(close ORDER BY ts) AS close,
               sum(volume * close) AS dollar_volume
        FROM deduped
        GROUP BY symbol, date_trunc('day', ts)
        ORDER BY symbol, ts
    """)


def load_liquidations() -> pd.DataFrame:
    if not table_exists("liquidations"):
        return pd.DataFrame(columns=["symbol", "ts", "interval", "long_usd", "short_usd"])
    return query(f"""
        SELECT symbol, ts, interval, max(long_usd) AS long_usd, max(short_usd) AS short_usd
        FROM read_parquet('{table_path('liquidations')}', union_by_name=true)
        GROUP BY symbol, ts, interval ORDER BY symbol, ts
    """)


def load_dvol() -> pd.DataFrame:
    return query(f"""
        SELECT currency, ts, max(close) AS close
        FROM read_parquet('{table_path('options_dvol')}', union_by_name=true)
        GROUP BY currency, ts ORDER BY currency, ts
    """)
