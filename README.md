# Crypto Dashboard

Self-hosted crypto positioning analytics, modeled on tradingriot.com's crypto
stack, built entirely on free data sources.

- **Data**: hourly funding, open interest (Binance + Bybit + Hyperliquid),
  aggregated liquidations (Coinalyze), BTC/ETH options (Deribit), 1h OHLCV.
  History backfilled from Jan 2021 via Binance Vision bulk archives.
- **Storage**: parquet files in `data/`, queried with DuckDB. A GitHub Actions
  cron collects hourly and commits.
- **Analytics**: rolling z-scores for funding/OI/momentum, cross-sectional
  screener, composite regime index, options term structure and 25-delta skew.
- **Dashboard**: Streamlit (`streamlit run dashboard/app.py`).
- **LLM layer**: `CLAUDE.md` documents schemas for ad hoc analysis with Claude
  Code; `python -m briefing.generate` writes a Claude market briefing via
  headless Claude Code (`claude -p`) - uses the Claude subscription, no API key
  (weekly via Actions).

## Setup

```
pip install -r requirements.txt
python -m collectors.universe
python -m collectors.hourly --daily
streamlit run dashboard/app.py
```

Secrets (GitHub Actions repo secrets; locally copy `.env.example` to `.env`):
- `COINALYZE_API_KEY` - free at https://coinalyze.net/account/api (liquidations, aggregated OI)
- `CLAUDE_CODE_OAUTH_TOKEN` - for the weekly briefing workflow only; generate
  once from your Claude subscription with `claude setup-token`. Local briefings
  just use your Claude Code login.

See `CLAUDE.md` for schemas and commands, `docs/` for system docs.
