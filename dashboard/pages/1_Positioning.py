import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import plotly.graph_objects as go
import streamlit as st

from dashboard import shared

st.set_page_config(page_title="Positioning", layout="wide")
st.title("Positioning - funding and open interest")

funding = shared.funding_panels()
oi = shared.oi_panels()

symbols = sorted(funding["value"].columns)
col_coin, col_lookback = st.columns([4, 1])
with col_coin:
    symbol = st.selectbox("Coin", symbols, index=symbols.index("BTC") if "BTC" in symbols else 0)
with col_lookback:
    cutoff = shared.lookback_cutoff()
funding = {name: shared.clip_index(panel, cutoff) for name, panel in funding.items()}
oi = {name: shared.clip_index(panel, cutoff) for name, panel in oi.items()}

col1, col2 = st.columns(2)

with col1:
    figure = go.Figure()
    figure.add_scatter(x=funding["value"].index, y=funding["value"][symbol] * 100 * 3 * 365,
                       name="funding (annualized %)", line={"color": "#22c55e"})
    figure.update_layout(title=f"{symbol} funding rate (annualized %)", height=350, template="plotly_dark")
    st.plotly_chart(figure, use_container_width=True)

    figure = go.Figure()
    figure.add_scatter(x=funding["z90"].index, y=funding["z90"][symbol], name="z90", line={"color": "#f59e0b"})
    figure.add_hline(y=2, line_dash="dot", line_color="#ef4444")
    figure.add_hline(y=-2, line_dash="dot", line_color="#22c55e")
    figure.update_layout(title=f"{symbol} funding z-score (90d)", height=300, template="plotly_dark")
    st.plotly_chart(figure, use_container_width=True)

with col2:
    figure = go.Figure()
    figure.add_scatter(x=oi["value"].index, y=oi["value"][symbol] / 1e6, name="OI", line={"color": "#3b82f6"})
    figure.update_layout(title=f"{symbol} open interest ($M)", height=350, template="plotly_dark")
    st.plotly_chart(figure, use_container_width=True)

    figure = go.Figure()
    figure.add_scatter(x=oi["z90"].index, y=oi["z90"][symbol], name="OI change z90", line={"color": "#a855f7"})
    figure.add_hline(y=2, line_dash="dot", line_color="#ef4444")
    figure.add_hline(y=-2, line_dash="dot", line_color="#22c55e")
    figure.update_layout(title=f"{symbol} 7d OI-change z-score (90d)", height=300, template="plotly_dark")
    st.plotly_chart(figure, use_container_width=True)
