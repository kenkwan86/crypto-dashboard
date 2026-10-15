"""Shared storage helpers for all collectors.

Data lives in data/<table>/<year>.parquet. Every table has a `ts` column
(UTC, pandas datetime64). Appends are idempotent: rows are deduplicated on
the table's key columns before writing.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

def load_environment() -> None:
    """Explicit collector startup only; importing storage/analytics reads no secrets."""
    path = REPO_ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                if value.strip() and not os.environ.get(key.strip()):
                    os.environ[key.strip()] = value.strip()

# Dedupe keys per table.
TABLE_KEYS = {
    "ohlcv": ["symbol", "ts", "exchange"],
    "funding": ["symbol", "ts", "exchange"],
    "open_interest": ["symbol", "ts", "exchange"],
    "liquidations": ["symbol", "ts", "interval"],
    "options_dvol": ["currency", "ts"],
    "options_chain": ["instrument", "ts"],
}


# Funding rows carry a `kind`: "settled" (a venue's settlement history) or
# "live" (the current rate sampled at the run hour). Both can land on the same
# key at a settlement hour; the settled value wins. Legacy rows have no kind.
KIND_RANK = {"live": 0, "settled": 2}
UNKNOWN_KIND_RANK = 1


def dedupe_rows(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Keep one row per key: the highest-ranked kind, then the newest row."""
    if "kind" in frame.columns:
        rank = frame["kind"].map(KIND_RANK).fillna(UNKNOWN_KIND_RANK)
        frame = frame.assign(_kind_rank=rank).sort_values("_kind_rank", kind="stable")
        frame = frame.drop_duplicates(subset=keys, keep="last").drop(columns="_kind_rank")
        return frame.sort_index()
    return frame.drop_duplicates(subset=keys, keep="last")


def append_parquet(df: pd.DataFrame, table: str) -> int:
    """Append rows to data/<table>/<year>-<tag>.parquet with dedupe (within the
    tag file). Returns rows added.

    The tag (DATA_WRITER_TAG, default "local"; the cloud workflow sets "cloud")
    keeps each writer in its own files so the GitHub Actions collector and the
    PC collector never git-conflict on the same parquet. Loaders read
    data/<table>/*.parquet and dedupe across files."""
    if df.empty:
        return 0
    tag = env("DATA_WRITER_TAG", "local")
    keys = TABLE_KEYS[table]
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["ingested_at"] = pd.Timestamp.now(tz="UTC")
    df["writer"] = tag
    added = 0
    for year, chunk in df.groupby(df["ts"].dt.year):
        path = DATA_DIR / table / f"{year}-{tag}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = pd.read_parquet(path)
            existing["ts"] = pd.to_datetime(existing["ts"], utc=True)
            before = len(existing)
            merged = pd.concat([existing, chunk], ignore_index=True)
            merged = dedupe_rows(merged, keys)
            added += len(merged) - before
        else:
            merged = dedupe_rows(chunk, keys)
            added += len(merged)
        merged = merged.sort_values("ts")
        # Write via temp file + replace so readers never see a half-written file.
        # Windows denies the replace while a reader has the file open - retry briefly.
        temp_path = path.with_suffix(".parquet.tmp")
        merged.to_parquet(temp_path, index=False)
        for attempt in range(10):
            try:
                os.replace(temp_path, path)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.5 * (attempt + 1))
    return added


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value if value else default
