# Dashboard and briefing

Start with `streamlit run dashboard/app.py` from the repository root.
On Windows, double-click `dashboard.bat` to open the same app using local data.
The launcher does not pull or rebase Git history. Sync incoming GitHub data
separately after checking local edits.

The homepage presents data coverage, daily regime components, 1d/7d changes and
positioning worth investigating. Current rankings exclude inactive, stale,
incompletely covered and insufficient-history coins. An expander explains each
exclusion. Daily metrics use completed UTC days rather than forming daily bars.

The sidebar retains Positioning, Regime, Liquidations, Options and Screener and
adds Research and Coin Detail. Research contains the retrospective bucket table
with explicit limitations. Coin Detail brings price, funding, the selected OI
source, liquidation history and per-feed observation ages into one view.
Screener and funding basis default to usable/current observations; an option
allows inspecting excluded rows. Historical plots remain visible with warnings.

`dashboard/shared.py` caches the shared snapshot for 900 seconds. Its coverage
expander shows each expected coin/source feed, distinguishing inactive historical
series from missing or stale current ones. A table's newest timestamp no longer
stands in for every constituent's freshness.

Every page also shows the hourly git sync health. `render_sync_status()` in
`dashboard/shared.py` reads `logs/sync-status.json` (written by
`tools/run_hourly.ps1`) through `collectors.run_status.sync_warning` and shows an
`st.error` when the last run failed (naming the error and the last success, or
"never succeeded"), when the last success is over 3 hours old, or when the file is
unreadable. A missing file (cloud, fresh clone) is silent. `render_freshness()`
calls it; Regime, Research and Coin Detail call it directly after the title.

## Briefing

`python -m briefing.generate` still uses the existing authenticated model CLI.
`analytics/snapshot.py` supplies the same facts used on the homepage. It removes
stale or invalid current observations before model invocation and carries units,
observation timestamps, source labels and exclusion reasons. Legacy options
whose actual capture time is unknown are omitted from current commentary.

The prompt emphasizes changes and invalidation conditions. After a successful
report, a machine-readable `snapshot-YYYY-MM-DD.json` is saved beside the Markdown
report. The next report compares shared usable coins against that snapshot;
OI changes are compared only when source labels match. This history starts with
the first new successful report, not by inferring facts from old prose.

Reports remain in `briefing/reports/`. No provider settings or credentials are
changed by the analytics update.
