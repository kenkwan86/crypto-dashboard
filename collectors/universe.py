"""Build the top-50 perp universe, ranked by Binance USDT-perp 24h quote volume.

Run: python -m collectors.universe
Writes data/universe.parquet with one row per base asset and the ccxt symbol
for each exchange that lists it (NaN when not listed).
"""

from __future__ import annotations

import pandas as pd
import ccxt

from collectors.common import DATA_DIR

UNIVERSE_SIZE = 50
# Bases that are stablecoins or exchange-wrapped duplicates, not tradeable theses.
EXCLUDED_BASES = {"USDC", "FDUSD", "TUSD", "DAI", "USDP", "EURI", "USD1", "BFUSD"}


def build_universe() -> pd.DataFrame:
    binance = ccxt.binanceusdm()
    bybit = ccxt.bybit()
    # spot market parsing is broken in ccxt 4.x for hyperliquid; we only need swaps
    hyperliquid = ccxt.hyperliquid({"options": {"fetchMarkets": {"types": ["swap"]}}})

    binance_markets = binance.load_markets()
    tickers = binance.fetch_tickers()

    rows = []
    for symbol, market in binance_markets.items():
        if not market.get("swap") or market.get("quote") != "USDT" or not market.get("active"):
            continue
        info = market.get("info") or {}
        # Binance also lists tokenized stocks/commodities as perps; keep crypto only.
        if info.get("underlyingType") != "COIN":
            continue
        # Delisting perps go SETTLING/CLOSED and reject fetch_open_interest (-4108).
        if info.get("status") != "TRADING":
            continue
        base = market["base"]
        if base in EXCLUDED_BASES:
            continue
        ticker = tickers.get(symbol)
        if not ticker:
            continue
        rows.append({"base": base, "binance_symbol": symbol, "quote_volume": ticker.get("quoteVolume") or 0})

    df = pd.DataFrame(rows).sort_values("quote_volume", ascending=False)
    df = df.drop_duplicates(subset="base").head(UNIVERSE_SIZE).reset_index(drop=True)

    bybit_markets = bybit.load_markets()
    hl_markets = hyperliquid.load_markets()
    bybit_by_base = {m["base"]: s for s, m in bybit_markets.items() if m.get("swap") and m.get("quote") == "USDT" and m.get("active")}
    hl_by_base = {m["base"]: s for s, m in hl_markets.items() if m.get("swap") and m.get("active")}

    df["bybit_symbol"] = df["base"].map(bybit_by_base)
    df["hyperliquid_symbol"] = df["base"].map(hl_by_base)
    df["rank"] = df.index + 1
    return df


def main() -> None:
    df = build_universe()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "universe.parquet"
    df.to_parquet(path, index=False)
    listed = df[["bybit_symbol", "hyperliquid_symbol"]].notna().sum()
    print(f"universe: {len(df)} bases -> {path}")
    print(f"  bybit listed: {listed['bybit_symbol']}, hyperliquid listed: {listed['hyperliquid_symbol']}")
    print(df[["rank", "base", "quote_volume"]].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
