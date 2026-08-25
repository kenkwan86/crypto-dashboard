"""Generate a market regime briefing with Claude.

Assembles the latest metrics into a compact JSON context, sends it to the
Claude API, and saves a markdown report to briefing/reports/.

Run: python -m briefing.generate   (requires ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import pandas as pd

MODEL = "claude-sonnet-5"
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
        context["regime_weekly_last_90d"] = (
            regime["regime"].iloc[-90:].resample("7D").last().round(2).dropna().to_dict()
        )
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
        context["options_term_structure"] = json.loads(
            term.round(2).drop(columns=["ts"]).assign(expiry=term["expiry"].astype(str)).to_json(orient="records")
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
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "Write the briefing from this data:\n\n"
                   + json.dumps(context, default=str)}],
    )
    body = "".join(block.text for block in response.content if block.type == "text")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"briefing-{datetime.now(timezone.utc):%Y-%m-%d}.md"
    path.write_text(f"# Market briefing {datetime.now(timezone.utc):%Y-%m-%d}\n\n{body}\n",
                    encoding="utf-8")
    print(f"saved {path} ({len(body)} chars)")


if __name__ == "__main__":
    main()
