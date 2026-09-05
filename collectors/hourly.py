"""Hourly collector: OHLCV, funding, open interest, liquidations, daily options snapshot.

Run: python -m collectors.hourly
Idempotent — safe to re-run; appends dedupe on each table's keys.
The Deribit options snapshot runs whenever today's is missing (or with --daily).
"""

from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timezone

import ccxt
import httpx
import pandas as pd

from collectors.common import DATA_DIR, append_parquet, env

DERIBIT = "https://www.deribit.com/api/v2"

# Catch-up sweep: when the newest stored row for a (table, exchange) is older
# than SWEEP_MAX_AGE, the next run pages 48h of history so a missed run is
# repaired. Budget: ONE shared deadline for both sweeps (created at the top of
# main) so their combined runtime stays well inside the 15-minute workflow
# timeout (.github/workflows/hourly.yml); each sweep abandons with a printed
# warning when the deadline passes.
SWEEP_MAX_AGE = pd.Timedelta(minutes=90)
SWEEP_WINDOW = pd.Timedelta(hours=48)
SWEEP_BUDGET_S = 600


def newest_stored_ts(table: str, exchange: str) -> pd.Timestamp | None:
    """Newest ts stored for (table, exchange) across all writer files."""
    newest = None
    for path in (DATA_DIR / table).glob("*.parquet"):
        frame = pd.read_parquet(path, columns=["ts", "exchange"])
        hits = frame.loc[frame["exchange"] == exchange, "ts"]
        if not hits.empty:
            value = pd.to_datetime(hits.max(), utc=True)
            newest = value if newest is None or value > newest else newest
    return newest


def funding_interval_map(exchange: ccxt.Exchange, symbols: list[str]) -> dict[str, float | None]:
    """Per-ccxt-symbol funding interval in hours, from whatever ccxt exposes:
    the venue's fetch_funding_intervals lookup (binance) and, as a fallback,
    the interval field on fetch_funding_rates entries (bybit, hyperliquid)."""
    interval_map: dict[str, float | None] = {}
    if exchange.has.get("fetchFundingIntervals"):
        try:
            interval_map = {symbol: _interval_hours(entry.get("interval"))
                            for symbol, entry in exchange.fetch_funding_intervals().items()}
        except Exception as error:
            print(f"  funding intervals {exchange.id}: {error}")
    try:
        for symbol, entry in exchange.fetch_funding_rates(symbols).items():
            hours = _interval_hours(entry.get("interval"))
            if hours is not None:
                interval_map[symbol] = hours
    except Exception as error:
        print(f"  funding rates {exchange.id}: {error}")
    return interval_map


def load_universe() -> pd.DataFrame:
    path = DATA_DIR / "universe.parquet"
    if not path.exists():
        raise SystemExit("data/universe.parquet missing - run: python -m collectors.universe")
    return pd.read_parquet(path)


def collect_ohlcv(binance: ccxt.binanceusdm, universe: pd.DataFrame) -> int:
    rows = []
    for _, coin in universe.iterrows():
        try:
            candles = binance.fetch_ohlcv(coin["binance_symbol"], timeframe="1h", limit=6)
        except Exception as error:
            print(f"  ohlcv {coin['base']}: {error}")
            continue
        # Drop the still-forming last candle.
        for ts, o, h, l, c, v in candles[:-1]:
            rows.append({"symbol": coin["base"], "ts": pd.Timestamp(ts, unit="ms", tz="UTC"),
                         "open": o, "high": h, "low": l, "close": c, "volume": v, "exchange": "binance"})
    return append_parquet(pd.DataFrame(rows), "ohlcv")


def _interval_hours(interval: str | None) -> float | None:
    """ccxt reports the funding interval as a string like '8h'/'4h'/'1h'."""
    if not interval:
        return None
    match = re.match(r"(\d+(?:\.\d+)?)", interval)
    return float(match.group(1)) if match else None


def collect_funding(exchanges: dict[str, ccxt.Exchange], universe: pd.DataFrame, now: pd.Timestamp) -> int:
    rows = []
    for name, exchange in exchanges.items():
        symbol_col = f"{name}_symbol"
        wanted = {s: b for s, b in zip(universe[symbol_col], universe["base"]) if pd.notna(s)}
        # Binance's fetch_funding_rates response (premiumIndex) carries no funding
        # interval; the per-symbol fundingIntervalHours lives on
        # fetch_funding_intervals (one call for the whole venue) instead.
        interval_map = funding_interval_map(exchange, list(wanted))
        try:
            funding = exchange.fetch_funding_rates(list(wanted))
        except Exception as error:
            print(f"  funding {name}: {error}")
            continue
        for symbol, entry in funding.items():
            rate = entry.get("fundingRate")
            if symbol in wanted and rate is not None:
                interval_h = _interval_hours(entry.get("interval"))
                if interval_h is None:
                    interval_h = interval_map.get(symbol)
                rows.append({"symbol": wanted[symbol], "ts": now, "rate": rate,
                             "exchange": name, "interval_h": interval_h})
    return append_parquet(pd.DataFrame(rows), "funding")


def sweep_funding(exchanges: dict[str, ccxt.Exchange], universe: pd.DataFrame, now: pd.Timestamp,
                  deadline: float) -> int:
    """Catch-up sweep: page fetch_funding_rate_history for the last 48h when the
    newest stored funding row for an exchange is more than 90 minutes old.
    Rows land at their settlement timestamps with the same interval_h the
    point sample uses. Only exchanges with fetchFundingRateHistory take part.
    `deadline` is the monotonic clock time shared with the OI sweep; abandon
    with a printed warning rather than overrun the job budget."""
    wall_now = pd.Timestamp.now(tz="UTC")
    since_ms = int((now - SWEEP_WINDOW).timestamp() * 1000)
    total = 0
    for name, exchange in exchanges.items():
        if not exchange.has.get("fetchFundingRateHistory"):
            continue
        newest = newest_stored_ts("funding", name)
        if newest is not None and wall_now - newest <= SWEEP_MAX_AGE:
            continue
        symbol_col = f"{name}_symbol"
        wanted = {s: b for s, b in zip(universe[symbol_col], universe["base"]) if pd.notna(s)}
        if not wanted:
            continue
        interval_map = funding_interval_map(exchange, list(wanted))
        rows = []
        for symbol in wanted:
            if time.monotonic() > deadline:
                print(f"  funding sweep {name}: time budget reached, abandoning "
                      f"after {len(rows)} rows (re-run repairs the rest)")
                break
            cursor = since_ms
            try:
                while True:
                    history = exchange.fetch_funding_rate_history(symbol, since=cursor, limit=1000)
                    if not history:
                        break
                    for entry in history:
                        rows.append({"symbol": wanted[symbol],
                                     "ts": pd.Timestamp(entry["timestamp"], unit="ms", tz="UTC").floor("h"),
                                     "rate": entry["fundingRate"], "exchange": name,
                                     "interval_h": interval_map.get(symbol)})
                    if len(history) < 1000:
                        break
                    cursor = history[-1]["timestamp"] + 1
            except Exception as error:
                print(f"  funding sweep {name} {wanted[symbol]}: {error}")
        if rows:
            added = append_parquet(pd.DataFrame(rows), "funding")
            print(f"  funding sweep {name}: +{added}")
            total += added
    return total


def sweep_open_interest(exchanges: dict[str, ccxt.Exchange], universe: pd.DataFrame, now: pd.Timestamp,
                        deadline: float) -> int:
    """Catch-up sweep for the Binance OI leg (the only exchange with a usable
    1h history endpoint here; Bybit and Hyperliquid gaps stay unfillable).
    Shares the deadline with sweep_funding so both sweeps together stay inside
    the job budget."""
    wall_now = pd.Timestamp.now(tz="UTC")
    if "binance" not in exchanges:
        return 0
    newest = newest_stored_ts("open_interest", "binance")
    if newest is not None and wall_now - newest <= SWEEP_MAX_AGE:
        return 0
    since_ms = int((now - SWEEP_WINDOW).timestamp() * 1000)
    binance = exchanges["binance"]
    rows = []
    for _, coin in universe.iterrows():
        if time.monotonic() > deadline:
            print(f"  oi sweep binance: time budget reached, abandoning after {len(rows)} rows "
                  f"(re-run repairs the rest)")
            break
        try:
            history = binance.fetch_open_interest_history(coin["binance_symbol"], "1h",
                                                          since=since_ms, limit=500)
        except Exception as error:
            print(f"  oi sweep {coin['base']}: {error}")
            continue
        for entry in history:
            value = entry.get("openInterestValue")
            if value is not None and entry.get("timestamp") is not None:
                rows.append({"symbol": coin["base"],
                             "ts": pd.Timestamp(entry["timestamp"], unit="ms", tz="UTC").floor("h"),
                             "oi_usd": float(value), "exchange": "binance"})
    if rows:
        added = append_parquet(pd.DataFrame(rows), "open_interest")
        print(f"  oi sweep binance: +{added}")
        return added
    return 0


def collect_open_interest(exchanges: dict[str, ccxt.Exchange], universe: pd.DataFrame, now: pd.Timestamp) -> int:
    rows = []
    for name, exchange in exchanges.items():
        symbol_col = f"{name}_symbol"
        wanted = [s for s in universe[symbol_col] if pd.notna(s)]
        try:
            tickers = exchange.fetch_tickers(wanted)
        except Exception as error:
            print(f"  oi tickers {name}: {error}")
            tickers = {}
        for _, coin in universe.iterrows():
            symbol = coin[symbol_col]
            if pd.isna(symbol):
                continue
            try:
                oi = exchange.fetch_open_interest(symbol)
            except Exception as error:
                print(f"  oi {name} {coin['base']}: {error}")
                continue
            value = oi.get("openInterestValue")
            amount = oi.get("openInterestAmount")
            if value is None and amount is not None:
                # Binance/Bybit report contracts only; convert with the last price.
                price = (tickers.get(symbol) or {}).get("last")
                if price:
                    value = float(amount) * float(price)
            if value is not None:
                rows.append({"symbol": coin["base"], "ts": now, "oi_usd": float(value), "exchange": name})
    return append_parquet(pd.DataFrame(rows), "open_interest")


def collect_coinalyze(universe: pd.DataFrame, now: pd.Timestamp) -> tuple[int, int]:
    """Aggregated liquidations and OI for the last 24h from Coinalyze.
    OI is stored as exchange='coinalyze_agg' so cloud runs (which cannot reach
    Binance/Bybit) still record a full-market OI series."""
    if not env("COINALYZE_API_KEY"):
        print("  coinalyze: COINALYZE_API_KEY not set, skipping")
        return 0, 0
    from collectors.coinalyze_client import CoinalyzeClient

    client = CoinalyzeClient()
    symbol_to_base = client.perp_symbols_for_bases(set(universe["base"]))
    end_s = int(now.timestamp())
    start_s = end_s - 24 * 3600

    liq_rows = []
    for market in client.liquidation_history(list(symbol_to_base), "1hour", start_s, end_s):
        base = symbol_to_base.get(market["symbol"])
        for point in market.get("history", []):
            liq_rows.append({"symbol": base, "ts": pd.Timestamp(point["t"], unit="s", tz="UTC"),
                             "long_usd": point.get("l", 0.0), "short_usd": point.get("s", 0.0),
                             "interval": "1h"})
    liq_added = 0
    if liq_rows:
        df = pd.DataFrame(liq_rows).groupby(["symbol", "ts", "interval"], as_index=False)[["long_usd", "short_usd"]].sum()
        liq_added = append_parquet(df, "liquidations")

    oi_rows = []
    for market in client.open_interest_history(list(symbol_to_base), "1hour", start_s, end_s):
        base = symbol_to_base.get(market["symbol"])
        for point in market.get("history", []):
            oi_rows.append({"symbol": base, "ts": pd.Timestamp(point["t"], unit="s", tz="UTC"),
                            "oi_usd": point.get("c", 0.0)})
    oi_added = 0
    if oi_rows:
        df = pd.DataFrame(oi_rows).groupby(["symbol", "ts"], as_index=False)[["oi_usd"]].sum()
        df["exchange"] = "coinalyze_agg"
        oi_added = append_parquet(df, "open_interest")
    return liq_added, oi_added


def collect_options(now: pd.Timestamp) -> tuple[int, int]:
    client = httpx.Client(timeout=30)
    dvol_rows, chain_rows = [], []
    for currency in ("BTC", "ETH"):
        end_ms = int(now.timestamp() * 1000)
        start_ms = end_ms - 3 * 24 * 3600 * 1000
        response = client.get(f"{DERIBIT}/public/get_volatility_index_data",
                              params={"currency": currency, "start_timestamp": start_ms,
                                      "end_timestamp": end_ms, "resolution": 3600})
        response.raise_for_status()
        # Drop the still-forming last hourly candle, exactly as collect_ohlcv does.
        for ts, o, h, l, c in response.json()["result"]["data"][:-1]:
            dvol_rows.append({"currency": currency, "ts": pd.Timestamp(ts, unit="ms", tz="UTC"),
                              "open": o, "high": h, "low": l, "close": c})

        response = client.get(f"{DERIBIT}/public/get_book_summary_by_currency",
                              params={"currency": currency, "kind": "option"})
        response.raise_for_status()
        snapshot_ts = now.floor("D")
        for item in response.json()["result"]:
            name = item["instrument_name"]  # e.g. BTC-27SEP26-80000-C
            parts = name.split("-")
            if len(parts) != 4 or item.get("mark_iv") is None:
                continue
            chain_rows.append({
                "instrument": name, "ts": snapshot_ts, "currency": currency,
                "expiry": parts[1], "strike": float(parts[2]), "option_type": parts[3],
                "mark_iv": item.get("mark_iv"), "open_interest": item.get("open_interest"),
                "underlying_price": item.get("underlying_price"), "volume": item.get("volume"),
            })
    return append_parquet(pd.DataFrame(dvol_rows), "options_dvol"), append_parquet(pd.DataFrame(chain_rows), "options_chain")


def options_snapshot_stale() -> bool:
    """True when no options_chain row exists for today yet (UTC)."""
    newest = None
    for path in (DATA_DIR / "options_chain").glob("*.parquet"):
        hits = pd.read_parquet(path, columns=["ts"])["ts"]
        if not hits.empty:
            value = pd.to_datetime(hits.max(), utc=True)
            newest = value if newest is None or value > newest else newest
    return newest is None or newest < pd.Timestamp.now(tz="UTC").floor("D")


def main() -> None:
    start = time.monotonic()
    # One shared sweep deadline for both catch-up sweeps, bounded from process
    # start so funding + OI sweeping together cannot overrun the 15-minute job.
    sweep_deadline = start + SWEEP_BUDGET_S
    now = pd.Timestamp.now(tz="UTC").floor("h")
    universe = load_universe()
    # Binance/Bybit/Deribit geo-block US IPs (GitHub-hosted runners are US-based),
    # so every source is optional: collect what this network can reach.
    candidates = {
        "binance": lambda: ccxt.binanceusdm({"enableRateLimit": True}),
        "bybit": lambda: ccxt.bybit({"enableRateLimit": True}),
        "hyperliquid": lambda: ccxt.hyperliquid({"enableRateLimit": True,
                                                 "options": {"fetchMarkets": {"types": ["swap"]}}}),
    }
    exchanges = {}
    for name, factory in candidates.items():
        try:
            exchange = factory()
            exchange.load_markets()
            exchanges[name] = exchange
        except Exception as error:
            print(f"  exchange {name} unavailable, skipping: {str(error)[:160]}")

    counts = {
        "funding_sweep": sweep_funding(exchanges, universe, now, sweep_deadline),
        "open_interest_sweep": sweep_open_interest(exchanges, universe, now, sweep_deadline),
        "funding": collect_funding(exchanges, universe, now),
        "open_interest": collect_open_interest(exchanges, universe, now),
    }
    try:
        counts["liquidations"], counts["oi_coinalyze"] = collect_coinalyze(universe, now)
    except Exception as error:
        print(f"  coinalyze failed: {str(error)[:160]}")
        counts["liquidations"] = counts["oi_coinalyze"] = 0
    if "binance" in exchanges:
        counts["ohlcv"] = collect_ohlcv(exchanges["binance"], universe)
    else:
        print("  ohlcv: binance unavailable, skipping")
    if "--daily" in sys.argv or options_snapshot_stale():
        try:
            counts["options_dvol"], counts["options_chain"] = collect_options(now)
        except Exception as error:
            print(f"  options: deribit unavailable, skipping: {str(error)[:160]}")
            counts["options"] = "failed"

    elapsed = time.monotonic() - start
    print(f"done in {elapsed:.0f}s at {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    for table, added in counts.items():
        print(f"  {table}: FAILED" if added == "failed" else f"  {table}: +{added} rows")
    if all(added == 0 for added in counts.values()):
        raise SystemExit("no rows added to any table - treat as failure")


if __name__ == "__main__":
    main()
