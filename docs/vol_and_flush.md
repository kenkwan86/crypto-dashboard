# Vol spread and liquidation flush

Two tradable signals. **Vol spread** (`analytics/vol.py`) compares Deribit DVOL
against 30-day realised vol from the stored hourly candles and ranks the gap
over five years, answering "are options rich or cheap right now?"; it renders on
`dashboard/pages/4_Options.py`. **Liquidation flush** (`analytics/flush.py`)
normalises hourly long/short liquidations by each coin's open interest, z-scores
them and flags cascades; it renders on `dashboard/pages/3_Liquidations.py`.
Run either standalone: `python -m analytics.vol`, `python -m analytics.flush`.

## Vol spread (O3)

Inputs: `data/options_dvol` (hourly Deribit DVOL, BTC + ETH, since 2021-04) and
`data/ohlcv` (hourly Binance candles, high/low/close, since 2021).

- `load_hourly_ohlcv` / `load_dvol_hourly` - deduped DuckDB loaders local to the
  module (`analytics/data_access.py` is untouched).
- `realised_vol(candles)` - both estimators on a 720-hour (30-day) rolling
  window, min 480 observations, annualised by `sqrt(24*365)` and put in % points
  so they sit on DVOL's scale:
  - `close_to_close` - stdev of hourly log returns.
  - `parkinson` - `sqrt(mean(ln(h/l)^2) / (4 ln 2))`.
- `vol_spread(estimator)` - per (currency, ts): DVOL, both RV30s,
  `spread = DVOL - RV30`, and `spread_pct`, the spread's full-history rank
  (0-100).
- `latest_spread()` / `reading(pct)` - the current row per coin and the one-line
  verdict: rich at >= 80th percentile, cheap at <= 20th, fairly priced between.

**Default estimator is `close_to_close`**, and the reason is in the module
docstring: a hedged short-option position accrues P&L against realised *return*
variance, which is what close-to-close measures. Parkinson is ~5x more efficient
per observation but measures the path's range; on a 24/7 market with no
open/close gaps it prints systematically below close-to-close when intra-hour
reversals are frequent, so pricing a vol sale off it flatters the edge. It is
displayed alongside as a lower-noise cross-check - when the two disagree
materially the tape has been chop rather than trend and the spread deserves less
weight.

Page section "Implied vs realised volatility": five metrics per coin (DVOL,
both RV30s, spread, percentile), the reading line, and a 180-day DVOL vs RV30
chart for BTC and ETH (realised drawn dotted).

The per-expiry version of the same idea (ATM IV from `options_chain` snapshots
minus RV over the matching horizon) is **not** built. Chain snapshots are daily
00 UTC only and sparse, so the series would be mostly gaps; the term structure
already on the Options page covers the shape question.

## Liquidation flush (O4)

Inputs: `data/liquidations` rows with `interval = '1h'` (live collector, since
2026-08-24 - the `1d` backfill rows and the `unknown` rows are excluded) and
hourly `data/open_interest`.

- `long_ratio = long_usd / oi_usd`, `short_ratio = short_usd / oi_usd`. The
  dollar figure alone is not comparable across coins; the OI-normalised ratio is.
- **Z-score window: the coin's full hourly history, as one expanding-sample mean
  and stdev.** The hourly rows are under two weeks old, so the rolling 30/90/365
  day windows in `analytics/zscores.py` would return all NaN. Coins with fewer
  than `MIN_HOURS = 72` hourly rows are dropped (50 of 62 survive today).
  Move to rolling z30 once a few months of hourly rows exist.
- **Threshold `FLUSH_Z = 3.0`**, picked from the data. The ratio distribution is
  heavily right-skewed, so the normal-tail intuition (z >= 3 is 0.13% of hours)
  is wrong: on the history to date it fires on 2.14% of long-side and 2.02% of
  short-side hours, about one flagged hour per coin every two days. That is
  where the flag still isolates visible cascades rather than hourly noise, and
  it leaves enough events to test. z >= 4 (~1.4% of hours) is the stricter
  alternative.
- **OI source**: one continuous source per coin, never a sum (see CLAUDE.md).
  Coinalyze aggregated OI is preferred because the liquidation numbers are
  themselves Coinalyze's cross-exchange aggregate - dividing an all-venue
  numerator by one venue's OI would overstate every ratio. Binance-only OI is
  the fallback when Coinalyze covers less than half a coin's liquidation hours.
  The source used is reported per coin as `oi_src`.
- `flush_events(panel, hours=48)`, `top_flush_now(panel)` (each coin's newest
  row, only if within `STALE_HOURS = 6` of the panel's latest hour), and
  `falsifier(panel)`.

Page section "Liquidation-flush trigger (hourly)": the last 48 hours of events
(coin, ts, side, size, % of OI, z), the current top 10 by long-flush z and by
short-flush z, and the falsifier table under a PRELIMINARY warning.

### Falsifier result (as of 2026-09-05, hourly history 2026-08-24 -> 2026-09-05)

Do long-flush hours precede positive 24h returns more often than chance?

| sample | n | hit rate | mean 24h return |
|---|---|---|---|
| all coin-hours (base) | 6,278 | 44.4% | -0.09% |
| long flush, z >= 3 | 145 | 51.0% | -1.35% |
| short flush, z >= 3 | 140 | 37.1% | -5.21% |

Long flushes beat the base rate by 6.6 points on hit rate but the mean forward
return is still negative and worse than base - the sign flips depending on
whether you weight by count or by size, which is what a fat left tail looks
like. Short flushes are clearly bad to buy. **Preliminary**: under two weeks of
data, and the events cluster inside a handful of market-wide cascades (the
2026-09-04 12:00 UTC hour alone accounts for a large share of the long events),
so 145 events is nothing like 145 independent observations. Re-run this once a
few months of hourly rows exist before trading it.
