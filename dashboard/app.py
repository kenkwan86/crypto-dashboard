"""Crypto dashboard entry point. Run: streamlit run dashboard/app.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from dashboard import shared

st.set_page_config(page_title="Crypto Dashboard", layout="wide", page_icon="📊")

st.title("Crypto Market Dashboard")

shared.render_freshness()

regime = shared.regime_history()
table = shared.cross_sectional_table()

if not regime.empty:
    latest = regime.iloc[-1]
    week_ago = regime.iloc[-8] if len(regime) > 8 else latest
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Regime score", f"{latest['regime']:.2f}", f"{latest['regime'] - week_ago['regime']:+.2f} vs 7d")
    col2.metric("Median funding z90", f"{latest['funding_z']:.2f}")
    col3.metric("Median OI z90", f"{latest['oi_z']:.2f}")
    col4.metric("Breadth score", f"{latest['breadth']:.2f}")

    st.subheader("Forward returns by regime bucket")
    bucket_table, reading = shared.regime_forward_returns()
    if bucket_table.empty:
        st.info("Not enough regime history for forward returns yet.")
    else:
        st.markdown(f"**{reading['line']}**")
        show = [c for c in ["n_days", "avg_coins",
                            "btc_7d_med_%", "universe_7d_med_%",
                            "btc_30d_p25_%", "btc_30d_med_%", "btc_30d_p75_%", "btc_30d_n",
                            "universe_30d_p25_%", "universe_30d_med_%", "universe_30d_p75_%"]
                if c in bucket_table.columns]
        current_bucket = reading["bucket"]

        def highlight_current(row):
            hit = str(row.name) == current_bucket
            return ["background-color: #1e3a8a" if hit else "" for _ in row]

        st.dataframe(
            bucket_table[show].style.apply(highlight_current, axis=1).format("{:.2f}"),
            use_container_width=True,
        )
        if reading["flat"]:
            spread = bucket_table["btc_30d_med_%"].max() - bucket_table["btc_30d_med_%"].min()
            st.warning(f"Descriptive only: median BTC 30d forward returns are flat and "
                       f"non-monotonic across buckets (spread {spread:.1f} pp). "
                       "Do not size off this table.")
        st.caption("Buckets are quintiles of the composite regime score over the full 2021-2026 "
                   "history; 1/5 = coldest, 5/5 = hottest. avg_coins is the average number of coins "
                   "contributing to the universe average on those dates - early history has severe "
                   "survivorship bias. Source: analytics/regime_returns.py.")

st.subheader("Hottest positioning (funding z90)")
if not table.empty:
    hot = table.sort_values("funding_z90", ascending=False).head(10)
    cold = table.sort_values("funding_z90").head(10)
    col1, col2 = st.columns(2)
    col1.dataframe(hot[["funding_rate", "funding_z90", "oi_z90", "return_30d"]], use_container_width=True)
    col2.dataframe(cold[["funding_rate", "funding_z90", "oi_z90", "return_30d"]], use_container_width=True)
else:
    st.info("No data yet - run the collectors first.")

st.caption("Pages: Positioning, Regime, Liquidations, Options, Screener (see sidebar).")
