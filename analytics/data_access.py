"""Whole-observation reconciliation and UTC parquet access. No credential reads."""
from __future__ import annotations

import duckdb
import pandas as pd
from contextlib import contextmanager
from contextvars import ContextVar

from collectors.common import DATA_DIR, KIND_RANK, TABLE_KEYS, UNKNOWN_KIND_RANK

SCHEMAS = {
    "ohlcv": "symbol VARCHAR, ts TIMESTAMPTZ, exchange VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE",
    "funding": "symbol VARCHAR, ts TIMESTAMPTZ, exchange VARCHAR, rate DOUBLE, interval_h DOUBLE, kind VARCHAR",
    "open_interest": "symbol VARCHAR, ts TIMESTAMPTZ, exchange VARCHAR, oi_usd DOUBLE",
    "liquidations": "symbol VARCHAR, ts TIMESTAMPTZ, interval VARCHAR, long_usd DOUBLE, short_usd DOUBLE",
    "options_dvol": "currency VARCHAR, ts TIMESTAMPTZ, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE",
    "options_chain": "instrument VARCHAR, ts TIMESTAMPTZ, currency VARCHAR, expiry VARCHAR, strike DOUBLE, option_type VARCHAR, mark_iv DOUBLE, open_interest DOUBLE, underlying_price DOUBLE, volume DOUBLE",
}

_QUERY_CACHE = ContextVar('analytics_query_cache', default=None)


@contextmanager
def query_cache():
    """Reuse reads within one snapshot only; never cache across data updates."""
    marker = _QUERY_CACHE.set({})
    try:
        yield
    finally:
        _QUERY_CACHE.reset(marker)


def query(sql: str) -> pd.DataFrame:
    cache = _QUERY_CACHE.get()
    if cache is not None and sql in cache:
        return cache[sql].copy()
    # Separate connections avoid shared session state between Streamlit workers.
    with duckdb.connect() as connection:
        connection.execute("SET timezone = 'UTC'")
        result = connection.execute(sql).df()
    if cache is not None:
        cache[sql] = result
    return result.copy() if cache is not None else result


def table_path(table: str) -> str:
    if table not in TABLE_KEYS:
        raise ValueError(f"Unknown table: {table}")
    return (DATA_DIR / table / "*.parquet").as_posix().replace("'", "''")


def table_exists(table: str) -> bool:
    return any((DATA_DIR / table).glob("*.parquet"))


def deduped_sql(table: str) -> str:
    """Newest ingestion wins as a whole row; legacy ties use file then row.

    Funding first prefers a settled row over a live sample at the same key
    (collectors.common.KIND_RANK); rows without a kind rank in between.

    Legacy ordering is deterministic, not evidence of accuracy. Duplicate counts
    include identical copies; original files remain available for conflict audit.
    """
    fields = [entry.split() for entry in SCHEMAS[table].split(", ")]
    if not table_exists(table):
        empty = ", ".join(f"NULL::{kind} AS {name}" for name, kind in fields)
        return f"SELECT {empty}, NULL::TIMESTAMPTZ AS ingested_at, NULL::VARCHAR AS _source_file, 0 AS _duplicate_count, TRUE AS _legacy WHERE FALSE"
    raw = f"read_parquet('{table_path(table)}', union_by_name=true, filename=true, file_row_number=true)"
    names = set(query(f"DESCRIBE SELECT * FROM {raw}")["column_name"])
    extra = [f"NULL::{kind} AS {name}" for name, kind in fields if name not in names]
    if "ingested_at" not in names:
        extra.append("NULL::TIMESTAMPTZ AS ingested_at")
    projected = f"SELECT *{', ' + ', '.join(extra) if extra else ''} FROM {raw}"
    keys = ", ".join(TABLE_KEYS[table])
    kind_order = ""
    if table == "funding":
        ranks = " ".join(f"WHEN '{kind}' THEN {rank}" for kind, rank in KIND_RANK.items())
        kind_order = f"CASE kind {ranks} ELSE {UNKNOWN_KIND_RANK} END DESC, "
    return f"""SELECT * EXCLUDE(filename, file_row_number),
        filename AS _source_file, ingested_at IS NULL AS _legacy,
        count(*) OVER (PARTITION BY {keys}) - 1 AS _duplicate_count
        FROM ({projected})
        QUALIFY row_number() OVER (PARTITION BY {keys}
            ORDER BY {kind_order}TRY_CAST(ingested_at AS TIMESTAMPTZ) DESC NULLS LAST,
                     filename DESC, file_row_number DESC) = 1"""


def load_table(table: str) -> pd.DataFrame:
    return query(f"SELECT * FROM ({deduped_sql(table)}) ORDER BY ts")


def load_funding() -> pd.DataFrame:
    return query(f"""SELECT symbol, ts, avg(rate * 8.0 / interval_h) AS rate,
        count(DISTINCT exchange) AS venue_count FROM ({deduped_sql('funding')})
        WHERE interval_h > 0 AND isfinite(rate)
        GROUP BY symbol, ts ORDER BY symbol, ts""")


BINANCE_SETTLEMENT_HOURS = (0, 8, 16)


def binance_funding_filter() -> str:
    """Binance rows at UTC hours every funding schedule (1h/2h/4h/8h) settles at.

    The hour set does not depend on stored `interval_h` labels, which sweeps
    and gap fills assign from the current interval, not the historical one.
    """
    hours = ", ".join(str(hour) for hour in BINANCE_SETTLEMENT_HOURS)
    return (f"exchange = 'binance' AND interval_h > 0 AND isfinite(rate) "
            f"AND extract(hour FROM ts) IN ({hours})")


def load_daily_funding() -> pd.DataFrame:
    """Per (symbol, UTC day): mean per-8h Binance rate over the 00/08/16 samples."""
    return query(f"""SELECT symbol, date_trunc('day', ts) AS ts,
        avg(rate * 8.0 / interval_h) AS rate, max(ts) AS observed_at
        FROM ({deduped_sql('funding')}) WHERE {binance_funding_filter()}
        GROUP BY symbol, date_trunc('day', ts) ORDER BY symbol, ts""")


def load_open_interest(exchange: str) -> pd.DataFrame:
    if exchange not in {"binance", "bybit", "hyperliquid", "coinalyze_agg"}:
        raise ValueError("Unknown OI source")
    return query(f"""SELECT symbol, ts, oi_usd FROM ({deduped_sql('open_interest')})
        WHERE exchange = '{exchange}' AND oi_usd > 0 ORDER BY symbol, ts""")


def load_open_interest_binance() -> pd.DataFrame:
    return load_open_interest("binance")


def load_open_interest_coinalyze() -> pd.DataFrame:
    return load_open_interest("coinalyze_agg")


def load_daily_closes() -> pd.DataFrame:
    return query(f"""SELECT symbol, date_trunc('day', ts) AS ts,
        last(close ORDER BY ts) AS close, sum(volume * close) AS dollar_volume,
        count(DISTINCT ts) AS hours, max(ts) AS observed_at
        FROM ({deduped_sql('ohlcv')}) WHERE exchange = 'binance' AND close > 0
        GROUP BY symbol, date_trunc('day', ts) ORDER BY symbol, ts""")


def load_liquidations() -> pd.DataFrame:
    return load_table("liquidations")


def load_dvol() -> pd.DataFrame:
    return query(f"SELECT currency, ts, close FROM ({deduped_sql('options_dvol')}) ORDER BY currency, ts")
