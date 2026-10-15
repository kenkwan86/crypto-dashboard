# Collectors

The hybrid collector keeps free Binance, Bybit, Hyperliquid, Coinalyze and Deribit
data in parquet. Cloud and local writers retain separate yearly files. The full
exchange set depends on network reachability; a reachable feed does not establish
coverage for every coin.

Entry points are `python -m collectors.hourly`, `python -m collectors.universe`
and the modules in `collectors/backfill/`. Collector entry points explicitly call
`load_environment()` to support existing local configuration. Importing helpers,
analytics, tests or the dashboard does not read the environment file.

## Writes and collection

`append_parquet()` adds `ingested_at` and `writer` to new observations, deduplicates
within its writer file, and atomically replaces via a temporary file. Readers
reconcile complete rows across writers. These changes do not rewrite historical
files. Do not run two simultaneous jobs using the same writer tag.

OHLCV refreshes the last 48 closed hours per coin, excluding candles by timestamp.
Funding catch-up checks each coin's freshness instead of the exchange-wide maximum.
Binance OI additionally repairs incomplete recent hourly coverage. Sweeps share a
600-second budget; funding pagination checks the deadline between requests.
The available history endpoints still limit what can be recovered.

Options are fetched when either BTC or ETH lacks a snapshot today, or `--daily`
is passed. Chain `ts` is actual capture time; `snapshot_day` is the partition day.
Repeated forced snapshots can add a new observation rather than overwrite a
midnight-labelled record. Daily collection freshness and actual observation age
are separate concepts. Historical midnight labels remain unchanged.

Each hourly run writes non-sensitive counts and per-source coverage to
`data/collection_health/latest-<writer>.json`. Partial coverage is degraded;
zero added rows can be an idempotent result if existing data remains healthy.
A failure string is never counted as a positive number of rows.

## Universe

`collectors.universe` maintains the current top-50 crypto perpetual universe and
records membership changes in immutable `data/universe_history/*.parquet`
snapshots. Hourly startup also records the observed current membership when it
changes. Effective timestamps are never backdated. Analytics applies recorded
membership from when it was known; earlier membership is explicitly unknown.

## Backfills and operation

Binance Vision supplies candles/funding/metrics; Coinalyze provides aggregated
OI/liquidations; Deribit provides DVOL. Only one Vision backfill may run at a time
because it shares a manifest. Historical funding intervals reconstructed by older
migration scripts remain uncertain; this update does not relabel them.

Before an authorized collector run, reconcile incoming tracked data with local
changes. Tests and UI verification do not invoke collectors or load credentials.
