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
