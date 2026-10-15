# Crypto Dashboard

Personal crypto derivatives analytics built on free market data, parquet,
DuckDB, pandas, Streamlit and Plotly. Use the project skill when changing or
investigating collectors, analytics, dashboard pages or market briefings.

<!-- agent-plugins-sync:skills:start -->
- [crypto-dashboard](.agents/skills/crypto-dashboard/SKILL.md): project architecture,
  data contracts, operating commands and validation constraints.
<!-- agent-plugins-sync:skills:end -->

Protect secret-bearing files, including existing environment examples and local
tool configuration. Read an exact protected file only when the user explicitly
authorizes reading that file in the current turn; reading permission does not
authorize editing or disclosure. Exclude these files from broad searches and
diffs. Use a new placeholder-only file for configuration changes and have the
user fill values locally.

`collectors/common.py` is safe to import. Only operational collector entry points
explicitly call `load_environment()`, which reads the root `.env`. Do not execute
that startup path without the required exact-file authorization. Tests use
synthetic fixtures and mocked services; analytics and dashboard reads need no
credentials.

Deduplicate parquet across writer files before aggregation. Funding intervals
vary per symbol; OI changes require a consistent source; daily and hourly
liquidation rows must not be added together. See the skill for exact contracts.
