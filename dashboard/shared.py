"""Cached data loaders shared by all dashboard pages."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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


SYNC_STATUS_PATH = Path(__file__).resolve().parent.parent / "logs" / "sync-status.json"


def render_sync_status() -> None:
    """Show an error when the hourly git sync is failing or overdue."""
    from collectors.run_status import sync_warning

    message = sync_warning(SYNC_STATUS_PATH, datetime.now(timezone.utc))
    if message:
        st.error(message)


def render_freshness() -> None:
    render_sync_status()
    snapshot = market_snapshot()
    health = snapshot['health']
    healthy = sum(row['healthy'] for row in health.values())
    expected = sum(row['expected'] for row in health.values())
    st.caption(f"Data checked {snapshot['generated_at']:%Y-%m-%d %H:%M UTC} · {healthy}/{expected} expected coin/source feeds fresh")
    unhealthy = [name for name, info in health.items() if info['status'] != 'healthy']
    if unhealthy:
        st.warning('Coverage needs attention: ' + ', '.join(unhealthy) + '. Current rankings exclude unusable inputs.')
    with st.expander('Inspect data age, coverage and sources'):
        details = snapshot['coverage'].copy()
        st.dataframe(details[['table','symbol','source','status','observed_at','age_h','duplicate_rows']], hide_index=True, use_container_width=True)
        st.caption('Inactive means outside the current universe. Duplicate rows include identical copies; legacy timestamp precision is not recoverable.')
    for name, reason in snapshot['gaps'].items():
        st.info(f'{name}: {reason}')


@st.cache_data(ttl=CACHE_TTL_S)
def cross_sectional_table() -> pd.DataFrame:
    return market_snapshot()['cross_section']


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
def regime_forward_returns() -> tuple[pd.DataFrame, dict]:
    """Regime bucket table plus the current reading (analytics.regime_returns)."""
    from analytics.regime_returns import (bucket_table, current_reading,
                                          forward_return_frame)

    frame = forward_return_frame()
    table = bucket_table(frame)
    return table, current_reading(frame, table)


@st.cache_data(ttl=CACHE_TTL_S)
def funding_basis() -> pd.DataFrame:
    """Current cross-venue funding spreads (analytics.funding_basis)."""
    from analytics.funding_basis import current_basis

    return current_basis()


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


@st.cache_data(ttl=CACHE_TTL_S)
def market_snapshot() -> dict:
    from analytics.snapshot import build_snapshot
    return build_snapshot()
