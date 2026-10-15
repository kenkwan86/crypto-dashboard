# Volatility spread and liquidation flush

## Volatility

`analytics/vol.py` computes DVOL minus trailing 30-day realized volatility for
BTC/ETH. Close-to-close remains the default; Parkinson remains a companion
estimate. Realized volatility uses an explicit hourly calendar grid and a
720-clock-hour window with 480 valid observations. Missing hours are not filled,
so a multi-hour price change cannot be annualized as a one-hour return.

Spread percentile uses the trailing 365 days with at least 480 observations,
not a rank against future data. >=80 is labelled rich and <=20 cheap relative to
the trailing distribution. This describes implied versus past realized movement;
it does not establish the profitability of an option trade. `latest_spread()`
returns the newest whole row per currency; a missing percentile stays missing
rather than being filled from an older hour.

## Flush

Hourly long/short liquidations are divided by positive OI from one selected
source. The source is chosen using the first 72 actual liquidation hours:
Coinalyze if it overlaps at least half, otherwise Binance. It is then held fixed;
missing source observations are not replaced with another venue. Baseline
accumulation begins after source selection.

Each z-score compares the current ratio with the prior 30 calendar days,
excluding the current event, and requires at least 72 baseline observations.
Zero variance produces no z-score. The threshold remains z >= 3. Future rows
cannot rewrite prior flags; corrections to historical observations still can.
The previous full-sample z-score results are obsolete under this definition.

The falsifier joins prices at exactly t+24h. Missing endpoints remain missing.
The base sample requires available signal baselines. Events can cluster within
market-wide cascades, so event counts do not equal independent sample counts.
Current event tables use wall-clock UTC freshness, not the newest stored row as
an implicit clock. Historical charts remain available when current data is stale.

Run diagnostics with `python -m analytics.vol` and `python -m analytics.flush`.
These analytics imports no longer read environment files. Regression tests use
synthetic data via `python -m unittest discover -s tests -v`.
