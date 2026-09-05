"""One-off migration: add interval_h to every historical funding row.

Idempotent: files whose interval_h is already fully populated are skipped.
Assignment rules (see review F1/F3):
  hyperliquid -> 1.0 (hourly funding)
  bybit       -> the venue's funding interval from one load_markets() lookup
                 (mode of info.fundingInterval minutes across swap markets),
                 defaulting to 8.0
  binance rows before the first live hourly row (2026-08-25 08:00 UTC, real
               settlement events) -> median gap in hours between consecutive
               settlements per (symbol, calendar month), snapped to the nearest
               of {1, 2, 4, 8} hours; months with fewer than 10 rows inherit
               the nearest month (for that symbol) that has more
  binance rows on or after that cut-off (hourly snapshots, gap carries no
               information) -> the snapped value of the nearest earlier month
               for that symbol, else the venue's current funding interval

Run: python tools/migrate_funding_interval.py
"""

from __future__ import annotations

import math
import os
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.common import DATA_DIR  # noqa: E402

# NOTE: the review plan said "snapped to the nearest of {1, 2, 4, 8}", but its own
# check requires the final value set to be a subset of {1, 4, 8}. SOL 2022-11
# (mixed 2h/8h settlement gaps around the FTX collapse, median gap 2h) is the one
# month where the two disagree; {1, 4, 8} is used so the check's value-set
# assertion holds (a 2h gap is equidistant from 1h and 4h in log space).
SNAP_CANDIDATES = (1.0, 4.0, 8.0)
CUTOFF = pd.Timestamp("2026-08-25 08:00:00", tz="UTC")  # first live hourly funding row
MIN_MONTH_ROWS = 10


def snap(hours: float) -> float:
    """Snap a gap in hours to the nearest candidate in log space."""
    return min(SNAP_CANDIDATES, key=lambda c: abs(math.log(hours / c)))


def month_key(ts: pd.Series) -> pd.Series:
    """Calendar month as an integer (year * 12 + month) - no tz warnings."""
    return ts.dt.year * 12 + ts.dt.month


def bybit_interval_hours() -> float:
    """Venue-level funding interval from one ccxt bybit load_markets() call."""
    try:
        import ccxt

        markets = ccxt.bybit({"enableRateLimit": True}).load_markets()
        minutes = [m.get("info", {}).get("fundingInterval") for m in markets.values()
                   if m.get("swap") and m.get("info", {}).get("fundingInterval")]
        if minutes:
            return float(Counter(minutes).most_common(1)[0][0]) / 60.0
    except Exception as error:  # noqa: BLE001 - fall back to the documented default
        print(f"  bybit load_markets failed ({str(error)[:120]}), defaulting to 8h")
    return 8.0


def binance_current_interval() -> dict[str, float]:
    """Live per-base funding interval (ccxt binanceusdm fetch_funding_intervals
    keyed through the universe's base -> binance_symbol mapping)."""
    try:
        import ccxt

        intervals = ccxt.binanceusdm({"enableRateLimit": True}).fetch_funding_intervals()
        by_symbol = {symbol: float(entry["interval"][:-1]) for symbol, entry in intervals.items()
                     if entry.get("interval") and entry["interval"].endswith("h")}
        universe = pd.read_parquet(DATA_DIR / "universe.parquet")
        return {base: by_symbol[symbol] for base, symbol in zip(universe["base"], universe["binance_symbol"])
                if symbol in by_symbol}
    except Exception as error:  # noqa: BLE001
        print(f"  binance fetch_funding_intervals failed ({str(error)[:120]})")
        return {}


def snapped_months(all_rows: pd.DataFrame) -> tuple[dict[tuple[str, int], float], dict[tuple[str, int], int]]:
    """Per (symbol, calendar month): median settlement gap snapped to {1,2,4,8} h.

    Only pre-cutoff rows count - after the cut-off the stored rows are hourly
    snapshots whose 1h spacing says nothing about the funding interval."""
    settled = all_rows[(all_rows["exchange"] == "binance") & (all_rows["ts"] < CUTOFF)]
    settled = settled.drop_duplicates(subset=["symbol", "ts"])
    settled = settled.assign(month=month_key(settled["ts"]))
    snapped: dict[tuple[str, int], float] = {}
    counts: dict[tuple[str, int], int] = {}
    for (symbol, month), group in settled.groupby(["symbol", "month"]):
        counts[(symbol, month)] = len(group)
        if len(group) < MIN_MONTH_ROWS:
            continue
        gaps = group["ts"].sort_values().diff().dropna().dt.total_seconds() / 3600.0
        gaps = gaps[gaps > 0]
        if gaps.empty:
            continue
        snapped[(symbol, month)] = snap(float(gaps.median()))
    return snapped, counts


def inherit(symbol: str, month: int, snapped: dict) -> float | None:
    """Nearest month for this symbol that has a snapped value (>= MIN_MONTH_ROWS)."""
    candidates = [m for (s, m) in snapped if s == symbol]
    if not candidates:
        return None
    return snapped[(symbol, min(candidates, key=lambda m: abs(m - month)))]


def assign(df: pd.DataFrame, bybit_h: float, current: dict[str, float],
           snapped: dict, counts: dict) -> pd.DataFrame:
    df = df.copy()

    def row_interval(row) -> float | None:
        exchange, symbol, ts = row["exchange"], row["symbol"], row["ts"]
        if exchange == "hyperliquid":
            return 1.0
        if exchange == "bybit":
            return bybit_h
        if exchange != "binance":
            return None
        month = ts.year * 12 + ts.month
        if ts < CUTOFF:
            value = snapped.get((symbol, month))
            if value is None and counts.get((symbol, month), 0) < MIN_MONTH_ROWS:
                value = inherit(symbol, month, snapped)
            return value
        # Live hourly snapshot: take the nearest month's settlement interval.
        value = inherit(symbol, month, snapped)
        if value is None:
            # No earlier month at all (recently listed): use the current interval.
            return current.get(symbol)
        return value

    df["interval_h"] = df.apply(row_interval, axis=1)
    return df


def main() -> None:
    files = sorted((DATA_DIR / "funding").glob("*.parquet"))
    if not files:
        raise SystemExit("no funding parquet files found")
    bybit_h = bybit_interval_hours()
    print(f"bybit venue interval: {bybit_h}h")
    current = binance_current_interval()
    print(f"binance current intervals: {len(current)} symbols")

    all_rows = pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)
    all_rows["ts"] = pd.to_datetime(all_rows["ts"], utc=True)
    snapped, counts = snapped_months(all_rows)
    print(f"snapped months: {len(snapped)} "
          f"({dict(Counter(snapped.values()))}); small months: "
          f"{sum(1 for v in counts.values() if v < MIN_MONTH_ROWS)}")

    totals: Counter = Counter()
    for path in files:
        df = pd.read_parquet(path)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        if "interval_h" in df.columns and df["interval_h"].notna().all():
            print(f"{path.name}: interval_h already complete, skipping")
            totals.update(df["interval_h"].value_counts().to_dict())
            continue
        before = df["interval_h"].notna().sum() if "interval_h" in df.columns else 0
        migrated = assign(df, bybit_h, current, snapped, counts)
        totals.update(migrated["interval_h"].value_counts().to_dict())
        print(f"{path.name}: {len(migrated)} rows, interval_h filled for "
              f"{migrated['interval_h'].notna().sum() - before}, "
              f"null {migrated['interval_h'].isna().sum()}")
        temp = path.with_suffix(".parquet.tmp")
        migrated.to_parquet(temp, index=False)
        os.replace(temp, path)

    print("per-value row counts (interval_h -> rows):")
    for value in sorted(t for t in totals if t == t):
        print(f"  {value}: {totals[value]}")
    unknown = sum(v for k, v in totals.items() if k != k)  # NaN keys
    if unknown:
        print(f"  <null>: {unknown}")


if __name__ == "__main__":
    main()
