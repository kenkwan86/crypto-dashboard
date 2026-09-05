"""Cached data loaders shared by all dashboard pages."""

from __future__ import annotations

import pandas as pd
import streamlit as st

CACHE_TTL_S = 900

LOOKBACKS = {"3m": 91, "1y": 365, "2y": 730, "All": None}


def lookback_cutoff(key: str = "lookback") -> pd.Timestamp | None:
    """Render the lookback selector (default 1y) and return the cutoff ts."""
    choice = st.selectbox("Lookback", list(LOOKBACKS), index=1, key=key)
    days = LOOKBACKS[choice]
    return None if days is None else pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)


def clip_index(frame: pd.DataFrame, cutoff: pd.Timestamp | None) -> pd.DataFrame:
    return frame if cutoff is None else frame[frame.index >= cutoff]


# Hours of age after which a table is flagged with st.error on the dashboard.
STALE_ERROR_HOURS = {"funding": 3, "open_interest": 3, "liquidations": 3,
                     "options_dvol": 30, "options_chain": 30}
TABLES = ("ohlcv", "funding", "open_interest", "liquidations", "options_dvol", "options_chain")


@st.cache_data(ttl=CACHE_TTL_S)
def data_freshness() -> dict[str, dict]:
    """Max ts per table straight from the parquet globs, plus its age in hours."""
    import pandas as pd

    from analytics.data_access import query, table_exists, table_path

    now = pd.Timestamp.now(tz="UTC")
    out: dict[str, dict] = {}
    for table in TABLES:
        if not table_exists(table):
            out[table] = {"max_ts": None, "age_hours": None}
            continue
        max_ts = query(f"SELECT max(ts) AS max_ts FROM read_parquet('{table_path(table)}', union_by_name=true)")["max_ts"].iloc[0]
        if max_ts is None or pd.isna(max_ts):
            out[table] = {"max_ts": None, "age_hours": None}
            continue
        max_ts = pd.Timestamp(max_ts)
        out[table] = {"max_ts": str(max_ts),
                      "age_hours": round((now - max_ts).total_seconds() / 3600, 1)}
    return out


def render_freshness() -> None:
    """Caption with every table's max ts and age; st.error once a table is stale."""
    lines, errors = [], []
    for table, info in data_freshness().items():
        if info["age_hours"] is None:
            lines.append(f"{table}: no data")
            continue
        lines.append(f"{table} {info['max_ts']} ({info['age_hours']}h old)")
        limit = STALE_ERROR_HOURS.get(table)
        if limit is not None and info["age_hours"] > limit:
            errors.append(f"{table} data is {info['age_hours']}h old (> {limit}h) - shown numbers may be stale")
    st.caption("Data as of: " + " | ".join(lines))
    for error in errors:
        st.error(error)


@st.cache_data(ttl=CACHE_TTL_S)
def cross_sectional_table() -> pd.DataFrame:
    from analytics.zscores import cross_sectional_table

    return cross_sectional_table()


@st.cache_data(ttl=CACHE_TTL_S)
def funding_panels() -> dict[str, pd.DataFrame]:
    from analytics.zscores import funding_zscores

    return funding_zscores()


@st.cache_data(ttl=CACHE_TTL_S)
def oi_panels() -> dict[str, pd.DataFrame]:
    from analytics.zscores import oi_zscores

    return oi_zscores()


@st.cache_data(ttl=CACHE_TTL_S)
def regime_history() -> pd.DataFrame:
    from analytics.regime import compute_regime

    return compute_regime()


@st.cache_data(ttl=CACHE_TTL_S)
def liquidations() -> pd.DataFrame:
    from analytics.data_access import load_liquidations

    return load_liquidations()


@st.cache_data(ttl=CACHE_TTL_S)
def dvol() -> pd.DataFrame:
    from analytics.data_access import load_dvol

    return load_dvol()


@st.cache_data(ttl=CACHE_TTL_S)
def options_term_structure() -> pd.DataFrame:
    from analytics.options_metrics import chain_metrics

    return chain_metrics()
