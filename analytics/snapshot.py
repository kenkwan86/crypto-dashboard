"""Shared, quality-gated facts for the dashboard and briefing.

No model calls and no writes. Historical charts remain available separately;
current assessments require usable observations and explicit timestamps.
"""
from __future__ import annotations

import pandas as pd

from analytics import data_access as da
from analytics.health import coverage_details, summarize
from analytics.universe import current_universe


def change_at(panel: pd.DataFrame, days: int) -> pd.Series:
    if panel.empty:
        return pd.Series(dtype=float)
    previous = panel.index[-1] - pd.Timedelta(days=days)
    return panel.iloc[-1] - panel.loc[previous] if previous in panel.index else pd.Series(index=panel.columns, dtype=float)


def annotate_cross_section(table: pd.DataFrame, details: pd.DataFrame,
                           now: pd.Timestamp) -> pd.DataFrame:
    """Match provenance to the completed-day metrics, not the table's newest row."""
    table = table.copy()
    universe = current_universe()
    active = set(universe['base'])
    cutoff = now.floor('D')
    funding = da.query(f"""SELECT symbol, max(ts) AS ts
        FROM ({da.deduped_sql('funding')}) WHERE ts < TIMESTAMPTZ '{cutoff.isoformat()}'
        AND {da.binance_funding_filter()} GROUP BY symbol""").set_index('symbol')
    oi = da.query(f"""SELECT symbol, exchange, max(ts) AS ts
        FROM ({da.deduped_sql('open_interest')}) WHERE ts < TIMESTAMPTZ '{cutoff.isoformat()}'
        AND oi_usd > 0 GROUP BY symbol, exchange""")
    closes = da.load_daily_closes()
    closes = closes[(closes['ts'] < cutoff) & (pd.to_datetime(closes['observed_at'], utc=True).dt.hour == 23)]
    price_times = closes.groupby('symbol')['observed_at'].max()
    table['funding_observed_at'] = pd.to_datetime(funding['ts'].reindex(table.index), utc=True)
    table['price_observed_at'] = pd.to_datetime(price_times.reindex(table.index), utc=True)
    source_times = oi.set_index(['symbol','exchange'])['ts']
    table['oi_observed_at'] = pd.to_datetime([
        source_times.get((symbol, row['oi_src']), pd.NaT) for symbol, row in table.iterrows()], utc=True)
    table['data_status'] = 'healthy'
    # Completed-day metrics are fresh when observed inside the latest completed
    # UTC day (not before cutoff - 1 day, not in the future). `*_age_h` stays the
    # actual age for display only.
    latest_completed_start = cutoff - pd.Timedelta(days=1)
    for metric in ('funding','oi','price'):
        observed = table[f'{metric}_observed_at']
        table[f'{metric}_age_h'] = (now - observed).dt.total_seconds() / 3600
        table.loc[observed.lt(latest_completed_start) | observed.gt(now), 'data_status'] = 'stale'
        table.loc[observed.isna(), 'data_status'] = 'missing'
    # Feed freshness also matters: an old completed daily value must not conceal
    # a collector that stopped this morning. OI uses the coin's selected source.
    for symbol, row in table.iterrows():
        relevant = details[(details['symbol'] == symbol) & details['expected'] & (
            ((details['table'] == 'funding') & (details['source'] == 'binance')) |
            (details['table'] == 'ohlcv') |
            ((details['table'] == 'open_interest') & (details['source'] == row['oi_src'])))]
        if relevant.empty or not relevant['status'].eq('healthy').all():
            table.loc[symbol, 'data_status'] = 'feed incomplete'
    required = ['funding_rate','funding_z90','oi_usd','oi_z90','return_30d']
    table.loc[table[required].isna().any(axis=1), 'data_status'] = 'insufficient history'
    table.loc[~table.index.isin(active), 'data_status'] = 'inactive'
    table['eligible'] = table['data_status'].eq('healthy')
    return table


def build_snapshot(now: pd.Timestamp | None = None) -> dict:
    with da.query_cache():
        return _build_snapshot(now)


def _build_snapshot(now: pd.Timestamp | None = None) -> dict:
    from analytics.zscores import cross_sectional_table, funding_zscores, oi_zscores
    from analytics.regime import compute_regime
    from analytics.options_metrics import latest_term_structure
    from analytics.liquidations import daily_liquidations

    now = pd.Timestamp.now(tz='UTC') if now is None else now
    details = coverage_details(now)
    snapshot = {'generated_at': now, 'coverage': details, 'health': summarize(details), 'gaps': {}}
    factories = {'cross_section': cross_sectional_table, 'regime': compute_regime,
                 'dvol': da.load_dvol, 'term': latest_term_structure, 'liquidations': daily_liquidations}
    for name, factory in factories.items():
        try:
            snapshot[name] = factory()
        except (ValueError, KeyError, IndexError) as error:
            snapshot[name] = pd.DataFrame()
            snapshot['gaps'][name] = f'Unavailable ({type(error).__name__})'
    table = snapshot['cross_section']
    if not table.empty:
        table = annotate_cross_section(table, details, now)
        funding = funding_zscores()['value']
        oi = oi_zscores()['value']
        for days in (1,7):
            table[f'funding_change_{days}d'] = change_at(funding, days)
            if not oi.empty:
                previous = oi.index[-1] - pd.Timedelta(days=days)
                table[f'oi_return_{days}d'] = oi.iloc[-1] / oi.loc[previous] - 1 if previous in oi.index else float('nan')
        snapshot['cross_section'] = table
    return snapshot


def briefing_facts(snapshot: dict) -> dict:
    """Fail closed before the model sees stale or insufficiently covered numbers."""
    now = snapshot['generated_at']
    facts = {'generated_utc': now.isoformat(), 'data_quality': snapshot['health'],
             'gaps': dict(snapshot['gaps']), 'metric_period': 'last completed UTC day'}
    table = snapshot['cross_section']
    if not table.empty:
        facts['cross_section'] = table[table['eligible']].reset_index().to_dict('records')
        facts['excluded_coins'] = table.loc[~table['eligible'], ['data_status']].reset_index().to_dict('records')
    regime = snapshot['regime']
    dependencies = ['funding','open_interest','ohlcv','options_dvol']
    quality_ok = all(snapshot['health'][name]['status'] == 'healthy' for name in dependencies)
    if not regime.empty and quality_ok and regime.iloc[-1]['n_components'] == 6 and now - regime.index[-1] < pd.Timedelta(days=2):
        facts['regime'] = regime.tail(8).reset_index().to_dict('records')
    else:
        facts['gaps']['regime'] = 'Current regime assessment withheld: incomplete or stale inputs.'
    for key in ('dvol','term'):
        frame = snapshot[key]
        if frame.empty:
            facts['gaps'][key] = 'No usable observations.'
            continue
        fresh = frame[(frame['ts'] <= now) & (frame['ts'] >= now - pd.Timedelta(hours=24))]
        if key == 'term':
            fresh = fresh[fresh['timestamp_quality'] == 'observed']
        else:
            fresh = fresh.sort_values('ts').drop_duplicates('currency', keep='last')
        facts[key] = fresh.to_dict('records')
        absent = {'BTC','ETH'} - set(fresh['currency'])
        if absent:
            facts['gaps'][key] = 'Missing, stale or unknown observation time: ' + ', '.join(sorted(absent))
    liquidations = snapshot['liquidations']
    if not liquidations.empty and snapshot['health']['liquidations']['status'] == 'healthy':
        current = liquidations[liquidations['symbol'].isin(set(current_universe()['base']))]
        current = current[(current['day'] < now.floor('D')) & (current['day'] >= now.floor('D') - pd.Timedelta(days=14))]
        daily = current.groupby('day').agg(long_usd=('long_usd','sum'), short_usd=('short_usd','sum'), coins=('symbol','nunique'))
        facts['liquidations_history'] = daily.reset_index().to_dict('records')
        facts['liquidations_note'] = 'Completed daily totals; compare contributing-coin counts. No current intraday total is implied.'
    else:
        facts['gaps']['liquidations'] = 'Current liquidation assessment withheld.'
    return facts
