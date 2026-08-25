# Dashboard and briefing

Streamlit dashboard (dashboard/app.py + pages/) and Claude briefing generator
(briefing/generate.py). Run the dashboard with `streamlit run dashboard/app.py`
after `git pull` (data arrives via the hourly Actions workflow).
Pages: overview, 1_Positioning, 2_Regime, 3_Liquidations, 4_Options, 5_Screener.
All data loading goes through dashboard/shared.py (st.cache_data, 15 min TTL).
Briefings run weekly via .github/workflows/weekly-briefing.yml (Sunday 06:30 UTC)
or manually; reports land in briefing/reports/.

## Briefing

briefing/generate.py builds a compact JSON context (regime history, cross-
sectional table, DVOL percentile, term structure, 14d liquidations) and pipes
it to headless Claude Code (`claude -p --model sonnet`), so it runs on the
user's Claude subscription - no API key. Missing inputs are omitted from the
context; the prompt tells the model to state gaps. Locally it uses the Claude
Code login; the workflow needs the CLAUDE_CODE_OAUTH_TOKEN repo secret
(generate once with `claude setup-token`).

## Conventions

Every page inserts the repo root into sys.path before imports (Streamlit runs
pages as scripts). Charts use template="plotly_dark"; green #22c55e = bullish /
shorts, red #ef4444 = bearish / longs liquidated.
