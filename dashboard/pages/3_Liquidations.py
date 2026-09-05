import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import shared
from analytics.liquidations import daily_liquidations

st.set_page_config(page_title="Liquidations", layout="wide")
st.title("Liquidations (aggregated across exchanges)")

shared.render_freshness()

daily = daily_liquidations()
if daily.empty:
    st.info("No liquidation data yet. Set COINALYZE_API_KEY and run the collector/backfill.")
    st.stop()

cutoff = shared.lookback_cutoff()
if cutoff is not None:
    daily = daily[daily["day"] >= cutoff]
universe_daily = daily.groupby("day")[["long_usd", "short_usd"]].sum()

figure = go.Figure()
figure.add_bar(x=universe_daily.index, y=universe_daily["long_usd"] / 1e6, name="longs liquidated", marker_color="#ef4444")
figure.add_bar(x=universe_daily.index, y=-universe_daily["short_usd"] / 1e6, name="shorts liquidated", marker_color="#22c55e")
figure.update_layout(title="Universe-wide daily liquidations ($M)", barmode="relative",
                     height=400, template="plotly_dark")
st.plotly_chart(figure, use_container_width=True)

symbols = sorted(daily["symbol"].unique())
symbol = st.selectbox("Coin", symbols, index=symbols.index("BTC") if "BTC" in symbols else 0)
coin = (daily[daily["symbol"] == symbol]
        .set_index("day")[["long_usd", "short_usd"]])

figure = go.Figure()
figure.add_bar(x=coin.index, y=coin["long_usd"] / 1e6, name="longs", marker_color="#ef4444")
figure.add_bar(x=coin.index, y=-coin["short_usd"] / 1e6, name="shorts", marker_color="#22c55e")
figure.update_layout(title=f"{symbol} daily liquidations ($M)", barmode="relative",
                     height=350, template="plotly_dark")
st.plotly_chart(figure, use_container_width=True)
