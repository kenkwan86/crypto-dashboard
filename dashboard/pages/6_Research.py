import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import streamlit as st
from dashboard import shared
st.set_page_config(page_title='Research', layout='wide')
st.title('Signal research')
shared.render_sync_status()
st.caption('Historical diagnostics. Signal definitions use prior observations; historical source revisions can still change results.')
st.warning('Universe membership before recorded snapshots is unknown. Legacy backfills lack availability timestamps. These diagnostics are not a fully point-in-time strategy backtest and do not establish a sizing rule.')
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
    st.caption("Buckets use expanding prior-history quintile boundaries after a 365-day warmup. "
               "1/5 = coldest, 5/5 = hottest. avg_coins is the average number of coins "
               "contributing to the universe average on those dates - early history has severe "
               "survivorship bias. Source: analytics/regime_returns.py.")
st.caption('Daily returns require complete candles at both endpoints. Overlapping return windows and market-wide events are not independent observations.')
