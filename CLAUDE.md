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
- `python -m briefing.generate` - Claude market briefing via headless Claude Code (no API key locally)
- `python -m analytics.vol` - DVOL minus 30d realised vol (close-to-close default, Parkinson alongside) and its full-history percentile, BTC/ETH; shown on the Options page
- `python -m analytics.flush` - hourly liquidations / OI z-scores, flush events (z >= 3) and the 24h-forward falsifier; shown on the Liquidations page

## Data schemas (parquet, `data/<table>/<year>.parquet`, all ts UTC)

| Table | Columns | Notes |
|---|---|---|
| ohlcv | symbol, ts, open, high, low, close, volume, exchange | 1h Binance candles; symbol is the base asset (BTC), volume in base units |
| funding | symbol, ts, rate, exchange, interval_h | Hourly snapshots (live) + funding events (backfill). Rate is per interval_h-hour interval (1h hyperliquid snapshots; 4h/8h binance settlements; bybit sets the interval **per symbol** - mostly 8h, ~23 of the universe are 4h and ONG is 1h), not annualized. `load_funding()` normalises to a per-8h rate (rate * 8 / interval_h) before averaging exchanges |
| open_interest | symbol, ts, oi_usd, exchange | exchange in {binance, bybit, hyperliquid, coinalyze_agg}. Sum live exchanges; coinalyze_agg is the daily backfill - never add it to live rows for the same ts |
| liquidations | symbol, ts, long_usd, short_usd, interval | Aggregated across exchanges (Coinalyze). interval is `1h` (live collector) or `1d` (daily backfill); use `analytics/liquidations.py:daily_liquidations()` for one pair per symbol-day, never a raw sum |
| options_dvol | currency, ts, open/high/low/close | Deribit DVOL hourly, BTC+ETH, since 2021-04 |
| options_chain | instrument, ts, currency, expiry, strike, option_type, mark_iv, open_interest, underlying_price, volume | Daily 00 UTC snapshots; mark_iv in % |
| universe.parquet | rank, base, binance_symbol, bybit_symbol, hyperliquid_symbol, quote_volume | Top 50 crypto perps by Binance volume |

## Querying (DuckDB)

```python
import duckdb
duckdb.sql("SELECT symbol, avg(rate * 8.0 / interval_h)*3*365*100 AS apr FROM read_parquet('data/funding/*.parquet', union_by_name=true) WHERE ts > now() - INTERVAL 7 DAY GROUP BY symbol ORDER BY apr DESC LIMIT 10").show()
```

Prefer the helpers in `analytics/data_access.py`.

## Metric definitions

- z-scores: value vs its own trailing window (30/90/365 days), computed in `analytics/zscores.py`.
- OI z is the z-score of the **7-day % change** in OI, not the level.
- Regime score (`analytics/regime.py`): mean of median funding z90, funding-level 1y percentile score, median OI z90, median momentum z90, breadth score, and BTC DVOL 1y percentile score; each clipped to [-3,3]. Positive = hot/crowded, negative = washed out.
- Crowding quadrant (`analytics/crowding.py`): per-coin label from funding z90 x OI-change z90 (crowded long / short-squeeze fuel / capitulation / apathy) at |funding z| >= 0.75 and |OI z| >= 0.50; Screener page. Falsifier: it does not predict 7d returns - see `docs/signals.md`.
- Regime forward returns (`analytics/regime_returns.py`): median/p25/p75 BTC and universe-average 7d and 30d forward returns per quintile of the composite regime score, with contributing-coin counts; Home page. Flat across buckets, so labelled descriptive only.
- Cross-venue funding basis (`analytics/funding_basis.py`): per-venue funding normalised to 8h (`rate * 8 / interval_h`), then Binance minus Hyperliquid and Binance minus Bybit with a 30d z-score - never averaged across venues; Positioning page.
- RR25 (`analytics/options_metrics.py`): 25-delta call IV minus 25-delta put IV, deltas computed via Black-Scholes from mark IV (Deribit book summary has no greeks).

## Gotchas

- Binance/Bybit/Deribit geo-block US IPs; GitHub-hosted runners are US-based. The cloud workflow only collects Coinalyze aggregates + Hyperliquid; the PC Task Scheduler job ("CryptoDashboardHourly", tools/run_hourly.ps1) collects the full set. Writers append to `<year>-<tag>.parquet` (cloud vs local) to avoid git conflicts; loaders dedupe across files - never read the parquet directly without deduping on the table keys.

- ccxt hyperliquid spot-market parsing is broken; always construct it with `{"options": {"fetchMarkets": {"types": ["swap"]}}}`.
- Binance/Bybit `fetch_open_interest` returns contracts only; convert to USD with the last price (done in `collectors/hourly.py`).
- Binance lists tokenized stocks/commodities as perps; the universe filter keeps only `underlyingType == "COIN"`.
- Binance REST OI history is capped at 30 days — that's why hourly self-collection matters. The hourly collector also runs a 48h catch-up sweep (funding on every venue with `fetchFundingRateHistory`, OI on Binance only) whenever the newest stored row for a table is over 90 minutes old. Bybit and Hyperliquid expose no usable OI history endpoint, so their OI gaps stay unfillable.
- All parquet appends dedupe on the keys in `collectors/common.py:TABLE_KEYS`; re-running anything is safe.
- The GitHub Actions workflows commit data; local work should `git pull` before running collectors to avoid conflicts.

System docs live in `docs/`, one file per system.
