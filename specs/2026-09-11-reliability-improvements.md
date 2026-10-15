# Reliability and decision workflow improvements

Implemented on 2026-09-11 following the project assessment.

## Delivered

- Complete-observation reconciliation across writer files, using ingestion
  timestamps with deterministic legacy tie-breaking. New writes carry provenance.
- Explicit collector environment loading; storage and analytics imports no
  longer read the local environment file.
- Per-symbol catch-up decisions, 48-hour closed-candle refresh, actual options
  capture timestamps, membership snapshots and non-sensitive collection health.
- Prior-only flush baselines, exact 24h forward-return joins, calendar-hour
  volatility windows, prior-history regime bucket boundaries and causal OI
  source selection. Missing prices are not filled for return evaluation.
- Expected coin/source coverage with healthy, stale, missing, inactive and
  unknown-time states. Daily closing-price availability is separate from
  intraday candle coverage.
- Shared validated snapshot for Home and briefing, including daily/weekly
  changes, actual input ages and exclusion reasons. Legacy options with unknown
  capture times are withheld from current briefings.
- Home now emphasizes coverage, market context, changes and usable positioning
  extremes. Research and Coin Detail were added. Existing specialized pages
  remain available, with options to inspect excluded screener/basis observations.
- Successful briefings persist structured facts for subsequent report comparisons;
  OI changes are compared only when source labels match.
- Synthetic regression suite and GitHub Actions workflow.

## Evidence

`python -m unittest discover -s tests -v` passes 23 tests covering whole-row
selection, writer idempotence, schema evolution, missing data, source continuity,
future-row invariance, time gaps, per-symbol catch-up, actual options timestamps,
delta brackets, membership effective times and the mocked briefing save pipeline.

Both Streamlit AppTest passes rendered all eight pages without exceptions.
The browser verification exercised Home, Research and Coin Detail. The final
runtime pass also passed screener exclusions and switching coin selection to ETH.

Stored market data was read directly for verification. The checked snapshot had
38 usable coins, 12 with insufficient analytical history and 12 inactive historical
coins. These are observations during verification, not permanent expected counts.

The portable project skill passes agent-plugins-sync lint with zero specification
errors. The plugin-manifest notice is inapplicable to this project skill directory.

## Limits and rollout

Existing parquet files were not migrated. Legacy conflicts have a deterministic
selection rule, not retroactively established truth. Historical funding-interval
reconstruction uncertainty remains. Prior source revisions can change calculations;
future observations alone must not rewrite already defined signals.

Universe membership before the first recorded observation and legacy ingestion
availability are unknown. New records begin on the next operational collection
run. Legacy options do not acquire fabricated capture times. Historical results
remain descriptive, with event dependence and tuned thresholds disclosed.

Live collectors and the external model were not invoked during validation. Their
boundaries were mocked in tests; existing credentials, provider settings and
scheduled jobs were not changed. Restart a running dashboard to load the update.

No commit, push or deployment is part of this change.
