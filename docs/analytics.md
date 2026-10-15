# Analytics

Data flows from whole-observation parquet loaders in `analytics/data_access.py`
through daily panels and specialized metrics into `analytics/snapshot.py`.
Importing analytics no longer loads the local environment file.

## Observation reconciliation

Readers select one complete row per `collectors.common.TABLE_KEYS` key. A newer
`ingested_at` wins; records without that metadata rank last. Remaining ties use
descending filename and file row number. This legacy rule is deterministic, not
proof that one source is correct. `_legacy`, `_source_file` and `_duplicate_count`
carry provenance. Duplicate counts include identical copies. Existing parquet
files are not migrated or rewritten by readers.

Daily funding (`load_daily_funding()`, used by `funding_zscores()`) is one venue
and one fixed set of sampling hours for all history: Binance rows at UTC hours
00, 08 and 16 only, each normalized with `rate * 8 / interval_h`, averaged per
`(symbol, UTC day)`; `observed_at` is the latest included row. Every Binance
funding schedule (1h, 2h, 4h, 8h) settles at those hours, so the filter does not
depend on historical `interval_h` labels. Other venues and Binance live samples
at other hours do not change the value. Before 2026-08-25 only Binance has
history, so this keeps the series on one definition across that date. Known
residuals: a live sample written at 00/08/16 UTC can replace the settled value
for the same key (they share `symbol, ts, exchange`), and the per-8h scaling
uses the stored `interval_h`, so a wrong historical label scales that row wrongly.
`load_funding()` (all venues averaged per timestamp) remains for other callers;
cross-venue work stays in `analytics/funding_basis.py`.
Missing/nonpositive intervals are excluded. OI is never summed
with the Coinalyze aggregate. Each coin's analytical OI source is fixed at the
first source to reach 90 observed daily values, preferring Binance on a tie;
values before selection remain unavailable. This avoids selecting past sources
using future depth. Historical corrections can still change selection.

## Daily panels and history

Panels exclude the current UTC day. Funding and OI fill at most three days;
price momentum and research returns do not fill missing closing prices. A daily
closing price needs the closed 23:00 candle; the `hours` field separately tracks
intraday coverage, so a missing earlier candle does not discard a known close.
Momentum uses 30-day returns; OI uses 7-day percentage changes. z30/z90/z365
require half their respective daily window and do not divide by zero variance.

The regime remains the mean of six available, clipped components: funding z90,
funding-level percentile, OI-change z90, momentum z90, breadth and BTC DVOL rank.
`n_components` is retained. `universe_recorded` flags days supported by an actual
membership snapshot. Membership before the first snapshot remains unknown;
legacy backfills have no historical availability timestamp. Neither issue is
represented as solved by the new signal calculations.

## Shared snapshot and health

`analytics/health.py` compares each expected coin/source pair with its latest
observation, distinguishing healthy, stale, missing, future timestamp and inactive.
Expectations come from the current universe, with BTC/ETH for options. Thresholds
are 3h for hourly tables and 30h for daily options collection.

`analytics/snapshot.py` joins actual completed-day input timestamps and source
coverage onto each coin. Current rankings require active membership, required
history, completed-day inputs, and healthy relevant feeds. A completed-day input
(funding, OI, price) is fresh when its observation falls inside the latest
completed UTC day (`observed_at >= now.floor('D') - 1 day`, not in the future);
otherwise the row is `stale`. It is no longer a fixed 24h age, which marked
every coin stale from 23:00 to 24:00 UTC. The `*_age_h` columns still show the
actual age. Funding provenance (`funding_observed_at`) is the latest included
Binance settlement row before the cutoff, and the funding feed check uses only
Binance `details` rows; the `partial venues` rule and the `funding_venues` /
`expected_funding_venues` columns were removed. Intraday inputs (DVOL, options
term structure) keep the 24h rule in `briefing_facts`. Excluded rows keep a reason. Daily 1d/7d changes
use exact calendar dates. A per-build query cache avoids repeated reads without
persisting results across data updates; Streamlit caches the snapshot for 900s.

Briefing facts are gated before model invocation. Historical charts remain
accessible even when the current assessment is unavailable. Legacy options with
unknown capture time are excluded from the current briefing.

## Options

New chain snapshots retain actual capture timestamps, with `snapshot_day` separate.
Deltas use Black-Scholes mark IV. RR25 interpolates call/put IV only when observed
deltas bracket +/-0.25; no silent endpoint extrapolation. Expiries under two days
are excluded. IV is percent; option OI is contracts. Legacy day-labelled snapshot
capture times cannot be reconstructed and remain explicitly marked.

## Validation

Run `python -m unittest discover -s tests -v`. Tests use synthetic parquet and
mocked services, never production writes or local secret files. CI runs the same
suite. Real data can be inspected through analytics without credentials.
