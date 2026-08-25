import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import shared

st.set_page_config(page_title="Liquidations", layout="wide")
st.title("Liquidations (aggregated across exchanges)")

liquidations = shared.liquidations()
if liquidations.empty:
    st.info("No liquidation data yet. Set COINALYZE_API_KEY and run the collector/backfill.")
    st.stop()

liquidations["ts"] = pd.to_datetime(liquidations["ts"], utc=True)
daily = (liquidations.assign(day=liquidations["ts"].dt.floor("D"))
         .groupby("day")[["long_usd", "short_usd"]].sum())

figure = go.Figure()
figure.add_bar(x=daily.index, y=daily["long_usd"] / 1e6, name="longs liquidated", marker_color="#ef4444")
figure.add_bar(x=daily.index, y=-daily["short_usd"] / 1e6, name="shorts liquidated", marker_color="#22c55e")
figure.update_layout(title="Universe-wide daily liquidations ($M)", barmode="relative",
                     height=400, template="plotly_dark")
st.plotly_chart(figure, use_container_width=True)

symbols = sorted(liquidations["symbol"].unique())
symbol = st.selectbox("Coin", symbols, index=symbols.index("BTC") if "BTC" in symbols else 0)
coin = (liquidations[liquidations["symbol"] == symbol]
        .assign(day=lambda d: d["ts"].dt.floor("D"))
        .groupby("day")[["long_usd", "short_usd"]].sum())

figure = go.Figure()
figure.add_bar(x=coin.index, y=coin["long_usd"] / 1e6, name="longs", marker_color="#ef4444")
figure.add_bar(x=coin.index, y=-coin["short_usd"] / 1e6, name="shorts", marker_color="#22c55e")
figure.update_layout(title=f"{symbol} daily liquidations ($M)", barmode="relative",
                     height=350, template="plotly_dark")
st.plotly_chart(figure, use_container_width=True)
