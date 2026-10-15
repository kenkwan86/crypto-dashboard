"""Build the top-50 perp universe, ranked by Binance USDT-perp 24h quote volume.

Run: python -m collectors.universe
Writes data/universe.parquet with one row per base asset and the ccxt symbol
for each exchange that lists it (NaN when not listed).
"""

from __future__ import annotations

import pandas as pd
import ccxt

from collectors.common import load_environment, DATA_DIR

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


def record_universe(frame: pd.DataFrame, now: pd.Timestamp | None = None) -> None:
    """Record membership from when it is observed, never backdate a new universe."""
    now = pd.Timestamp.now(tz='UTC') if now is None else now
    directory = DATA_DIR / 'universe_history'
    directory.mkdir(parents=True, exist_ok=True)
    # Separate immutable observations; no modification of past membership.
    previous = sorted(directory.glob('*.parquet'))
    if previous:
        old = pd.read_parquet(previous[-1]).drop(columns=['effective_at'])
        fields = ['base','binance_symbol','bybit_symbol','hyperliquid_symbol']
        if old[fields].sort_values('base').reset_index(drop=True).equals(frame[fields].sort_values('base').reset_index(drop=True)):
            return
    path = directory / (now.strftime('%Y%m%dT%H%M%S%fZ') + '.parquet')
    temporary = path.with_suffix('.tmp')
    frame.assign(effective_at=now).to_parquet(temporary, index=False)
    temporary.replace(path)


def main() -> None:
    load_environment()
    df = build_universe()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "universe.parquet"
    temporary = path.with_suffix(".tmp")
    df.to_parquet(temporary, index=False)
    temporary.replace(path)
    record_universe(df)
    listed = df[["bybit_symbol", "hyperliquid_symbol"]].notna().sum()
    print(f"universe: {len(df)} bases -> {path}")
    print(f"  bybit listed: {listed['bybit_symbol']}, hyperliquid listed: {listed['hyperliquid_symbol']}")
    print(df[["rank", "base", "quote_volume"]].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
