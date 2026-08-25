import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import plotly.graph_objects as go
import streamlit as st

from dashboard import shared

st.set_page_config(page_title="Regime", layout="wide")
st.title("Composite market regime")

regime = shared.regime_history()
if regime.empty:
    st.info("No regime history yet - collect more data first.")
    st.stop()

figure = go.Figure()
figure.add_scatter(x=regime.index, y=regime["regime"], name="regime",
                   line={"color": "#22c55e", "width": 2})
figure.add_hrect(y0=1.5, y1=3, fillcolor="#ef4444", opacity=0.12, line_width=0)
figure.add_hrect(y0=-3, y1=-1.5, fillcolor="#22c55e", opacity=0.12, line_width=0)
figure.update_layout(title="Regime score (+hot / -washed out)", height=400, template="plotly_dark")
st.plotly_chart(figure, use_container_width=True)

figure = go.Figure()
for component, color in [("funding_z", "#f59e0b"), ("funding_pct", "#eab308"), ("oi_z", "#3b82f6"),
                         ("momentum_z", "#a855f7"), ("breadth", "#22c55e"), ("dvol_pct", "#ef4444")]:
    figure.add_scatter(x=regime.index, y=regime[component], name=component, line={"color": color, "width": 1})
figure.update_layout(title="Components", height=400, template="plotly_dark")
st.plotly_chart(figure, use_container_width=True)

st.dataframe(regime.tail(30).iloc[::-1].round(2), use_container_width=True)
