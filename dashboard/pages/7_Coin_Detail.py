"""One coin's observations, derived panels and source coverage."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from analytics import data_access as da
from analytics.liquidations import daily_liquidations
from dashboard import shared

st.set_page_config(page_title='Coin Detail', layout='wide')
st.title('Coin detail')
shared.render_sync_status()
snapshot = shared.market_snapshot()
table = snapshot['cross_section']
if table.empty:
    st.info('No coin analytics yet.')
    st.stop()
symbols = sorted(table.index)
symbol = st.selectbox('Coin', symbols, index=symbols.index('BTC') if 'BTC' in symbols else 0)
row = table.loc[symbol]
st.caption(f"Data status: {row['data_status']} · OI source: {row['oi_src']}")
ages = st.columns(3)
for column, metric, label in zip(ages, ('funding','oi','price'), ('Funding','Open interest','Daily close')):
    stamp = row[f'{metric}_observed_at']
    column.metric(f'{label} input age', 'Unavailable' if pd.isna(stamp) else f"{row[f'{metric}_age_h']:.1f}h")
    if pd.notna(stamp):
        column.caption(f'{stamp:%Y-%m-%d %H:%M UTC}')
if not row['eligible']:
    st.warning('This coin is excluded from current rankings. The charts below are historical observations.')
details = snapshot['coverage']
st.dataframe(details[details['symbol'] == symbol][['table','source','status','observed_at','age_h']].round({'age_h':1}), hide_index=True, use_container_width=True)
cutoff = shared.lookback_cutoff('coin_detail_lookback')


@st.cache_data(ttl=shared.CACHE_TTL_S)
def coin_candles(base: str) -> pd.DataFrame:
    frame = da.load_daily_closes()
    return frame[frame['symbol'] == base]


def chart(frame, value, title):
    if cutoff is not None:
        frame = frame[frame['ts'] >= cutoff]
    if frame.empty:
        st.info(f'{title}: no observations in this period.')
        return
    figure = go.Figure(go.Scatter(x=frame['ts'], y=frame[value], mode='lines', connectgaps=False))
    figure.update_layout(title=title, template='plotly_dark', height=300)
    st.plotly_chart(figure, use_container_width=True)


chart(coin_candles(symbol), 'close', f'{symbol} daily close (USD)')
funding = shared.funding_panels()['value']
if symbol in funding:
    chart((funding[symbol] * 3 * 365 * 100).rename('apr').reset_index(), 'apr', 'Funding (annualized %, normalized to 8h)')
oi = shared.oi_panels()['value']
if symbol in oi:
    chart(oi[symbol].rename('oi_usd').reset_index(), 'oi_usd', f"Open interest (USD, {row['oi_src']})")
liquidations = snapshot['liquidations']
if not liquidations.empty:
    coin = liquidations[liquidations['symbol'] == symbol].rename(columns={'day':'ts'})
    chart(coin, 'long_usd', 'Long liquidations (USD per completed or covered day)')
    chart(coin, 'short_usd', 'Short liquidations (USD per completed or covered day)')
st.caption('Funding, OI and price panels use completed UTC days. Filled analytical observations can differ from live feed timestamps; inspect the provenance and ages above.')
