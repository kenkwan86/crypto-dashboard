"""Cached data loaders shared by all dashboard pages."""

from __future__ import annotations

import pandas as pd
import streamlit as st

CACHE_TTL_S = 900


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
