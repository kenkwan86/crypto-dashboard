# Project contracts

Updated against the implementation and synthetic regression suite on 2026-09-11. The application code remains authoritative for behavior; recheck
constants and coverage when editing the affected subsystem.

## Architecture and storage

Free sources feed collectors, which append parquet; DuckDB loaders feed pandas
analytics; Streamlit and the briefing context consume those analytics. The
universe is the top 50 Binance USDT crypto perpetuals by quote volume, mapped
onto Bybit and Hyperliquid. Historical data can contain more than 50 bases.

Data lives under `data/<table>/*.parquet`, including legacy yearly files and
`<year>-<writer>.parquet` files. The writer tag defaults to `local`; cloud jobs
use a separate tag. `append_parquet()` deduplicates within its file, writes a
temporary file, and replaces with retry on Windows. Readers must additionally
deduplicate across files. All timestamps are UTC; `symbol` is the base asset.

| Table | Dedupe key | Payload and units |
|---|---|---|
| `ohlcv` | symbol, ts, exchange | 1h open/high/low/close, base-unit volume |
| `funding` | symbol, ts, exchange | rate per `interval_h` hours, not annualized |
| `open_interest` | symbol, ts, exchange | `oi_usd`; venues plus `coinalyze_agg` |
| `liquidations` | symbol, ts, interval | long_usd, short_usd; `1h`, `1d`, or excluded `unknown` |
| `options_dvol` | currency, ts | hourly OHLC DVOL for BTC/ETH |
| `options_chain` | instrument, ts | currency, expiry, strike, option_type, mark_iv, open_interest, underlying_price, volume |

`data/universe.parquet` has rank, base, the three exchange symbols and
quote_volume. Option IV is in percent; option open interest is contracts, not
USD. Stored perpetual OI is USD notional.

## Current analytical contracts

All market readers select one complete observation per table key. New
`ingested_at` timestamps take precedence; legacy ties use descending filename
then row number. This provides deterministic selection without claiming that
legacy writer ordering proves accuracy. Preserve `_legacy`, `_source_file` and
`_duplicate_count` when inspecting provenance. Duplicate counts include identical
copies. New writer metadata does not retrospectively repair old observations.

Funding normalizes `rate * 8 / interval_h` per row, excludes invalid intervals,
then averages venues. Basis retains separate venues and uses common timestamps.
OI selection freezes at the first source to reach 90 observed daily values,
Binance on ties. It does not splice series when another source later gains depth.

Daily panels exclude the current day. Funding/OI fill at most three days; price
momentum and research returns do not fill missing closes. A known daily close
requires the 23:00 closed candle, independently of intraday candle count.
OI z-scores use 7-day changes; momentum uses 30-day returns. Zero variance stays
missing. The regime retains six clipped components and `n_components`.

Daily liquidations prefer >=20 hourly observations, otherwise a daily backfill,
never their sum. Unknown intervals are excluded. Flush sources are fixed using
actual overlap in the first 72 liquidation hours. Baselines begin after selection
and require 72 prior observations in a 30-calendar-day window, excluding the event.
The 24h falsifier uses exact timestamp joins. Current events use wall-clock age.

Realized volatility uses a calendar-hour grid with gaps preserved: 720 hours,
480 observations, close-to-close default with Parkinson alongside. Spread ranks
use trailing 365 days, not future observations. RR25 requires observed deltas
bracketing +/-0.25. Actual chain capture time is kept separate from snapshot day;
legacy day-only timestamps remain unknown and are excluded from current briefings.

Regime buckets use prior-history quintile boundaries after 365 valid scores.
Universe membership is applied only from recorded effective times. Before the
first snapshot, membership is unknown; historical availability times are also
missing for legacy backfills. These remain descriptive diagnostics.

`analytics/health.py` measures expected coin/source coverage from current
membership. `analytics/snapshot.py` annotates completed-day metric ages, source
identity, venue coverage and eligibility. Home and briefing share this snapshot.
Inactive, stale, insufficient-history and partially covered coins are excluded
from current rankings; historical plots remain accessible.

## Collection and operation

The documented hybrid deployment uses GitHub Actions for reachable Hyperliquid
and Coinalyze sources and a Windows scheduled job for the full source set.
Binance/Bybit/Deribit access is location-dependent; inspect failures rather than
assuming all venues ran. Keep per-writer files separate. Before an authorized
collection run, reconcile incoming tracked data and local changes; do not pull
over unreviewed local work.

Hyperliquid construction limits market loading to swaps with
`{"options": {"fetchMarkets": {"types": ["swap"]}}}`. Preserve the perpetual
universe's `underlyingType == "COIN"` filter and stablecoin exclusions. OI
collection converts contracts using price where necessary. Catch-up logic uses
a 90-minute age threshold, 48-hour sweep window and shared 600-second budget;
funding history is venue-capability dependent and historical OI sweep is Binance.
Inspect `options_snapshot_stale()` and the hourly main path for actual snapshot
scheduling, rather than relying only on older midnight-only documentation.

| Command from repository root | Effect |
|---|---|
| `python -m collectors.universe` | Fetch and replace the universe; normally monthly |
| `python -m collectors.hourly` | Fetch and append current data plus eligible catch-up |
| `python -m collectors.hourly --daily` | Also force the options snapshot |
| `python -m collectors.backfill.binance_vision <klines\|funding\|metrics> [BASE ...]` | Download historical archives; one instance at a time due to shared manifest |
| `python -m collectors.backfill.coinalyze` | Fetch aggregated OI and liquidation history; configured access required |
| `python -m collectors.backfill.deribit` | Fetch historical DVOL |
| `python -m analytics.zscores` | Compute and print current cross-section |
| `python -m analytics.regime` | Compute and write `data/analytics_cache/regime.parquet` |
| `python -m analytics.options_metrics` | Compute and print options metrics |
| `python -m analytics.crowding` / `python -m analytics.regime_returns` | Compute and print descriptive signal diagnostics |
| `python -m analytics.funding_basis` / `python -m analytics.vol` / `python -m analytics.flush` | Compute and print specialized diagnostics |
| `streamlit run dashboard/app.py` | Start the dashboard |
| `python -m briefing.generate` | Invoke the existing model integration and write a dated report |

These are operational recipes, not permission to execute. Collector entry points explicitly load the protected environment file; analytics
and storage imports do not. Tests use synthetic data and mocked services.

## Dashboard and briefing

Shared caching uses a 900-second TTL. Coverage thresholds are three hours for
hourly data and 30h for options collection. Current briefing observations must
also be no older than 24h; legacy options with unknown capture time are withheld.

The homepage shows market context, 1d/7d changes and usable positioning extremes.
Research contains retrospective return tables; Coin Detail joins price, funding,
OI, liquidations and source coverage. Screener and funding basis default to fresh
usable observations. Native Streamlit/Plotly styles remain consistent.

Briefing generation keeps its existing provider. The facts are gated in Python
before model invocation. Successful reports save a structured snapshot alongside
Markdown for subsequent change comparisons; OI comparisons require matching
sources. No previous snapshot means no invented report-to-report comparison.
