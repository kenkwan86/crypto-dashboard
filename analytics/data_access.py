"""DuckDB access helpers for the parquet tables in data/."""

from __future__ import annotations

import duckdb
import pandas as pd

from collectors.common import DATA_DIR

# duckdb returns timestamptz in the session timezone; keep everything UTC.
duckdb.sql("SET timezone = 'UTC'")


def query(sql: str) -> pd.DataFrame:
    """Run SQL; table('<name>') can be referenced as read_parquet on data/<name>/*.parquet."""
    return duckdb.sql(sql).df()


def table_path(table: str) -> str:
    return str(DATA_DIR / table / "*.parquet").replace("\\", "/")


def load_funding() -> pd.DataFrame:
    """Funding per (symbol, ts): mean rate across exchanges, normalized to hourly ts."""
    return query(f"""
        SELECT symbol, ts, avg(rate) AS rate
        FROM read_parquet('{table_path('funding')}')
        GROUP BY symbol, ts
        ORDER BY symbol, ts
    """)


def load_open_interest() -> pd.DataFrame:
    """OI per (symbol, ts): sum of live exchanges when present, else aggregated/backfill source."""
    return query(f"""
        WITH raw AS (
            SELECT symbol, ts, exchange, oi_usd,
                   CASE WHEN exchange IN ('binance','bybit','hyperliquid') THEN 1 ELSE 2 END AS tier
            FROM read_parquet('{table_path('open_interest')}')
        ),
        best_tier AS (
            SELECT symbol, ts, min(tier) AS tier FROM raw GROUP BY symbol, ts
        )
        SELECT raw.symbol, raw.ts, sum(raw.oi_usd) AS oi_usd
        FROM raw JOIN best_tier USING (symbol, ts, tier)
        GROUP BY raw.symbol, raw.ts
        ORDER BY raw.symbol, raw.ts
    """)


def load_daily_closes() -> pd.DataFrame:
    return query(f"""
        SELECT symbol, date_trunc('day', ts) AS ts, last(close ORDER BY ts) AS close,
               sum(volume * close) AS dollar_volume
        FROM read_parquet('{table_path('ohlcv')}')
        GROUP BY symbol, date_trunc('day', ts)
        ORDER BY symbol, ts
    """)


def load_liquidations() -> pd.DataFrame:
    return query(f"""
        SELECT symbol, ts, long_usd, short_usd
        FROM read_parquet('{table_path('liquidations')}')
        ORDER BY symbol, ts
    """)


def load_dvol() -> pd.DataFrame:
    return query(f"""
        SELECT currency, ts, close
        FROM read_parquet('{table_path('options_dvol')}')
        ORDER BY currency, ts
    """)
