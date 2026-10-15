"""Daily decision overview backed by the same snapshot as the briefing."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
import streamlit as st
from dashboard import shared
from analytics.snapshot import briefing_facts

st.set_page_config(page_title='Crypto Dashboard', layout='wide', page_icon='📊')
st.title('Crypto Market Dashboard')
st.caption('Positioning, leverage and volatility · daily context with live feed coverage')
shared.render_freshness()
snapshot = shared.market_snapshot()
facts = briefing_facts(snapshot)
regime = snapshot['regime']
table = snapshot['cross_section']

st.subheader('Market context')
if 'regime' in facts:
    latest = regime.iloc[-1]
    previous = regime.loc[regime.index[-1] - pd.Timedelta(days=7)] if regime.index[-1] - pd.Timedelta(days=7) in regime.index else None
    cols = st.columns(3)
    cols[0].metric('Regime score', f"{latest['regime']:.2f}", None if previous is None else f"{latest['regime']-previous['regime']:+.2f} over 7d")
    cols[1].metric('Components available', f"{int(latest['n_components'])}/6")
    cols[2].metric('Fresh coins with enough history', str(int(table['eligible'].sum())) if not table.empty else '0')
    st.caption(f'Completed UTC day: {regime.index[-1]:%Y-%m-%d}. Positive = crowded/hot; negative = washed out. Descriptive, not a return forecast.')
    components = latest.reindex(['funding_z','funding_pct','oi_z','momentum_z','breadth','dvol_pct']).astype(float)
    components = components.rename(index={'funding_z':'Funding deviation','funding_pct':'Funding level',
        'oi_z':'Leverage change','momentum_z':'Price momentum','breadth':'Market breadth','dvol_pct':'BTC volatility'})
    st.bar_chart(components.rename('component score'))
else:
    st.info(facts['gaps'].get('regime', 'No usable regime observations.'))
    if not regime.empty:
        with st.expander('Historical regime components'):
            st.dataframe(regime.tail(7), use_container_width=True)

st.subheader('What changed?')
st.caption('Changes between completed UTC days. Missing comparisons stay blank.')
if table.empty:
    st.info('No analytical snapshot is available yet.')
else:
    eligible = table[table['eligible']].copy()
    if eligible.empty:
        st.info('No coins currently pass coverage, freshness and history checks.')
    else:
        eligible['funding_24h_change_bp'] = eligible['funding_change_1d'] * 10000
        eligible['funding_7d_change_bp'] = eligible['funding_change_7d'] * 10000
        eligible['oi_24h_change_%'] = eligible.get('oi_return_1d', float('nan')) * 100
        eligible['oi_7d_change_%'] = eligible.get('oi_return_7d', float('nan')) * 100
        changes = eligible.sort_values('funding_24h_change_bp', key=lambda values: values.abs(), ascending=False).head(10)
        st.dataframe(changes[['funding_24h_change_bp','funding_7d_change_bp','oi_24h_change_%','oi_7d_change_%','oi_src']].round(2).rename(columns={
            'funding_24h_change_bp':'Funding 1d change (bp / 8h)', 'funding_7d_change_bp':'Funding 7d change (bp / 8h)',
            'oi_24h_change_%':'OI 1d change (%)','oi_7d_change_%':'OI 7d change (%)','oi_src':'OI source'}), use_container_width=True)
    st.subheader('Positioning worth investigating')
    st.caption('Largest absolute funding z-scores among usable coins. Open Coin Detail in the sidebar to inspect supporting observations.')
    if not eligible.empty:
        watch = eligible.sort_values('funding_z90', key=lambda values: values.abs(), ascending=False).head(10)
        watch['funding_apr_%'] = watch['funding_rate'] * 3 * 365 * 100
        st.dataframe(watch[['funding_apr_%','funding_z90','oi_z90','oi_src','funding_observed_at','oi_observed_at']].round({'funding_apr_%':2,'funding_z90':2,'oi_z90':2}).rename(columns={
            'funding_apr_%':'Funding APR (%)','funding_z90':'Funding z90','oi_z90':'OI change z90','oi_src':'OI source',
            'funding_observed_at':'Funding observed (UTC)','oi_observed_at':'OI observed (UTC)'}), use_container_width=True)
    with st.expander('Coins excluded from current rankings'):
        st.dataframe(table.loc[~table['eligible'], ['data_status','funding_age_h','oi_age_h','price_age_h']], use_container_width=True)

st.caption('Explore Positioning, Regime, Liquidations, Options, Screener, Research and Coin Detail in the sidebar.')
