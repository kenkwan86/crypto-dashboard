import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import shared
from analytics import vol


@st.cache_data(ttl=shared.CACHE_TTL_S)
def cached_vol_spread() -> pd.DataFrame:
    return vol.vol_spread()


st.set_page_config(page_title="Options", layout="wide")
st.title("BTC / ETH options - volatility and skew")

shared.render_freshness()

dvol = shared.dvol()
cutoff = shared.lookback_cutoff()
if not dvol.empty:
    dvol["ts"] = pd.to_datetime(dvol["ts"], utc=True)
    if cutoff is not None:
        dvol = dvol[dvol["ts"] >= cutoff]
    figure = go.Figure()
    for currency, color in [("BTC", "#f59e0b"), ("ETH", "#3b82f6")]:
        series = dvol[dvol["currency"] == currency]
        figure.add_scatter(x=series["ts"], y=series["close"], name=f"{currency} DVOL",
                           line={"color": color, "width": 1})
    figure.update_layout(title="Deribit DVOL (30d implied volatility index)", height=400,
                         template="plotly_dark")
    st.plotly_chart(figure, use_container_width=True)

st.header("Implied vs realised volatility")
st.caption("DVOL is 30-day implied vol; RV30 is 30-day realised vol from hourly candles. "
           f"Spread = DVOL - RV30 on the {vol.DEFAULT_ESTIMATOR} estimator; the percentile "
           "is a full-history rank, so a high percentile means options are historically rich.")

spread_history = cached_vol_spread()
if spread_history.empty:
    st.info("Not enough overlapping DVOL / OHLCV history yet.")
else:
    latest_vol = spread_history.groupby("currency", as_index=False).last()
    for _, row in latest_vol.iterrows():
        st.subheader(row["currency"])
        cols = st.columns(5)
        cols[0].metric("DVOL (implied)", f"{row['dvol']:.1f}")
        cols[1].metric("RV30 close-to-close", f"{row['rv30_close_to_close']:.1f}")
        cols[2].metric("RV30 Parkinson", f"{row['rv30_parkinson']:.1f}")
        cols[3].metric("Spread (DVOL - RV30)", f"{row['spread']:+.1f}")
        cols[4].metric("Spread percentile", f"{row['spread_pct']:.0f}")
        st.write(f"**{vol.reading(row['spread_pct'])}**")

    window_start = spread_history["ts"].max() - pd.Timedelta(days=180)
    recent_vol = spread_history[spread_history["ts"] >= window_start]
    figure = go.Figure()
    for currency, color in [("BTC", "#f59e0b"), ("ETH", "#3b82f6")]:
        series = recent_vol[recent_vol["currency"] == currency]
        if series.empty:
            continue
        figure.add_scatter(x=series["ts"], y=series["dvol"], name=f"{currency} DVOL",
                           line={"color": color, "width": 1.5})
        figure.add_scatter(x=series["ts"], y=series["rv30_close_to_close"], name=f"{currency} RV30",
                           line={"color": color, "width": 1.5, "dash": "dot"})
    figure.update_layout(title="DVOL vs RV30, last 180 days (dotted = realised)",
                         yaxis_title="annualised vol (%)", height=420, template="plotly_dark")
    st.plotly_chart(figure, use_container_width=True)

term = shared.options_term_structure()
if term.empty:
    st.info("No chain snapshots yet - the collector takes one daily at 00 UTC.")
    st.stop()

latest_ts = term["ts"].max()
latest = term[term["ts"] == latest_ts]
st.subheader(f"Term structure and 25-delta risk reversal ({latest_ts:%Y-%m-%d} snapshot)")

col1, col2 = st.columns(2)
with col1:
    figure = go.Figure()
    for currency, color in [("BTC", "#f59e0b"), ("ETH", "#3b82f6")]:
        series = latest[latest["currency"] == currency]
        figure.add_scatter(x=series["days_to_expiry"], y=series["atm_iv"], name=f"{currency} ATM IV",
                           mode="lines+markers", line={"color": color})
    figure.update_layout(title="ATM IV term structure", xaxis_title="days to expiry",
                         height=380, template="plotly_dark")
    st.plotly_chart(figure, use_container_width=True)
with col2:
    figure = go.Figure()
    for currency, color in [("BTC", "#f59e0b"), ("ETH", "#3b82f6")]:
        series = latest[latest["currency"] == currency]
        figure.add_scatter(x=series["days_to_expiry"], y=series["rr25"], name=f"{currency} RR25",
                           mode="lines+markers", line={"color": color})
    figure.add_hline(y=0, line_dash="dot", line_color="#737373")
    figure.update_layout(title="25-delta risk reversal (call IV - put IV)", xaxis_title="days to expiry",
                         height=380, template="plotly_dark")
    st.plotly_chart(figure, use_container_width=True)

# Skew history: front-month (21-45 dte) RR25 over time, once snapshots accumulate.
front = term[(term["days_to_expiry"] >= 21) & (term["days_to_expiry"] <= 45)]
if front["ts"].nunique() > 1:
    history = front.groupby(["ts", "currency"])["rr25"].mean().unstack()
    figure = go.Figure()
    for currency, color in [("BTC", "#f59e0b"), ("ETH", "#3b82f6")]:
        if currency in history:
            figure.add_scatter(x=history.index, y=history[currency], name=f"{currency} RR25 ~1m",
                               line={"color": color})
    figure.update_layout(title="Front-month skew history", height=350, template="plotly_dark")
    st.plotly_chart(figure, use_container_width=True)
