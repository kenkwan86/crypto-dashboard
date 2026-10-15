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

Funding is normalized with each selected row's `rate * 8 / interval_h` before
averaging venues. Missing/nonpositive intervals are excluded. OI is never summed
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
history, observed inputs within 24h, all expected funding venues at the selected
hour, and healthy relevant feeds. Excluded rows keep a reason. Daily 1d/7d changes
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
