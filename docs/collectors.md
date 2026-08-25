# Collectors

Pulls market data from free APIs into parquet tables under data/.
Entry points: collectors/hourly.py (GitHub Actions, cron 7 * * * *),
collectors/universe.py (manual, monthly), collectors/backfill/* (one-time).
Sources: ccxt (Binance/Bybit/Hyperliquid), Coinalyze REST, Deribit REST,
Binance Vision bulk archives. All writes go through
collectors/common.py:append_parquet which dedupes, so every job is idempotent.

## Hourly job (collectors/hourly.py)

Per run: last 5 closed 1h Binance candles per coin (ohlcv), bulk funding-rate
snapshot per exchange (funding), per-symbol OI converted to USD with the last
price (open_interest), last-24h hourly liquidations from Coinalyze
(liquidations, skipped without COINALYZE_API_KEY). In the 00 UTC hour (or with
--daily) it also snapshots the full Deribit BTC/ETH option chains
(options_chain) and the last 3 days of hourly DVOL (options_dvol).
Runtime ~1 minute. Exits non-zero if every table added 0 rows.

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
