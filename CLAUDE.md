# Crypto Dashboard

Personal crypto analytics: hourly perp positioning data (funding, open interest,
liquidations), BTC/ETH options, z-score analytics, a composite regime index, a
Streamlit dashboard, and Claude-generated market briefings. Free data sources only.

## Commands

- `python -m collectors.universe` - rebuild the top-50 perp universe (monthly)
- `python -m collectors.hourly` - hourly collect (add `--daily` to force the options snapshot)
- `python -m collectors.backfill.binance_vision <klines|funding|metrics> [BASE ...]`
- `python -m collectors.backfill.coinalyze` - OI + liquidation history (needs COINALYZE_API_KEY)
- `python -m collectors.backfill.deribit` - DVOL history
- `python -m analytics.zscores` / `python -m analytics.regime` / `python -m analytics.options_metrics`
- `streamlit run dashboard/app.py` - dashboard at localhost:8501
- `python -m briefing.generate` - Claude market briefing (needs ANTHROPIC_API_KEY)

## Data schemas (parquet, `data/<table>/<year>.parquet`, all ts UTC)

| Table | Columns | Notes |
|---|---|---|
| ohlcv | symbol, ts, open, high, low, close, volume, exchange | 1h Binance candles; symbol is the base asset (BTC), volume in base units |
| funding | symbol, ts, rate, exchange | Hourly snapshots (live) + 8h funding events (backfill). Rate per interval, not annualized |
| open_interest | symbol, ts, oi_usd, exchange | exchange in {binance, bybit, hyperliquid, coinalyze_agg}. Sum live exchanges; coinalyze_agg is the daily backfill - never add it to live rows for the same ts |
| liquidations | symbol, ts, long_usd, short_usd | Aggregated across exchanges (Coinalyze) |
| options_dvol | currency, ts, open/high/low/close | Deribit DVOL hourly, BTC+ETH, since 2021-04 |
| options_chain | instrument, ts, currency, expiry, strike, option_type, mark_iv, open_interest, underlying_price, volume | Daily 00 UTC snapshots; mark_iv in % |
| universe.parquet | rank, base, binance_symbol, bybit_symbol, hyperliquid_symbol, quote_volume | Top 50 crypto perps by Binance volume |

## Querying (DuckDB)

```python
import duckdb
duckdb.sql("SELECT symbol, avg(rate)*3*365*100 AS apr FROM 'data/funding/2026.parquet' WHERE ts > now() - INTERVAL 7 DAY GROUP BY symbol ORDER BY apr DESC LIMIT 10").show()
```

Prefer the helpers in `analytics/data_access.py` — `load_open_interest()` already
resolves the live-vs-backfill source overlap correctly.

## Metric definitions

- z-scores: value vs its own trailing window (30/90/365 days), computed in `analytics/zscores.py`.
- OI z is the z-score of the **7-day % change** in OI, not the level.
- Regime score (`analytics/regime.py`): mean of median funding z90, funding-level 1y percentile score, median OI z90, median momentum z90, breadth score, and BTC DVOL 1y percentile score; each clipped to [-3,3]. Positive = hot/crowded, negative = washed out.
- RR25 (`analytics/options_metrics.py`): 25-delta call IV minus 25-delta put IV, deltas computed via Black-Scholes from mark IV (Deribit book summary has no greeks).

## Gotchas

- ccxt hyperliquid spot-market parsing is broken; always construct it with `{"options": {"fetchMarkets": {"types": ["swap"]}}}`.
- Binance/Bybit `fetch_open_interest` returns contracts only; convert to USD with the last price (done in `collectors/hourly.py`).
- Binance lists tokenized stocks/commodities as perps; the universe filter keeps only `underlyingType == "COIN"`.
- Binance REST OI history is capped at 30 days — that's why hourly self-collection matters.
- All parquet appends dedupe on the keys in `collectors/common.py:TABLE_KEYS`; re-running anything is safe.
- The GitHub Actions workflows commit data; local work should `git pull` before running collectors to avoid conflicts.

System docs live in `docs/`, one file per system.
