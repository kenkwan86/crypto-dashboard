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
    """Funding per (symbol, ts): mean rate across exchanges."""
    return query(f"""
        WITH deduped AS (
            SELECT symbol, ts, exchange, max(rate) AS rate
            FROM read_parquet('{table_path('funding')}')
            GROUP BY symbol, ts, exchange
        )
        SELECT symbol, ts, avg(rate) AS rate
        FROM deduped GROUP BY symbol, ts ORDER BY symbol, ts
    """)


def load_open_interest() -> pd.DataFrame:
    """OI per (symbol, ts). Preference order per timestamp:
    1. sum of live exchanges when binance is among them (full picture),
    2. coinalyze aggregated (cloud hours while the PC is off),
    3. sum of whatever live rows exist (e.g. hyperliquid only)."""
    return query(f"""
        WITH deduped AS (
            SELECT symbol, ts, exchange, max(oi_usd) AS oi_usd
            FROM read_parquet('{table_path('open_interest')}')
            GROUP BY symbol, ts, exchange
        ),
        scored AS (
            SELECT symbol, ts,
                   CASE WHEN bool_or(exchange = 'binance') THEN 1
                        WHEN bool_or(exchange = 'coinalyze_agg') THEN 2
                        ELSE 3 END AS tier
            FROM deduped GROUP BY symbol, ts
        )
        SELECT d.symbol, d.ts, sum(d.oi_usd) AS oi_usd
        FROM deduped d JOIN scored s USING (symbol, ts)
        WHERE (s.tier = 1 AND d.exchange IN ('binance','bybit','hyperliquid'))
           OR (s.tier = 2 AND d.exchange = 'coinalyze_agg')
           OR (s.tier = 3 AND d.exchange NOT IN ('coinalyze_agg'))
        GROUP BY d.symbol, d.ts
        ORDER BY d.symbol, d.ts
    """)


def load_open_interest_binance() -> pd.DataFrame:
    """Binance-only OI: one continuous series across backfill and live rows.
    Use this for change/z-score computations - the total series mixes
    source sets across time."""
    return query(f"""
        SELECT symbol, ts, max(oi_usd) AS oi_usd
        FROM read_parquet('{table_path('open_interest')}')
        WHERE exchange = 'binance'
        GROUP BY symbol, ts ORDER BY symbol, ts
    """)


def load_open_interest_coinalyze() -> pd.DataFrame:
    """Coinalyze aggregated OI only - the fallback continuous series for coins
    without deep Binance OI history."""
    return query(f"""
        SELECT symbol, ts, max(oi_usd) AS oi_usd
        FROM read_parquet('{table_path('open_interest')}')
        WHERE exchange = 'coinalyze_agg'
        GROUP BY symbol, ts ORDER BY symbol, ts
    """)


def load_daily_closes() -> pd.DataFrame:
    return query(f"""
        WITH deduped AS (
            SELECT symbol, ts, exchange, max(close) AS close, max(volume) AS volume
            FROM read_parquet('{table_path('ohlcv')}')
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
        return pd.DataFrame(columns=["symbol", "ts", "long_usd", "short_usd"])
    return query(f"""
        SELECT symbol, ts, max(long_usd) AS long_usd, max(short_usd) AS short_usd
        FROM read_parquet('{table_path('liquidations')}')
        GROUP BY symbol, ts ORDER BY symbol, ts
    """)


def load_dvol() -> pd.DataFrame:
    return query(f"""
        SELECT currency, ts, max(close) AS close
        FROM read_parquet('{table_path('options_dvol')}')
        GROUP BY currency, ts ORDER BY currency, ts
    """)
