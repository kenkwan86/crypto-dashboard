# Collectors

Pulls market data from free APIs into parquet tables under data/.
Entry points: collectors/hourly.py (runs BOTH in GitHub Actions cron 7 * * * *
AND on the PC via Task Scheduler "CryptoDashboardHourly" at :33),
collectors/universe.py (manual, monthly), collectors/backfill/* (one-time).
Sources: ccxt (Binance/Bybit/Hyperliquid), Coinalyze REST, Deribit REST,
Binance Vision bulk archives. All writes go through
collectors/common.py:append_parquet which dedupes, so every job is idempotent.

## Hybrid cloud/PC split

Binance, Bybit, and Deribit geo-block US IPs, and GitHub-hosted runners are
US-based. So the cloud run only captures Coinalyze aggregates + Hyperliquid;
the PC run (tools/run_hourly.ps1, whenever the PC is on) captures everything.
Each writer appends to its own files - data/<table>/<year>-<DATA_WRITER_TAG>.parquet
("cloud" in the workflow, default "local") - so the two never git-conflict.
Loaders in analytics/data_access.py dedupe across files and prefer
binance-present hours over coinalyze_agg for OI totals.

## Hourly job (collectors/hourly.py)

Per run, per reachable source: last 5 closed 1h Binance candles per coin
(ohlcv), bulk funding-rate snapshot per exchange (funding), per-symbol OI
converted to USD with the last price (open_interest), last-24h aggregated
liquidations AND aggregated OI from Coinalyze (skipped without
COINALYZE_API_KEY; uses '.A' aggregated symbols, retries 429s). In the 00 UTC
hour (or with --daily) it also snapshots the full Deribit BTC/ETH option
chains (options_chain) and the last 3 days of hourly DVOL (options_dvol).
Runtime ~1 min cloud / ~6 min PC. Exits non-zero if every table added 0 rows.

## Backfill (collectors/backfill/)

- binance_vision.py: monthly kline/fundingRate zips since 2021-01; daily
  metrics zips (OI at 5m, resampled to 1h) since 2021-12, default top 10 bases.
  Progress recorded in data/_backfill_manifest.json; 404 = coin not listed yet.
  Only one instance may run at a time (shared manifest).
- coinalyze.py: daily aggregated OI + liquidation history for all bases,
  stored with exchange='coinalyze_agg'.
- deribit.py: hourly DVOL since 2021-04, windowed pagination.

## Universe (collectors/universe.py)

Top 50 Binance USDT perps by 24h quote volume, crypto only
(underlyingType == COIN, stablecoins excluded), mapped to Bybit and
Hyperliquid symbols where listed. Output: data/universe.parquet.
Re-run monthly; collectors read it at startup.
