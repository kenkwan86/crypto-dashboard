# Trading signals

Three tradable signals layered on the existing z-score / regime analytics.
- **Crowding quadrant** (`analytics/crowding.py`) - labels each coin crowded long /
  short-squeeze fuel / capitulation / apathy from funding z90 x OI-change z90.
  Shown on the **Screener** page (coloured column + quadrant scatter).
- **Regime forward returns** (`analytics/regime_returns.py`) - what the next 7 and 30
  days did from each regime-score quintile. Shown on the **Home** page under the score.
- **Cross-venue funding basis** (`analytics/funding_basis.py`) - Binance minus
  Hyperliquid / Bybit funding, never averaged. Shown on the **Positioning** page.

Each module has a `__main__` block: `python -m analytics.crowding`,
`python -m analytics.regime_returns`, `python -m analytics.funding_basis`.

## Crowding quadrant (`analytics/crowding.py`)

Two inputs, both already produced by `analytics/zscores.py`: `funding_z90` (90d
z-score of the per-8h funding rate) and `oi_z90` (90d z-score of the 7-day % change
in open interest, from the fixed per-coin OI source in `oi_zscores()`).

| label | funding z90 | OI z90 | reading |
|---|---|---|---|
| crowded long | >= +0.75 | >= +0.50 | longs paying up while leverage builds |
| short-squeeze fuel | <= -0.75 | >= +0.50 | shorts paying up while leverage builds |
| capitulation | <= -0.75 | <= -0.50 | shorts paying up while leverage bleeds out |
| apathy | everything else | | no crowd worth fading |

`apathy` is the residual bucket, so it also holds the un-named fourth corner
(funding high, OI falling - longs quietly unwinding).

**Thresholds** are the named constants `FUNDING_Z_HI = 0.75` and `OI_Z_HI = 0.50`.
They were picked by sweeping the 2021-2026 history for a rate of a couple of episodes
per coin-month. Frequency at the chosen cutoffs (59,024 labelled coin-days, 62 coins):

| label | coin-days | share | days/coin-month | episodes/coin-month |
|---|---|---|---|---|
| crowded long | 3,520 | 5.96% | 1.79 | 0.88 |
| short-squeeze fuel | 1,798 | 3.04% | 0.91 | 0.63 |
| capitulation | 3,135 | 5.31% | 1.59 | 1.01 |
| apathy | 50,611 | 85.69% | 25.71 | 2.43 |

**Falsifier result - largely null.** 7d forward return by quadrant, 2021-2026:

| label | n | median % | mean % | p25 % | p75 % | win rate % |
|---|---|---|---|---|---|---|
| crowded long | 3,230 | -0.56 | 2.65 | -7.23 | 7.94 | 47.4 |
| short-squeeze fuel | 1,571 | -0.71 | 1.39 | -7.05 | 6.72 | 47.0 |
| capitulation | 2,857 | +0.36 | 1.57 | -5.46 | 7.15 | 52.2 |
| apathy | 43,441 | -0.83 | 0.58 | -7.16 | 5.73 | 46.0 |
| all coin-days | 65,859 | -0.58 | 1.18 | -7.47 | 6.71 | 46.9 |

"Crowded long" does **not** separate on the median (-0.56% vs -0.83% for apathy, and
-0.58% for the unconditional baseline); its higher mean is fat tails, not edge. The
only bucket that moves is `capitulation` (+0.36% median, 52% win rate). Treat the
quadrant as a description of positioning, not a return forecast - the page says so.

## Regime forward returns (`analytics/regime_returns.py`)

Buckets are **quintiles of the composite score over the whole 2021-2026 history**
(equal counts by construction; fixed cutoffs would leave the extremes near-empty).
1/5 = coldest, 5/5 = hottest. Two forward returns per date: BTC, and the equal-weight
average of every coin with a close on both ends of the window. `avg_coins` (contributing
coins per date) and the per-bucket `n` are reported because early history has severe
survivorship bias - 2021 has ~28 coins on average in the coldest bucket, 2026 has ~60.
The OI leg comes from `analytics.zscores.oi_zscores()` and its `source` map; no other
OI loader is used.

**Falsifier result - flat, so descriptive only.** BTC 30d medians by bucket
(1/5 .. 5/5): -0.95, +2.09, +1.81, -2.36, +1.81 - a 4.4 pp spread with no monotonic
order. `is_flat()` returns True and the Home page labels the table "descriptive only"
with a warning. The one thing that does show up is the universe average in the hottest
bucket (7d median +4.32% vs ~0 elsewhere, 30d +5.11%) - momentum, not mean reversion,
and still not monotonic.

## Cross-venue funding basis (`analytics/funding_basis.py`)

`load_funding()` averages the venues, which hides the trade. This module keeps every
row's venue, normalises each to a per-8h footing with `rate * 8 / interval_h`
(`interval_h` read from disk as-is; the module never writes the parquet), then computes
`binance - hyperliquid` and `binance - bybit`. Only the 33 coins with a symbol on all
three venues in `data/universe.parquet` are kept.

Every number on a row is read at **one** timestamp - the last hour at which the
Binance/Hyperliquid spread exists - because Hyperliquid lags and quoting each venue at
its own newest hour makes the legs disagree with the spread. `age_h` and a `stale` flag
carry that lag to the page.

**Caveat:** Bybit and Hyperliquid funding history only begins 2026-08-25, so the 30-day
z-score window (`Z_WINDOW_HOURS = 720`, `Z_MIN_PERIODS = 48`) is nowhere near full -
about 111 overlapping hours as of 2026-09-05. `coverage()` reports the real overlap.
