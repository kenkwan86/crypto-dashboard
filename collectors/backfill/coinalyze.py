"""Backfill aggregated open interest and liquidation history from Coinalyze.

Daily granularity, as far back as Coinalyze retains (years for daily data).
Aggregates across all perp markets per base. Requires COINALYZE_API_KEY.

Run: python -m collectors.backfill.coinalyze
"""

from __future__ import annotations

import pandas as pd

from collectors.coinalyze_client import CoinalyzeClient
from collectors.common import DATA_DIR, append_parquet

START = pd.Timestamp("2021-01-01", tz="UTC")


def main() -> None:
    universe = pd.read_parquet(DATA_DIR / "universe.parquet")
    client = CoinalyzeClient()
    symbol_to_base = client.perp_symbols_for_bases(set(universe["base"]))
    print(f"{len(symbol_to_base)} coinalyze perp markets for {universe['base'].nunique()} bases")
    start_s = int(START.timestamp())
    end_s = int(pd.Timestamp.now(tz="UTC").timestamp())
    symbols = list(symbol_to_base)

    liq = client.liquidation_history(symbols, "daily", start_s, end_s)
    rows = []
    for market in liq:
        base = symbol_to_base.get(market["symbol"])
        for point in market.get("history", []):
            rows.append({"symbol": base, "ts": pd.Timestamp(point["t"], unit="s", tz="UTC"),
                         "long_usd": point.get("l", 0.0), "short_usd": point.get("s", 0.0)})
    if rows:
        df = pd.DataFrame(rows).groupby(["symbol", "ts"], as_index=False)[["long_usd", "short_usd"]].sum()
        print(f"liquidations: +{append_parquet(df, 'liquidations')} rows")

    oi = client.open_interest_history(symbols, "daily", start_s, end_s)
    rows = []
    for market in oi:
        base = symbol_to_base.get(market["symbol"])
        for point in market.get("history", []):
            rows.append({"symbol": base, "ts": pd.Timestamp(point["t"], unit="s", tz="UTC"),
                         "oi_usd": point.get("c", 0.0)})
    if rows:
        df = pd.DataFrame(rows).groupby(["symbol", "ts"], as_index=False)[["oi_usd"]].sum()
        df["exchange"] = "coinalyze_agg"
        print(f"open_interest: +{append_parquet(df, 'open_interest')} rows")


if __name__ == "__main__":
    main()
