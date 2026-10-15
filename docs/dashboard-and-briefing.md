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
