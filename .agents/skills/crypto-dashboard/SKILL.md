---
name: crypto-dashboard
description: Maintain and investigate this Crypto Dashboard project's collection, parquet analytics, Streamlit pages and market briefings. Use when implementing features, tracing incorrect metrics, diagnosing data gaps or explaining this repository's behavior.
compatibility: Repository access is sufficient for static work. Runtime work requires Python and requirements.txt dependencies; dashboard rendering requires Streamlit. The existing briefing generator additionally requires an authenticated Claude Code CLI.
---

# Crypto Dashboard

Deliver the requested project change or explanation with the data units,
source provenance and freshness intact. Completion means the affected path is
traced from stored inputs through analytics to its consumer, appropriate checks
are recorded, and remaining limitations are explicit.

## Find the relevant path

Resolve the repository root containing `collectors/`, `analytics/` and
`dashboard/`; all project paths and commands below are relative to that root.
This skill's bundled reference is relative to the skill directory.

Read [Project contracts](references/project-contracts.md) before changing a
metric or data pipeline. Then inspect the actual implementation and the relevant
system document:

| Work | Implementation | Project document |
|---|---|---|
| Collection, gaps, storage | `collectors/hourly.py`, `collectors/common.py`, `collectors/universe.py`, `collectors/backfill/` | `docs/collectors.md` |
| Loaders, z-scores, regime, options | `analytics/data_access.py`, `analytics/zscores.py`, `analytics/regime.py`, `analytics/options_metrics.py` | `docs/analytics.md` |
| Crowding, forward returns, funding spreads | `analytics/crowding.py`, `analytics/regime_returns.py`, `analytics/funding_basis.py` | `docs/signals.md` |
| Volatility and liquidation flush | `analytics/vol.py`, `analytics/flush.py`, `analytics/liquidations.py` | `docs/vol_and_flush.md` |
| UI and report generation | `dashboard/shared.py`, `dashboard/app.py`, `dashboard/pages/`, `briefing/generate.py` | `docs/dashboard-and-briefing.md` |

Use code to establish current behavior when documentation disagrees. Historical
coverage counts and falsifier results in the docs are dated observations, not
current measurements. Maintain the relevant system doc when changing its contract.

## Preserve the analytical meaning

- Deduplicate across legacy and per-writer parquet files before aggregating;
  use existing loaders or reproduce their table-key contract for a new loader.
- Normalize funding by each row's `interval_h` before comparing venues. Keep
  venue identity for basis calculations.
- Use `oi_zscores()` for the screener and regime OI panels; its level, change,
  z-score and source label must refer to the same causally selected per-coin series.
- Use `daily_liquidations()` for daily totals, and hourly-only rows for flush
  detection. Report units, missing inputs and observation times to consumers.
- Preserve descriptive/preliminary labels. Prior-only statistics do not remove unknown historical universe membership,
  absent legacy availability timestamps or event dependence. Do not claim a
  fully point-in-time trading edge.

## Work and verify within scope

Follow project secret-handling instructions. Analytics and storage imports do
not read the environment file. Collector entry points explicitly call
`load_environment()`; do not execute those paths without exact-file authorization.
Use `python -m unittest discover -s tests -v` for synthetic regression checks.

Run commands from the repository root only when their side effects fit the
request. Collection and backfills call external services and write market data;
the regime entry point writes a cache; report generation invokes an external
model and writes a report. A skill migration does not require running them.

For a metric change, check the affected units, duplicate/overlap handling,
source continuity, missing/stale values and consuming page or report with small
synthetic cases where possible. For UI work, retain the shared cache and freshness
display and inspect the changed page when runtime access is available. Report
which checks ran, which did not, and why; do not claim a runtime check from static
inspection.

Report the result, affected files, validation evidence and any material data or
runtime limitation. Keep this skill as one portable project source; do not create
different copies for individual agent hosts.
