import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import plotly.graph_objects as go
import streamlit as st

from dashboard import shared
import pandas as pd

st.set_page_config(page_title="Positioning", layout="wide")
st.title("Positioning - funding and open interest")

shared.render_freshness()

funding = shared.funding_panels()
oi = shared.oi_panels()

symbols = sorted(funding["value"].columns)
col_coin, col_lookback = st.columns([4, 1])
with col_coin:
    symbol = st.selectbox("Coin", symbols, index=symbols.index("BTC") if "BTC" in symbols else 0)
with col_lookback:
    cutoff = shared.lookback_cutoff()
funding = {name: shared.clip_index(panel, cutoff) for name, panel in funding.items()}
oi_source = oi.get("source", {})
oi = {name: shared.clip_index(panel, cutoff) for name, panel in oi.items()
      if isinstance(panel, pd.DataFrame)}

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
    figure.update_layout(title=f"{symbol} open interest ($M, source: {oi_source.get(symbol, 'n/a')})",
                         height=350, template="plotly_dark")
    st.plotly_chart(figure, use_container_width=True)

    figure = go.Figure()
    figure.add_scatter(x=oi["z90"].index, y=oi["z90"][symbol], name="OI change z90", line={"color": "#a855f7"})
    figure.add_hline(y=2, line_dash="dot", line_color="#ef4444")
    figure.add_hline(y=-2, line_dash="dot", line_color="#22c55e")
    figure.update_layout(title=f"{symbol} 7d OI-change z-score (90d)", height=300, template="plotly_dark")
    st.plotly_chart(figure, use_container_width=True)

st.subheader("Cross-venue funding basis")
st.caption("Binance vs Hyperliquid vs Bybit, never averaged. Each venue's rate is normalised to "
           "a per-8h footing (rate * 8 / interval_h) before subtracting, then annualised (3x daily). "
           "Only coins listed on all three venues. Positive spread = that row's first venue has the "
           "crowd paying. Every number on a row is read at one hour - the last hour the "
           "Binance/Hyperliquid spread exists - so the legs subtract to the spread.")

basis = shared.funding_basis()
if basis.empty:
    st.info("No overlapping three-venue funding rows yet.")
else:
    basis_columns = ["binance_apr_%", "bybit_apr_%", "hyperliquid_apr_%",
                     "binance_hyperliquid_apr_%", "binance_hyperliquid_z", "binance_hyperliquid_paying",
                     "binance_bybit_apr_%", "binance_bybit_z", "binance_bybit_paying", "age_h"]
    basis_numeric = [c for c in basis_columns if not c.endswith("_paying")]
    st.dataframe(
        basis[basis_columns].style
        .background_gradient(subset=["binance_hyperliquid_z", "binance_bybit_z"],
                             cmap="RdYlGn_r", vmin=-3, vmax=3)
        .format("{:.2f}", subset=basis_numeric),
        use_container_width=True, height=500,
    )
    stale_count = int(basis["stale"].sum())
    max_age = basis["age_h"].max()
    if stale_count:
        st.warning(f"{stale_count}/{len(basis)} rows read at a spread hour older than 6h "
                   f"(max {max_age:.1f}h). Hyperliquid is usually the laggard.")
    st.caption("z = z-score of the hourly spread vs its trailing 30 days. Cross-venue history only "
               "starts 2026-08-25, so the z-window is not yet full - run "
               "`python -m analytics.funding_basis` for the exact overlap.")
