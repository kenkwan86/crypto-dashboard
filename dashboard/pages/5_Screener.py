import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import plotly.graph_objects as go
import streamlit as st

from analytics import crowding
from dashboard import shared

st.set_page_config(page_title="Screener", layout="wide")
st.title("Cross-sectional screener")

table = shared.cross_sectional_table()
if table.empty:
    st.info("No data yet.")
    st.stop()

shared.render_freshness()

display = table.copy()
display["funding_apr_%"] = display["funding_rate"] * 3 * 365 * 100
display["oi_usd_M"] = display["oi_usd"] / 1e6
display["oi_change_7d_%"] = display["oi_change_7d"] * 100
display["return_30d_%"] = display["return_30d"] * 100
display["crowding"] = crowding.label_table(table)
columns = ["crowding", "oi_usd_M", "oi_src", "funding_apr_%", "funding_z90", "oi_change_7d_%",
           "oi_z90", "return_30d_%", "momentum_z90"]
text_columns = {"crowding", "oi_src"}
numeric_columns = [c for c in columns if c not in text_columns]


def crowding_style(value: object) -> str:
    color = crowding.LABEL_COLORS.get(value)
    return f"background-color: {color}; color: white" if color else ""


st.dataframe(
    display[columns].style
    .background_gradient(subset=["funding_z90", "oi_z90", "momentum_z90"], cmap="RdYlGn_r", vmin=-3, vmax=3)
    .map(crowding_style, subset=["crowding"])
    .format("{:.2f}", subset=numeric_columns),
    use_container_width=True, height=800,
)
st.caption("z90 = z-score vs trailing 90 days. funding_apr annualises the per-8h rate (funding is normalised to a per-8h rate before annualising, 3x daily).")

st.subheader("Crowding quadrant")
quadrant = display[["funding_z90", "oi_z90", "crowding"]].dropna(subset=["funding_z90", "oi_z90"])
if quadrant.empty:
    st.info("No coin has both a funding and an OI z-score yet.")
else:
    figure = go.Figure()
    for label in crowding.LABELS:
        points = quadrant[quadrant["crowding"] == label]
        if points.empty:
            continue
        figure.add_scatter(
            x=points["funding_z90"], y=points["oi_z90"], mode="markers+text",
            text=points.index, textposition="top center", textfont={"size": 9},
            name=label, marker={"size": 10, "color": crowding.LABEL_COLORS[label]},
        )
    for x in (crowding.FUNDING_Z_HI, -crowding.FUNDING_Z_HI):
        figure.add_vline(x=x, line_dash="dot", line_color="#4b5563")
    for y in (crowding.OI_Z_HI, -crowding.OI_Z_HI):
        figure.add_hline(y=y, line_dash="dot", line_color="#4b5563")
    figure.update_layout(
        height=600, template="plotly_dark",
        xaxis_title="funding z90 (longs paying ->)", yaxis_title="7d OI-change z90 (leverage building ->)",
        legend={"orientation": "h", "y": -0.15},
    )
    st.plotly_chart(figure, use_container_width=True)
    st.caption(
        f"Labels fire at |funding z90| >= {crowding.FUNDING_Z_HI} and |OI z90| >= {crowding.OI_Z_HI}, "
        f"chosen on 2021-2026 so each label runs about twice a coin-month rather than daily. "
        "'apathy' is the residual bucket - it also holds the un-named corner (funding high, OI falling). "
        "Falsifier (python -m analytics.crowding): over 2021-2026 'crowded long' does NOT separate on "
        "median 7d forward return (-0.56% vs -0.83% for apathy); treat the quadrant as a positioning "
        "description, not a return forecast."
    )
