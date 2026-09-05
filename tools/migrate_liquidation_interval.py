"""One-off migration: add the `interval` granularity key to stored liquidation rows.

Under the old key (symbol, ts) a daily backfill row and an hourly row at the
same timestamp could not coexist. Labelling rules (see review F4):
  2021-local .. 2025-local      -> "1d"  (only the Coinalyze daily backfill wrote those years)
  any row whose ts hour != 0    -> "1h"  (daily rows only ever land at hour 0)
  2026-cloud.parquet            -> "1h"  (the cloud runner has only ever called the 1hour endpoint)
  2026-local.parquet, hour 0, before 2026-08-24        -> "1d"  (daily backfill only; no hourly writer yet)
  2026-local.parquet, hour 0, on/after 2026-08-24      -> "unknown" (genuinely ambiguous under the
                                   old key - left in place rather than deleted; re-run
                                   `python -m collectors.backfill.coinalyze` to lay down clean
                                   1d rows for those days under the new key)

Run: python tools/migrate_liquidation_interval.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.common import DATA_DIR  # noqa: E402

AMBIGUOUS_FROM = pd.Timestamp("2026-08-24 00:00:00", tz="UTC")


def label(df: pd.DataFrame, filename: str) -> pd.Series:
    ts = pd.to_datetime(df["ts"], utc=True)
    if filename.startswith(("2021", "2022", "2023", "2024", "2025")):
        return pd.Series("1d", index=df.index)
    if filename.startswith("2026-cloud"):
        return pd.Series("1h", index=df.index)
    # 2026-local
    labels = pd.Series("1d", index=df.index, dtype=object)
    labels[ts.dt.hour != 0] = "1h"
    labels[(ts.dt.hour == 0) & (ts >= AMBIGUOUS_FROM)] = "unknown"
    return labels


def main() -> None:
    files = sorted((DATA_DIR / "liquidations").glob("*.parquet"))
    if not files:
        raise SystemExit("no liquidation parquet files found")
    for path in files:
        df = pd.read_parquet(path)
        if "interval" in df.columns and df["interval"].notna().all():
            print(f"{path.name}: interval already complete, skipping")
            continue
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df["interval"] = label(df, path.name)
        print(f"{path.name}: {df['interval'].value_counts(dropna=False).to_dict()}")
        temp = path.with_suffix(".parquet.tmp")
        df.to_parquet(temp, index=False)
        os.replace(temp, path)
    print("done")


if __name__ == "__main__":
    main()
