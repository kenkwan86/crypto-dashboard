import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from dashboard import shared

st.set_page_config(page_title="Screener", layout="wide")
st.title("Cross-sectional screener")

table = shared.cross_sectional_table()
if table.empty:
    st.info("No data yet.")
    st.stop()

display = table.copy()
display["funding_apr_%"] = display["funding_rate"] * 3 * 365 * 100
display["oi_usd_M"] = display["oi_usd"] / 1e6
display["oi_change_7d_%"] = display["oi_change_7d"] * 100
display["return_30d_%"] = display["return_30d"] * 100
columns = ["oi_usd_M", "funding_apr_%", "funding_z90", "oi_change_7d_%", "oi_z90",
           "return_30d_%", "momentum_z90"]

st.dataframe(
    display[columns].style
    .background_gradient(subset=["funding_z90", "oi_z90", "momentum_z90"], cmap="RdYlGn_r", vmin=-3, vmax=3)
    .format("{:.2f}"),
    use_container_width=True, height=800,
)
st.caption("z90 = z-score vs trailing 90 days. funding_apr assumes 8h funding, 3x daily.")
