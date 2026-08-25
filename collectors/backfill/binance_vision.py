"""Backfill from Binance Vision bulk archives (https://data.binance.vision).

Datasets:
  klines   - 1h OHLCV, monthly zips, from 2021-01 (then ccxt gap-fill to now)
  funding  - funding rate history, monthly zips, from 2021-01
  metrics  - open interest (5m -> hourly), daily zips, from 2021-12; heavy:
             ~1700 files per symbol, so default is the top 10 bases only.

Run: python -m collectors.backfill.binance_vision <klines|funding|metrics> [BASE ...]
Resumable: completed (dataset, symbol, period) pairs are recorded in
data/_backfill_manifest.json and skipped on re-run. 404s (coin not yet listed
in that period) are recorded as done.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from datetime import date, timedelta

import httpx
import pandas as pd

from collectors.common import DATA_DIR, append_parquet

BASE_URL = "https://data.binance.vision/data/futures/um"
START = date(2021, 1, 1)
METRICS_START = date(2021, 12, 1)
METRICS_DEFAULT_TOP = 10
MANIFEST_PATH = DATA_DIR / "_backfill_manifest.json"

KLINE_COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
                 "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def load_manifest() -> set[str]:
    if MANIFEST_PATH.exists():
        return set(json.loads(MANIFEST_PATH.read_text()))
    return set()


def save_manifest(done: set[str]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(sorted(done)))


def months_until_last_complete(start: date) -> list[str]:
    today = date.today()
    last = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    months, cursor = [], start.replace(day=1)
    while cursor <= last:
        months.append(f"{cursor:%Y-%m}")
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    return months


def fetch_zip_csv(client: httpx.Client, url: str, columns: list[str] | None) -> pd.DataFrame | None:
    """Download a zip and return its single CSV. None on 404 (not listed yet)."""
    response = client.get(url)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        with archive.open(archive.namelist()[0]) as file:
            first = file.readline().decode()
            file.seek(0)
            has_header = not first.split(",")[0].strip().isdigit()
            if columns:
                return pd.read_csv(file, names=columns, header=0 if has_header else None)
            return pd.read_csv(file)


def raw_id(binance_symbol: str) -> str:
    return binance_symbol.replace("/USDT:USDT", "") + "USDT"


def backfill_klines(client: httpx.Client, base: str, symbol: str, done: set[str]) -> None:
    for month in months_until_last_complete(START):
        key = f"klines|{base}|{month}"
        if key in done:
            continue
        url = f"{BASE_URL}/monthly/klines/{symbol}/1h/{symbol}-1h-{month}.zip"
        df = fetch_zip_csv(client, url, KLINE_COLUMNS)
        if df is not None:
            out = pd.DataFrame({
                "symbol": base,
                "ts": pd.to_datetime(df["open_time"], unit="ms", utc=True),
                "open": df["open"], "high": df["high"], "low": df["low"],
                "close": df["close"], "volume": df["volume"], "exchange": "binance",
            })
            added = append_parquet(out, "ohlcv")
            print(f"  klines {base} {month}: +{added}")
        done.add(key)
        save_manifest(done)


def gap_fill_klines(base: str, ccxt_symbol: str) -> None:
    """Fill from the start of the current month to now via ccxt."""
    import ccxt

    binance = ccxt.binanceusdm({"enableRateLimit": True})
    since = int(pd.Timestamp.now(tz="UTC").normalize().replace(day=1).timestamp() * 1000)
    rows = []
    while True:
        candles = binance.fetch_ohlcv(ccxt_symbol, timeframe="1h", since=since, limit=1000)
        if not candles:
            break
        for ts, o, h, l, c, v in candles[:-1]:
            rows.append({"symbol": base, "ts": pd.Timestamp(ts, unit="ms", tz="UTC"),
                         "open": o, "high": h, "low": l, "close": c, "volume": v, "exchange": "binance"})
        if len(candles) < 1000:
            break
        since = candles[-1][0] + 1
    if rows:
        added = append_parquet(pd.DataFrame(rows), "ohlcv")
        print(f"  klines {base} gap-fill: +{added}")


def backfill_funding(client: httpx.Client, base: str, symbol: str, done: set[str]) -> None:
    for month in months_until_last_complete(START):
        key = f"funding|{base}|{month}"
        if key in done:
            continue
        url = f"{BASE_URL}/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"
        df = fetch_zip_csv(client, url, None)
        if df is not None:
            out = pd.DataFrame({
                "symbol": base,
                "ts": pd.to_datetime(df["calc_time"], unit="ms", utc=True).dt.floor("h"),
                "rate": df["last_funding_rate"], "exchange": "binance",
            })
            added = append_parquet(out, "funding")
            print(f"  funding {base} {month}: +{added}")
        done.add(key)
        save_manifest(done)


def backfill_metrics(client: httpx.Client, base: str, symbol: str, done: set[str]) -> None:
    day = METRICS_START
    today = date.today()
    while day < today:
        key = f"metrics|{base}|{day:%Y-%m-%d}"
        day_str = f"{day:%Y-%m-%d}"
        day += timedelta(days=1)
        if key in done:
            continue
        url = f"{BASE_URL}/daily/metrics/{symbol}/{symbol}-metrics-{day_str}.zip"
        df = fetch_zip_csv(client, url, None)
        if df is not None and "sum_open_interest_value" in df.columns:
            df["ts"] = pd.to_datetime(df["create_time"], utc=True)
            hourly = df.set_index("ts").resample("1h")["sum_open_interest_value"].last().dropna()
            out = pd.DataFrame({"symbol": base, "ts": hourly.index,
                                "oi_usd": hourly.values, "exchange": "binance"})
            added = append_parquet(out, "open_interest")
            if added:
                print(f"  metrics {base} {day_str}: +{added}")
        done.add(key)
        if day.day == 1:
            save_manifest(done)
    save_manifest(done)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"klines", "funding", "metrics"}:
        raise SystemExit(__doc__)
    dataset = sys.argv[1]
    universe = pd.read_parquet(DATA_DIR / "universe.parquet")
    if len(sys.argv) > 2:
        universe = universe[universe["base"].isin(sys.argv[2:])]
    elif dataset == "metrics":
        universe = universe.head(METRICS_DEFAULT_TOP)

    done = load_manifest()
    client = httpx.Client(timeout=60)
    for _, coin in universe.iterrows():
        symbol = raw_id(coin["binance_symbol"])
        print(f"{dataset} {coin['base']} ({symbol})")
        if dataset == "klines":
            backfill_klines(client, coin["base"], symbol, done)
            gap_fill_klines(coin["base"], coin["binance_symbol"])
        elif dataset == "funding":
            backfill_funding(client, coin["base"], symbol, done)
        else:
            backfill_metrics(client, coin["base"], symbol, done)
    print("backfill complete")


if __name__ == "__main__":
    main()
