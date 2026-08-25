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
  Code; `python -m briefing.generate` writes a Claude market briefing
  (weekly via Actions).

## Setup

```
pip install -r requirements.txt
python -m collectors.universe
python -m collectors.hourly --daily
streamlit run dashboard/app.py
```

Secrets (GitHub Actions repo secrets, or local env vars):
- `COINALYZE_API_KEY` - free at https://coinalyze.net/account/api (liquidations, aggregated OI)
- `ANTHROPIC_API_KEY` - for briefings only

See `CLAUDE.md` for schemas and commands, `docs/` for system docs.
