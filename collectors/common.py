"""Shared storage helpers for all collectors.

Data lives in data/<table>/<year>.parquet. Every table has a `ts` column
(UTC, pandas datetime64). Appends are idempotent: rows are deduplicated on
the table's key columns before writing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

# Dedupe keys per table.
TABLE_KEYS = {
    "ohlcv": ["symbol", "ts", "exchange"],
    "funding": ["symbol", "ts", "exchange"],
    "open_interest": ["symbol", "ts", "exchange"],
    "liquidations": ["symbol", "ts"],
    "options_dvol": ["currency", "ts"],
    "options_chain": ["instrument", "ts"],
}


def append_parquet(df: pd.DataFrame, table: str) -> int:
    """Append rows to data/<table>/<year>.parquet with dedupe. Returns rows added."""
    if df.empty:
        return 0
    keys = TABLE_KEYS[table]
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    added = 0
    for year, chunk in df.groupby(df["ts"].dt.year):
        path = DATA_DIR / table / f"{year}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = pd.read_parquet(path)
            existing["ts"] = pd.to_datetime(existing["ts"], utc=True)
            before = len(existing)
            merged = pd.concat([existing, chunk], ignore_index=True)
            merged = merged.drop_duplicates(subset=keys, keep="last")
            added += len(merged) - before
        else:
            merged = chunk.drop_duplicates(subset=keys, keep="last")
            added += len(merged)
        merged = merged.sort_values("ts")
        # Write via temp file + replace so readers never see a half-written file.
        temp_path = path.with_suffix(".parquet.tmp")
        merged.to_parquet(temp_path, index=False)
        os.replace(temp_path, path)
    return added


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value if value else default
