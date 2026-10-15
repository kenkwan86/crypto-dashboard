"""Generate a market regime briefing with Claude.

Assembles the latest metrics into a compact JSON context, runs headless Claude
Code (`claude -p`), and saves a markdown report to briefing/reports/.

Run: python -m briefing.generate
Locally this uses the Claude Code login (Max plan) - no API key needed.
In CI, set the CLAUDE_CODE_OAUTH_TOKEN secret (generate once with
`claude setup-token`).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

MODEL = "sonnet"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"

SYSTEM_PROMPT = """You are a crypto derivatives strategist writing a concise market
regime briefing from positioning data. Be specific and numbers-driven. Structure:
1. Regime assessment - where are we (hot/neutral/washed-out) and the trend of the score.
2. Positioning extremes - coins with stretched funding or OI z-scores, and what that implies.
3. Volatility - DVOL level/percentile, term structure shape, skew, and what they price in.
4. Liquidation picture - recent flush activity or its absence.
5. Watchlist - 3-5 concrete things that would change the assessment (levels, z-score reversals).
Plain English, no hedging boilerplate. State data gaps plainly if inputs are missing.
Lead with changes over the last completed day and week and what would invalidate the assessment.
Use only supplied facts; gaps and excluded_coins are unavailable, never neutral.
State the age of each input you cite (see observation timestamps and data_quality), and refuse to draw any
conclusion from a table whose data is older than 24 hours - say so instead."""


UNITS = {
    "funding": "per-8h rate (rate * 3 * 365 annualises it); each venue's stored "
               "interval is normalised to a per-8h rate before averaging",
    "open_interest": "USD notional; one single source per symbol (binance or "
                     "coinalyze_agg, see cross_section.oi_src) - never a mix across time",
    "liquidations": "USD per (symbol, day), one long/short pair per day",
    "mark_iv": "percent (e.g. 55.2 means 55.2% IV)",
    "atm_iv": "percent",
    "total_oi": "option contracts (Deribit units), NOT USD",
    "funding_change_1d": "change in per-8h fractional funding rate between completed UTC days",
    "funding_change_7d": "change in per-8h fractional funding rate over seven calendar days",
    "oi_return_1d": "fractional OI change, same source, one calendar day",
    "oi_return_7d": "fractional OI change, same source, seven calendar days",
}


def build_context() -> dict:
    from analytics.snapshot import build_snapshot, briefing_facts
    return briefing_facts(build_snapshot()) | {'units': UNITS}


def main() -> None:
    context = build_context()
    import math
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if value is pd.NaT:
            return None
        return value
    context = clean(context)
    claude = shutil.which("claude")
    if not claude:
        raise SystemExit("claude CLI not found - install Claude Code")
    previous_paths = sorted(REPORTS_DIR.glob('snapshot-*.json')) if REPORTS_DIR.exists() else []
    if previous_paths:
        previous = json.loads(previous_paths[-1].read_text(encoding='utf-8'))
        current_rows = {row['symbol']: row for row in context.get('cross_section', [])}
        previous_rows = {row['symbol']: row for row in previous.get('cross_section', [])}
        changes = []
        for symbol in sorted(current_rows.keys() & previous_rows.keys()):
            row = {'symbol': symbol}
            for key in ('funding_rate','oi_usd'):
                current_value, previous_value = current_rows[symbol].get(key), previous_rows[symbol].get(key)
                if isinstance(current_value, (int,float)) and isinstance(previous_value, (int,float)):
                    if key != 'oi_usd' or current_rows[symbol].get('oi_src') == previous_rows[symbol].get('oi_src'):
                        row[key + '_change'] = current_value - previous_value
            changes.append(row)
        context['since_previous_report'] = {'previous_generated_utc': previous.get('generated_utc'), 'changes': changes}
    prompt = (SYSTEM_PROMPT + "\n\nWrite the briefing from this data:\n\n"
              + json.dumps(context, default=str))
    result = subprocess.run(
        [claude, "-p", "--model", MODEL],
        input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=600,
    )
    if result.returncode != 0:
        raise SystemExit(f"claude failed ({result.returncode}): {result.stderr[:500]}")
    body = result.stdout.strip()
    if len(body) < 200:
        raise SystemExit(f"briefing suspiciously short ({len(body)} chars): {body[:200]}")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"briefing-{datetime.now(timezone.utc):%Y-%m-%d}.md"
    path.write_text(f"# Market briefing {datetime.now(timezone.utc):%Y-%m-%d}\n\n{body}\n",
                    encoding="utf-8")
    snapshot_path = REPORTS_DIR / f"snapshot-{datetime.now(timezone.utc):%Y-%m-%d}.json"
    snapshot_path.write_text(json.dumps(context, default=str, allow_nan=False, indent=2), encoding='utf-8')
    print(f"saved {path} ({len(body)} chars)")


if __name__ == "__main__":
    main()
