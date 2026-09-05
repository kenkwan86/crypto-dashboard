import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import shared
from analytics.liquidations import daily_liquidations
from analytics import flush


@st.cache_data(ttl=shared.CACHE_TTL_S)
def cached_flush_panel() -> pd.DataFrame:
    return flush.flush_panel()


@st.cache_data(ttl=shared.CACHE_TTL_S)
def cached_flush_falsifier() -> dict:
    return flush.falsifier()

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

st.header("Liquidation-flush trigger (hourly)")
st.caption(
    f"Hourly liquidations divided by the same coin's open interest, z-scored over the full "
    f"hourly history available per coin (min {flush.MIN_HOURS}h); a flush is z >= {flush.FLUSH_Z}. "
    "Long flush = longs stopped out (forced selling); short flush = shorts squeezed (forced buying)."
)

panel = cached_flush_panel()
if panel.empty:
    st.info("No hourly liquidation rows yet - the hourly collector started 2026-08-24.")
else:
    st.caption(
        f"Hourly panel: {len(panel):,} coin-hours, {panel['symbol'].nunique()} coins, "
        f"{panel['ts'].min():%Y-%m-%d %H:%M} to {panel['ts'].max():%Y-%m-%d %H:%M} UTC. "
        "OI source per coin is shown in the tables; it is a single continuous source, "
        "never a sum of the Coinalyze aggregate and the live venues."
    )

    events = flush.flush_events(panel, hours=48)
    st.subheader(f"Flush events, last 48 hours ({len(events)})")
    if events.empty:
        st.write("No hour crossed the threshold in the last 48 hours.")
    else:
        table = events.copy()
        table["usd_m"] = table["usd"] / 1e6
        table["ratio_pct_of_oi"] = table["ratio"] * 100
        st.dataframe(
            table[["symbol", "ts", "side", "usd_m", "ratio_pct_of_oi", "z"]]
            .rename(columns={"symbol": "coin", "usd_m": "size ($M)",
                             "ratio_pct_of_oi": "% of OI"})
            .style.format({"size ($M)": "{:.2f}", "% of OI": "{:.2f}", "z": "{:.1f}"}),
            use_container_width=True, height=400,
        )

    tops = flush.top_flush_now(panel)
    st.subheader("Current top 10 by flush z")
    col_long, col_short = st.columns(2)
    for column, side, label in [(col_long, "long", "Long flush (forced selling)"),
                                (col_short, "short", "Short flush (forced buying)")]:
        with column:
            st.markdown(f"**{label}**")
            table = tops[side].copy()
            if table.empty:
                st.write("no fresh rows")
                continue
            table["usd_m"] = table["usd"] / 1e6
            table["ratio_pct_of_oi"] = table["ratio"] * 100
            st.dataframe(
                table[["symbol", "ts", "usd_m", "ratio_pct_of_oi", "z", "oi_src"]]
                .rename(columns={"symbol": "coin", "usd_m": "size ($M)",
                                 "ratio_pct_of_oi": "% of OI"})
                .style.format({"size ($M)": "{:.2f}", "% of OI": "{:.2f}", "z": "{:.1f}"}),
                use_container_width=True,
            )

    result = cached_flush_falsifier()
    base, long_side, short_side = result["base"], result["long"], result["short"]
    if base and long_side:
        st.subheader("Falsifier: do flush hours precede positive 24h returns?")
        st.warning(
            "PRELIMINARY - the hourly liquidation history is under two weeks and flush hours "
            "cluster inside the same market-wide cascades, so these events are nowhere near "
            "independent. Treat as a sanity check, not evidence."
        )
        falsifier_table = pd.DataFrame([
            {"sample": "all coin-hours (base rate)", "n": base["n"],
             "hit rate": base["hit_rate"], "mean 24h return": base["mean_return"]},
            {"sample": f"long flush (z >= {result['threshold']})", "n": long_side["n"],
             "hit rate": long_side["hit_rate"], "mean 24h return": long_side["mean_return"]},
            {"sample": f"short flush (z >= {result['threshold']})", "n": short_side["n"],
             "hit rate": short_side["hit_rate"], "mean 24h return": short_side["mean_return"]},
        ])
        st.dataframe(
            falsifier_table.style.format({"hit rate": "{:.1%}", "mean 24h return": "{:+.2%}"}),
            use_container_width=True,
        )
