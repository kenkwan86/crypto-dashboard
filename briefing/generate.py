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
Plain English, no hedging boilerplate. State data gaps plainly if inputs are missing."""


def build_context() -> dict:
    from analytics.options_metrics import latest_term_structure
    from analytics.regime import compute_regime
    from analytics.zscores import cross_sectional_table
    from analytics.data_access import load_dvol, load_liquidations

    regime = compute_regime()
    table = cross_sectional_table()
    dvol = load_dvol()
    liquidations = load_liquidations()

    context: dict = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="minutes")}
    if not regime.empty:
        weekly = regime["regime"].iloc[-90:].resample("7D").last().round(2).dropna()
        context["regime_weekly_last_90d"] = {f"{ts:%Y-%m-%d}": v for ts, v in weekly.items()}
        context["regime_components_latest"] = regime.iloc[-1].round(2).to_dict()
    if not table.empty:
        context["cross_section"] = json.loads(
            table.round(4).reset_index().to_json(orient="records")
        )
    if not dvol.empty:
        btc = dvol[dvol["currency"] == "BTC"].set_index("ts")["close"]
        context["btc_dvol"] = {
            "latest": round(float(btc.iloc[-1]), 1),
            "percentile_1y": round(float((btc.iloc[-365 * 24:] < btc.iloc[-1]).mean()), 2),
        }
    term = latest_term_structure()
    if not term.empty:
        numeric = term.drop(columns=["ts"]).assign(expiry=term["expiry"].dt.strftime("%Y-%m-%d"))
        context["options_term_structure"] = json.loads(
            numeric.round(2).to_json(orient="records")
        )
    if not liquidations.empty:
        recent = liquidations[liquidations["ts"] > liquidations["ts"].max() - pd.Timedelta(days=14)]
        daily = recent.groupby(recent["ts"].dt.floor("D"))[["long_usd", "short_usd"]].sum()
        context["liquidations_daily_14d_usd"] = {
            str(day.date()): {"long": int(row["long_usd"]), "short": int(row["short_usd"])}
            for day, row in daily.iterrows()
        }
    return context


def main() -> None:
    context = build_context()
    claude = shutil.which("claude")
    if not claude:
        raise SystemExit("claude CLI not found - install Claude Code")
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
    print(f"saved {path} ({len(body)} chars)")


if __name__ == "__main__":
    main()
