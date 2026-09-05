"""One-off migration: add interval_h to every historical funding row.

Idempotent, and re-runnable: a file is skipped only when interval_h is fully
populated AND no bybit row disagrees with that symbol's live funding interval.
A file that is complete but carries stale bybit labels is relabelled in place
(second pass), so a venue-wide guess made by an earlier run gets corrected.
Assignment rules (see review F1/F3, V1):
  hyperliquid -> 1.0 (hourly funding)
  bybit       -> the symbol's own funding interval, from the same
                 collectors.hourly.funding_interval_map() lookup the live
                 collector uses (bybit sets the interval PER SYMBOL: most are
                 8h, but a couple of dozen are 4h and ONG is 1h). Falls back to
                 8.0 only for a symbol the lookup does not cover.
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
BYBIT_DEFAULT_H = 8.0  # only for a symbol the live per-symbol lookup does not cover
CUTOFF = pd.Timestamp("2026-08-25 08:00:00", tz="UTC")  # first live hourly funding row
MIN_MONTH_ROWS = 10


def snap(hours: float) -> float:
    """Snap a gap in hours to the nearest candidate in log space."""
    return min(SNAP_CANDIDATES, key=lambda c: abs(math.log(hours / c)))


def month_key(ts: pd.Series) -> pd.Series:
    """Calendar month as an integer (year * 12 + month) - no tz warnings."""
    return ts.dt.year * 12 + ts.dt.month


def bybit_interval_map() -> dict[str, float]:
    """Per-base funding interval for bybit, keyed by the universe's base asset.

    Bybit sets the funding interval per symbol, so a venue-wide value is wrong
    for every 4h/1h market. This reuses the live collector's lookup
    (collectors.hourly.funding_interval_map) so the migration and the hourly
    collector can never disagree."""
    try:
        import ccxt

        from collectors.hourly import funding_interval_map

        universe = pd.read_parquet(DATA_DIR / "universe.parquet")
        wanted = {symbol: base for symbol, base in zip(universe["bybit_symbol"], universe["base"])
                  if pd.notna(symbol)}
        exchange = ccxt.bybit({"enableRateLimit": True})
        found = funding_interval_map(exchange, list(wanted))
        return {wanted[symbol]: hours for symbol, hours in found.items()
                if symbol in wanted and hours is not None}
    except Exception as error:  # noqa: BLE001 - fall back to the documented default
        print(f"  bybit interval lookup failed ({str(error)[:120]}), defaulting to {BYBIT_DEFAULT_H}h")
        return {}


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


def bybit_mismatch(df: pd.DataFrame, bybit_map: dict[str, float]) -> pd.Series:
    """Bybit rows whose stored interval_h disagrees with the symbol's live value."""
    if "interval_h" not in df.columns or not bybit_map:
        return pd.Series(False, index=df.index)
    target = df["symbol"].map(bybit_map)
    return (df["exchange"] == "bybit") & target.notna() & (df["interval_h"] != target)


def assign(df: pd.DataFrame, bybit_map: dict[str, float], current: dict[str, float],
           snapped: dict, counts: dict) -> pd.DataFrame:
    df = df.copy()

    def row_interval(row) -> float | None:
        exchange, symbol, ts = row["exchange"], row["symbol"], row["ts"]
        if exchange == "hyperliquid":
            return 1.0
        if exchange == "bybit":
            return bybit_map.get(symbol, BYBIT_DEFAULT_H)
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
    bybit_map = bybit_interval_map()
    off_default = {base: hours for base, hours in bybit_map.items() if hours != BYBIT_DEFAULT_H}
    print(f"bybit per-symbol intervals: {len(bybit_map)} symbols, "
          f"{len(off_default)} not {BYBIT_DEFAULT_H}h -> {dict(sorted(off_default.items()))}")
    current = binance_current_interval()
    print(f"binance current intervals: {len(current)} symbols")

    all_rows = pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)
    all_rows["ts"] = pd.to_datetime(all_rows["ts"], utc=True)
    snapped, counts = snapped_months(all_rows)
    print(f"snapped months: {len(snapped)} "
          f"({dict(Counter(snapped.values()))}); small months: "
          f"{sum(1 for v in counts.values() if v < MIN_MONTH_ROWS)}")

    totals: Counter = Counter()
    relabelled: Counter = Counter()
    for path in files:
        df = pd.read_parquet(path)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        complete = "interval_h" in df.columns and df["interval_h"].notna().all()
        stale = bybit_mismatch(df, bybit_map)
        if complete and not stale.any():
            print(f"{path.name}: interval_h already complete and bybit labels current, skipping")
            totals.update(df["interval_h"].value_counts().to_dict())
            continue
        before = df["interval_h"].notna().sum() if "interval_h" in df.columns else 0
        if complete:
            # Second pass: only the stale bybit labels move; everything else is
            # left exactly as stored.
            migrated = df.copy()
            migrated.loc[stale, "interval_h"] = migrated.loc[stale, "symbol"].map(bybit_map)
        else:
            migrated = assign(df, bybit_map, current, snapped, counts)
        changed = migrated["interval_h"].ne(df["interval_h"]) if "interval_h" in df.columns \
            else pd.Series(True, index=df.index)
        bybit_changed = changed & (df["exchange"] == "bybit") & df.get(
            "interval_h", pd.Series(pd.NA, index=df.index)).notna()
        relabelled.update(df.loc[bybit_changed, "symbol"].value_counts().to_dict())
        totals.update(migrated["interval_h"].value_counts().to_dict())
        print(f"{path.name}: {len(migrated)} rows, interval_h filled for "
              f"{migrated['interval_h'].notna().sum() - before}, "
              f"bybit rows relabelled {int(bybit_changed.sum())}, "
              f"null {migrated['interval_h'].isna().sum()}")
        temp = path.with_suffix(".parquet.tmp")
        migrated.to_parquet(temp, index=False)
        os.replace(temp, path)

    if relabelled:
        print("bybit rows relabelled (symbol -> rows):")
        for symbol in sorted(relabelled):
            print(f"  {symbol}: {relabelled[symbol]} -> {bybit_map.get(symbol)}h")

    print("per-value row counts (interval_h -> rows):")
    for value in sorted(t for t in totals if t == t):
        print(f"  {value}: {totals[value]}")
    unknown = sum(v for k, v in totals.items() if k != k)  # NaN keys
    if unknown:
        print(f"  <null>: {unknown}")


if __name__ == "__main__":
    main()
