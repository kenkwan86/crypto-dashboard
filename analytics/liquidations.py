"""Liquidation aggregation across the two stored granularities.

The liquidations table holds Coinalyze 1hour rows (live collector) and 1d rows
(daily backfill). Summing both double-counts the days where they overlap, so
`daily_liquidations` returns exactly one long/short pair per (symbol, day):
the sum of the 1h rows when that day has at least 20 of them, otherwise the 1d
row. Rows labelled "unknown" (see tools/migrate_liquidation_interval.py) are
ignored entirely.
"""

from __future__ import annotations

import pandas as pd

from analytics.data_access import load_liquidations

MIN_HOURLY_ROWS = 20


def daily_liquidations() -> pd.DataFrame:
    """One (symbol, day, long_usd, short_usd) row per symbol per day."""
    frame = load_liquidations()
    columns = ["symbol", "day", "long_usd", "short_usd"]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    frame = frame.copy()
    frame["day"] = pd.to_datetime(frame["ts"], utc=True).dt.floor("D")

    hourly = (frame[frame["interval"] == "1h"]
              .groupby(["symbol", "day"], as_index=False)
              .agg(long_usd=("long_usd", "sum"), short_usd=("short_usd", "sum"),
                   hours=("ts", "nunique")))
    hourly = hourly[hourly["hours"] >= MIN_HOURLY_ROWS][columns]

    daily = (frame[frame["interval"] == "1d"]
             .groupby(["symbol", "day"], as_index=False)[["long_usd", "short_usd"]].sum())

    # Prefer the hourly sum for a day, fall back to the 1d row.
    merged = pd.concat([daily.assign(_pref=0), hourly.assign(_pref=1)], ignore_index=True)
    merged = (merged.sort_values("_pref")
              .drop_duplicates(subset=["symbol", "day"], keep="last")
              .drop(columns="_pref"))
    return merged.sort_values(["symbol", "day"]).reset_index(drop=True)


if __name__ == "__main__":
    print(daily_liquidations().tail(10).to_string())
