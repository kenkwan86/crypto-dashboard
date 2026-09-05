# Review plan for Crypto-Dashboard

Source: C:\01. Coding\review-factory\reviews\Crypto-Dashboard\2026-09-04-blind.md

Mode: PLAN

Every item below repairs a number a trader reads off the dashboard or the briefing. P1-P3 are one chain (funding units), P4 and P5 are independent, P6-P7 are collection coverage, P8-P11 are display and downstream. Execute in `Order:` sequence; P3 depends on P2, P2 depends on P1's column name.

## Done when

- [ ] D1: `SELECT count(*) FROM read_parquet('data/funding/*.parquet', union_by_name=true) WHERE interval_h IS NULL` returns 0, and `load_funding()` returns a per-8h-normalised `rate`.
- [ ] D2: The median funding level panel (`funding_zscores()["value"].median(axis=1)`) shows no step down at 2026-08-25 — the post-Aug-25 daily medians sit in the same range as the July medians, not ~4x below.
- [ ] D3: The BTC daily OI level shown on Positioning and Screener has no single-day change above 35% over the last 30 days, and each displayed level carries the name of the single source it came from.
- [ ] D4: One long/short pair per (symbol, day) comes out of the liquidations aggregator, taken from either the 1h rows or the 1d row and never their sum; BTC 2026-08-24 is no longer ~$44.5M.
- [ ] D5: Binance funding rows exist for every day from 2026-08-04 to 2026-08-24, and a single `python -m collectors.hourly` run refills Binance OI hours missed in the previous 48h.
- [ ] D6: Home, Screener, Positioning, Liquidations and Options each print the max timestamp of the data behind them and its age; `latest()` in `analytics/zscores.py` no longer forward-fills a second time.

### P1 — Persist the funding interval at every write site

Resolves: F1, F3 (write half)
Files: `collectors/hourly.py`, `collectors/backfill/binance_vision.py`, `CLAUDE.md`
Change: In `collect_funding` (`collectors/hourly.py:45-59`) read `entry.get("interval")` — ccxt 4.5.28 returns a string like `"8h"`/`"4h"`/`"1h"` (binance builds it from `fundingIntervalHours`, hyperliquid hard-codes `'1h'`) — parse the leading number to a float and store it as `interval_h` on every funding row, leaving it `None` when ccxt gives nothing rather than guessing 8. In `backfill_funding` (`collectors/backfill/binance_vision.py:121-137`) add `"interval_h": df["funding_interval_hours"]`; the Binance Vision monthly funding CSV carries that column (confirmed against the 2026-08 BTCUSDT zip: `['calc_time','funding_interval_hours','last_funding_rate']`). Update the `funding` row of the schema table in `CLAUDE.md` to list `interval_h` and state that the stored `rate` is per that interval. Do not change `TABLE_KEYS["funding"]`; the key stays `["symbol","ts","exchange"]`.
Check: `python -m collectors.hourly` (needs network), then `python -c "import duckdb;duckdb.sql(\"SET timezone='UTC'\");duckdb.sql(\"SELECT exchange, count(*) n, count(interval_h) with_iv, min(interval_h) mn, max(interval_h) mx FROM read_parquet('data/funding/2026-local.parquet', union_by_name=true) WHERE ts >= now() - INTERVAL 2 HOUR GROUP BY 1\").show()"` — `with_iv` equals `n` for every exchange and hyperliquid shows `mn = mx = 1`.
Order: 1

### P2 — Backfill `interval_h` onto the funding rows already on disk

Resolves: F1, F3 (history half)
Files: `tools/migrate_funding_interval.py` (new)
Change: Write a one-off, idempotent script that rewrites each `data/funding/*.parquet` in place (temp file plus `os.replace`, the pattern at `collectors/common.py:69-80`) adding `interval_h`, and skips files that already have it fully populated. Assign it as: `hyperliquid` rows → `1.0`; `bybit` rows → the venue's funding interval from one `ccxt.bybit().load_markets()` lookup, defaulting to `8.0`; `binance` rows before the first live hourly row (2026-08-25 08:00) → the median gap in hours between consecutive settlements for that (symbol, calendar month), snapped to the nearest of {1, 2, 4, 8}, with any month holding fewer than 10 rows inheriting the nearest month that has more; `binance` rows on or after that cut-off (hourly snapshots, so the gap is 1h and carries no information) → the value from the nearest earlier month for that symbol, else the current `fetch_funding_rates` interval. A query over today's data gives 1650 symbol-months at 8h, 473 at 4h and 6 anomalies, which is what the snapping and the small-month rule exist for. Print a per-value row count at the end.
Check: `python tools/migrate_funding_interval.py && python -c "import duckdb;duckdb.sql(\"SET timezone='UTC'\");duckdb.sql(\"SELECT count(*) AS null_interval FROM read_parquet('data/funding/*.parquet', union_by_name=true) WHERE interval_h IS NULL\").show();duckdb.sql(\"SELECT interval_h, count(*) FROM read_parquet('data/funding/*.parquet', union_by_name=true) GROUP BY 1 ORDER BY 1\").show();duckdb.sql(\"SELECT symbol, max(interval_h) FROM read_parquet('data/funding/*.parquet', union_by_name=true) WHERE symbol IN ('BTC','ENA') AND exchange='binance' GROUP BY 1\").show()"` — `null_interval` is 0, the value set is a subset of {1, 4, 8}, BTC is 8 and ENA is 4.
Order: 2

### P3 — Normalise funding to a per-8h rate inside `load_funding`

Resolves: F1, F3 (read half)
Files: `analytics/data_access.py`, `dashboard/pages/5_Screener.py`, `dashboard/pages/1_Positioning.py`, `CLAUDE.md`
Change: In `load_funding` (`analytics/data_access.py:31-41`) read the parquet glob with `union_by_name=true` — without it DuckDB takes the first file's schema and silently drops `interval_h`, verified on a two-file fixture — dedupe with `max(rate)` and `max(interval_h)` per (symbol, ts, exchange), then replace `avg(rate)` with `avg(rate * 8.0 / interval_h)` over rows where `interval_h IS NOT NULL`, keeping the output column named `rate` so `analytics/zscores.py:36` needs no change. Add `union_by_name=true` to the other loaders reading the same globs so a later column addition cannot vanish the same way. With the rate now per-8h, the `* 3 * 365` at `dashboard/pages/5_Screener.py:19` and `dashboard/pages/1_Positioning.py:30` is correct for every venue and every symbol; change only the Screener caption at `dashboard/pages/5_Screener.py:32` to say funding is normalised to a per-8h rate before annualising, and update the `funding` schema note and the DuckDB example in `CLAUDE.md`, which currently teaches `avg(rate)*3*365*100` on the raw column.
Check: `python -c "from analytics.zscores import funding_zscores; p=funding_zscores()['value'].median(axis=1); print(p.loc['2026-07-20':].round(6).to_string())"` — the daily medians from 2026-08-25 onward sit in the same range as the late-July values (~5e-5) instead of dropping to ~1.3e-5.
Order: 3

### P4 — Show one OI scope, labelled, instead of a per-hour source mix

Resolves: F2
Files: `analytics/zscores.py`, `analytics/data_access.py`, `dashboard/pages/1_Positioning.py`, `dashboard/pages/5_Screener.py`, `CLAUDE.md`
Change: In `oi_zscores` (`analytics/zscores.py:41-60`) return the already-built single-source `continuous` frame as `"value"` instead of the mixed `panel` from `load_open_interest()`, and add a `"source"` entry mapping each symbol to `"binance"` or `"coinalyze_agg"` from the branch that already picks it at `analytics/zscores.py:51-55`. Delete `load_open_interest()` and its tier CASE (`analytics/data_access.py:44-69`) — `analytics/zscores.py:46` is its only caller — and delete the `CLAUDE.md` line telling readers that `load_open_interest()` "already resolves the live-vs-backfill source overlap correctly", which is the claim this finding disproves. Put the source name in the Positioning chart title at `dashboard/pages/1_Positioning.py:45` and add an `oi_src` column beside `oi_usd_M` on the Screener (`dashboard/pages/5_Screener.py:20-24`); symbols with neither a deep Binance series nor a Coinalyze series get NaN rather than a mixed number.
Check: `python -c "from analytics.zscores import oi_zscores; o=oi_zscores(); v=o['value']['BTC'].tail(31); print(v.round(0).to_string()); print('max 1d change', round(float(v.pct_change().abs().max()),3)); print('source', o['source']['BTC'])"` — the max one-day change is below 0.35 and the 2026-09-03 to 2026-09-04 step from 10.23B to 15.95B is gone.
Order: 4

### P5 — Give liquidations a granularity key and one shared daily aggregator

Resolves: F4
Files: `collectors/common.py`, `collectors/hourly.py`, `collectors/backfill/coinalyze.py`, `analytics/data_access.py`, `analytics/liquidations.py` (new), `dashboard/pages/3_Liquidations.py`, `briefing/generate.py`, `tools/migrate_liquidation_interval.py` (new), `CLAUDE.md`
Change: Add an `interval` column to the liquidations table and make `TABLE_KEYS["liquidations"]` `["symbol","ts","interval"]` (`collectors/common.py:34`); the hourly path writes `"1h"` (`collectors/hourly.py:108-116`), the Coinalyze backfill writes `"1d"` (`collectors/backfill/coinalyze.py:28-37`). Write a one-off migration that labels the rows already on disk per file: everything in `2021-local` through `2025-local`, and every row whose `ts` hour is not 0, is unambiguous (`1d` and `1h` respectively); rows at hour 0 in `2026-cloud.parquet` are `1h`, because the cloud runner has only ever called the 1hour endpoint; rows at hour 0 in `2026-local.parquet` dated on or after 2026-08-24 are genuinely ambiguous — under the old key one may have overwritten the other — so label them `"unknown"` and leave them in place rather than deleting data, then re-run `python -m collectors.backfill.coinalyze` to lay down clean `1d` rows for those days under the new key. Add `analytics/liquidations.py` with `daily_liquidations()` returning one long/short pair per (symbol, day): the sum of the `1h` rows when that day has at least 20 of them, otherwise the `1d` row, ignoring `unknown` entirely. Have `load_liquidations` (`analytics/data_access.py:110-117`) carry `interval` through, and switch both `dashboard/pages/3_Liquidations.py:24-25` and `briefing/generate.py:67-73` off their raw `groupby(day).sum()` onto `daily_liquidations()`.
Check: `python -c "from analytics.liquidations import daily_liquidations; d=daily_liquidations(); b=d[d['symbol']=='BTC'].set_index('day').loc['2026-08-20':'2026-08-27']; print((b[['long_usd','short_usd']]/1e6).round(2).to_string())"` — BTC 2026-08-24 shows either the ~24.6M daily total or the ~19.9M hourly sum, not ~44.5M.
Order: 5

### P6 — Refill the August funding hole and add a current-month funding gap fill

Resolves: F5
Files: `collectors/backfill/binance_vision.py`
Change: Add `gap_fill_funding(base, ccxt_symbol)` mirroring `gap_fill_klines` (`collectors/backfill/binance_vision.py:99-118`): page `ccxt.binanceusdm().fetch_funding_rate_history` from the first of the current month to now, write `symbol/ts/rate/exchange='binance'` plus the `interval_h` from that symbol's current `fetch_funding_rates` entry, and call it from the `funding` branch of `main` (`collectors/backfill/binance_vision.py:183-184`) exactly as the klines branch calls its gap fill at line 182. Then run `python -m collectors.backfill.binance_vision funding`: `months_until_last_complete` now includes 2026-08, so the monthly zips close the 2026-08-04 to 2026-08-24 hole for all 50 symbols and the new gap fill covers 2026-09-01 onward. Run this after P1 so the newly written rows already carry `interval_h`.
Check: `python -c "import duckdb;duckdb.sql(\"SET timezone='UTC'\");duckdb.sql(\"SELECT count(DISTINCT date_trunc('day',ts)) AS days FROM read_parquet('data/funding/*.parquet', union_by_name=true) WHERE exchange='binance' AND symbol='BTC' AND ts >= TIMESTAMPTZ '2026-08-04' AND ts < TIMESTAMPTZ '2026-08-25'\").show()"` — `days` is 21.
Order: 6

### P7 — Fetch a 48h history window instead of a single point sample

Resolves: F6
Files: `collectors/hourly.py`, `CLAUDE.md`
Change: In `collect_funding` and `collect_open_interest` (`collectors/hourly.py:45-90`), keep the point-in-time write but add a catch-up sweep that runs only when the newest stored row for that (table, exchange) is more than 90 minutes old, so a healthy hourly cadence costs nothing and a missed run is repaired by the next one. For funding, page `fetch_funding_rate_history` per symbol from the newest stored ts, capped at 48h back, for every exchange whose `has['fetchFundingRateHistory']` is true, storing rows at their settlement timestamps with the same `interval_h` the point sample uses. For open interest, use Binance's `fetch_open_interest_history(symbol, '1h', since=...)` for the Binance leg only; Bybit and Hyperliquid expose no usable history endpoint here, so their gaps stay unfillable and that limit belongs in the `CLAUDE.md` gotcha list next to the existing 30-day note. Keep the sweep inside the 15-minute `timeout-minutes` at `.github/workflows/hourly.yml:20` — 50 symbols per exchange under ccxt rate limiting is the budget to watch; abandon the sweep with a printed warning rather than overrun it.
Check: `python -m collectors.hourly` (needs network), then `python -c "import duckdb;duckdb.sql(\"SET timezone='UTC'\");duckdb.sql(\"SELECT count(DISTINCT ts) AS hours FROM read_parquet('data/open_interest/*.parquet', union_by_name=true) WHERE symbol='BTC' AND exchange='binance' AND ts >= now() - INTERVAL 48 HOUR\").show()"` — `hours` is at least 46, against the 3-15 rows per day the table holds today.
Order: 7

### P8 — Print data age on every page and stop the second forward fill

Resolves: F7
Files: `dashboard/shared.py`, `dashboard/app.py`, `dashboard/pages/1_Positioning.py`, `dashboard/pages/3_Liquidations.py`, `dashboard/pages/5_Screener.py`, `analytics/zscores.py`
Change: Add a cached `data_freshness()` to `dashboard/shared.py` returning `max(ts)` per table straight from the parquet globs plus the age in hours. Render it as a caption on Home (`dashboard/app.py:22-28`), Screener (`dashboard/pages/5_Screener.py:26-32`), Positioning and Liquidations: the timestamp, the age, and `st.error` once funding, open interest or liquidations pass 3 hours or options passes 30 hours. Drop the second forward fill in `latest` (`analytics/zscores.py:79`) so it reads `panel.iloc[-1]`; `daily_panel` (`analytics/zscores.py:30`) already ffills to 3 days, and the two stacked are what allow a 6-day-old value to be shown as current.
Check: `python -c "from dashboard.shared import data_freshness; import json; print(json.dumps(data_freshness(), indent=2, default=str))"` prints a max ts and an age for every table; then `streamlit run dashboard/app.py` and confirm by eye that Home and Screener show that timestamp and age above their tables.
Order: 8

### P9 — Take the options snapshot whenever today's is missing

Resolves: F8
Files: `collectors/hourly.py`
Change: Replace the `now.hour == 0` gate at `collectors/hourly.py:198` with a check on stored state: read `max(ts)` from `data/options_chain/*.parquet` and call `collect_options` whenever that is earlier than `now.floor("D")`, or `--daily` was passed. The snapshot is already keyed on the day (`collectors/hourly.py:149`), so this stays idempotent and a PC that is on at any hour of the day now captures that day's chain. Make the swallowed failure legible: the `except` at `collectors/hourly.py:199-202` should record `options: failed` in the printed run summary rather than only printing mid-run, so a run of Deribit geo-blocks is visible in `logs/hourly.log`.
Check: `python -m collectors.hourly --daily` at any non-00 hour, then `python -c "import duckdb;duckdb.sql(\"SET timezone='UTC'\");duckdb.sql(\"SELECT max(ts) FROM read_parquet('data/options_chain/*.parquet', union_by_name=true)\").show()"` — the max ts is today's date, and a second run in the same day adds no rows.
Order: 9

### P10 — Drop the forming DVOL candle

Resolves: F10 (forming-candle half; the cross-writer `max()` preference is under Not doing)
Files: `collectors/hourly.py`
Change: In `collect_options` (`collectors/hourly.py:132-144`) the DVOL request runs to `end_timestamp = now`, so the last hourly candle returned is the still-forming hour and its close is not that hour's close. Drop it exactly as `collect_ohlcv` drops its last candle (`collectors/hourly.py:39`), by slicing the parsed candle list before building `dvol_rows`. The 3-day lookback means earlier hours are re-fetched and corrected on the next run either way; this removes the one hour that never gets corrected before it reaches `dvol_pct` in the regime (`analytics/regime.py:43-47`).
Check: after `python -m collectors.hourly --daily`, `python -c "import duckdb,pandas as pd;duckdb.sql(\"SET timezone='UTC'\");print(duckdb.sql(\"SELECT max(ts) FROM read_parquet('data/options_dvol/*.parquet', union_by_name=true)\").df());print('current hour', pd.Timestamp.now(tz='UTC').floor('h'))"` — the max ts is strictly earlier than the current hour.
Order: 10

### P11 — Put units and as-of stamps into the briefing context

Resolves: F9
Files: `briefing/generate.py`
Change: In `build_context` (`briefing/generate.py:35-74`) add a `units` block naming what each number is — funding as a per-8h rate (true only once P3 lands, so write it after that), OI in USD with the per-symbol source P4 adds, liquidations in USD per day, `mark_iv` and `atm_iv` in percent, and `total_oi` from `analytics/options_metrics.py:66` in contracts rather than USD — and a `data_as_of` block giving the max ts per table from the same helper P8 adds. Extend `SYSTEM_PROMPT` (`briefing/generate.py:25-32`) with an instruction to state the age of each input it cites and to refuse to draw a conclusion from any table older than 24 hours.
Check: `python -c "from briefing.generate import build_context; import json; c=build_context(); print(json.dumps({k:c[k] for k in ('units','data_as_of')}, indent=2, default=str))"` — both blocks print, `units` names the funding interval and the `total_oi` contract unit, and `data_as_of` carries a timestamp for every table feeding `cross_section`, `btc_dvol`, `options_term_structure` and `liquidations_daily_14d_usd`.
Order: 11

## Not doing

- F11 (regime cache written but never read) — minor, and its own Impact line says "No user-visible effect today", so it does not bear on the goal of correct tradable signals. Deleting the write at `analytics/regime.py:62` is a free ride on any later touch of that file.
- F12 (survivorship and selection look-ahead from today's top-50 universe) — minor, and the fix is not one obvious edit: it needs a per-date universe snapshot, a coverage-normalised liquidation series, and a contributing-coin count on the regime chart.
- F13 (no tests) — minor, and the fix is not one obvious edit: it needs a two-writer, three-exchange parquet fixture per loader plus a step in `.github/workflows/hourly.yml`, and pytest is not a declared dependency. This is the largest thing the plan leaves behind, since P3, P4 and P5 all change loader contracts that nothing will re-check.
- F10, the cross-writer `max()` preference — the deterministic-writer half needs a source-priority column that no table has; only the forming-DVOL-candle half is planned, as P10.
- F2, Coinalyze `.A` aggregate coverage — the reviewer marked this CANNOT TELL because measuring it needs the owner's Coinalyze API key. P4 makes the scope visible and labelled, which is what the trade decision needs; what the aggregate actually covers stays open.

## Simpler alternative considered

The smaller change for F1 alone is to drop non-Binance venues from the funding series the way `load_open_interest_binance` already does for OI, needing no schema column at all — but it leaves F3's 26 four-hour Binance symbols annualised 2x low and blanks funding on every day the PC was off, so the `interval_h` column in P1-P3 is the smaller change that resolves both findings.

## SCOPE

Covers: every critical and major finding (F1-F8) plus the two minor findings whose fix is a single edit (F9, and the forming-candle half of F10). The funding chain P1-P3 is what changes the dashboard's reading of crowding today; P4 and P5 remove the two fabricated series (the OI source seam and the double-counted liquidation days); P6 and P7 close the data gaps that made both worse; P8-P11 stop stale and unlabelled numbers being read as current.

Leaves for later: tests (F13), universe survivorship (F12), the dead regime cache (F11), deterministic cross-writer dedupe (F10), and the unmeasured Coinalyze aggregate coverage noted under F2.

Least sure about: P2. The interval for historical Binance rows is reconstructed from the gap between stored settlements rather than read from a source of truth; today's data gives a clean 8h/4h split with six anomalous symbol-months, and the snapping plus small-month inheritance rule is a judgement call about those six. If the executor prefers certainty over speed, the alternative is to clear the `funding|*` keys from `data/_backfill_manifest.json` and re-download every monthly zip, which carries `funding_interval_hours` directly — roughly 3,400 downloads, and it leaves the legacy untagged `data/funding/20NN.parquet` rows duplicated with a null interval, which the `max(interval_h)` dedupe in P3 tolerates. P7 is second: the runtime budget against the 15-minute workflow timeout has not been measured.
