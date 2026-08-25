"""Backfill Deribit DVOL history (hourly) for BTC and ETH since 2021-04.

Run: python -m collectors.backfill.deribit
"""

from __future__ import annotations

import time

import httpx
import pandas as pd

from collectors.common import append_parquet

DERIBIT = "https://www.deribit.com/api/v2"
START = pd.Timestamp("2021-04-01", tz="UTC")


def backfill_dvol(client: httpx.Client, currency: str) -> int:
    added = 0
    cursor = START
    end = pd.Timestamp.now(tz="UTC")
    while cursor < end:
        window_end = min(cursor + pd.Timedelta(hours=990), end)
        response = client.get(f"{DERIBIT}/public/get_volatility_index_data",
                              params={"currency": currency,
                                      "start_timestamp": int(cursor.timestamp() * 1000),
                                      "end_timestamp": int(window_end.timestamp() * 1000),
                                      "resolution": 3600})
        response.raise_for_status()
        data = response.json()["result"]["data"]
        rows = [{"currency": currency, "ts": pd.Timestamp(ts, unit="ms", tz="UTC"),
                 "open": o, "high": h, "low": l, "close": c} for ts, o, h, l, c in data]
        added += append_parquet(pd.DataFrame(rows), "options_dvol")
        cursor = window_end
        time.sleep(0.3)
    return added


def main() -> None:
    client = httpx.Client(timeout=30)
    for currency in ("BTC", "ETH"):
        added = backfill_dvol(client, currency)
        print(f"dvol {currency}: +{added} rows")


if __name__ == "__main__":
    main()
