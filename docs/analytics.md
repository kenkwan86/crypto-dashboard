# Analytics

Computes z-scores, the composite regime index, and options metrics from the
parquet tables. Key files: analytics/data_access.py (DuckDB loaders),
analytics/zscores.py (rolling z-scores + cross-sectional table),
analytics/regime.py (composite regime index, cached to
data/analytics_cache/regime.parquet), analytics/options_metrics.py
(term structure + 25-delta risk reversal). All entry points runnable as
python -m analytics.<module>; the dashboard imports them via dashboard/shared.py.

## Source-overlap rule

open_interest holds three live exchanges plus two backfill sources
(binance metrics, coinalyze_agg). data_access.load_open_interest() picks, per
(symbol, ts), the live-exchange sum when present, else the backfill value —
never both. Any new OI consumer must go through this loader.

## Regime index

Daily mean of six clipped [-3,3] components: median funding z90, 1y rolling
percentile of the median funding LEVEL (absolute crowdedness - z-scores alone
miss long-lasting hot periods), median 7d-OI-change z90, median 30d-return z90,
breadth ((% coins above 50d MA - 0.5) * 4), BTC DVOL 1y rolling percentile
rescaled the same way. Positive = crowded/hot. Validated against history:
+1.35 Feb 2021, -1.15 Jun 2021, -1.0 Dec 2021, -0.99 May 2022 (LUNA),
+1.23 Mar 2024, -0.57 Aug 2024 flush.
n_components records how many inputs existed that day; early history has fewer.

## Options metrics

Black-Scholes delta is computed from mark_iv because Deribit's book summary
endpoint returns no greeks. IV at +/-0.25 delta is linearly interpolated across
strikes per expiry; expiries under 2 days are dropped as noise.
