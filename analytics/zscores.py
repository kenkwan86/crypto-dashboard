"""Rolling z-scores for funding, open interest, and momentum, plus the
cross-sectional positioning table used by the dashboard and briefings.

Run standalone for a quick look: python -m analytics.zscores
"""

from __future__ import annotations

import pandas as pd

from analytics.data_access import (load_daily_closes, load_funding,
                                   load_open_interest_binance, load_open_interest_coinalyze)

WINDOWS_DAYS = {"z30": 30, "z90": 90, "z365": 365}
MIN_PERIODS_FRACTION = 0.5


def rolling_z(series: pd.Series, window: int) -> pd.Series:
    """Z-score of the last value vs a rolling window (time-based, daily index)."""
    mean = series.rolling(window, min_periods=int(window * MIN_PERIODS_FRACTION)).mean()
    std = series.rolling(window, min_periods=int(window * MIN_PERIODS_FRACTION)).std()
    std = std.where(std > 0)
    return (series - mean) / std


def daily_panel(df: pd.DataFrame, value: str, fill_days: int = 3) -> pd.DataFrame:
    """Completed UTC days only; bounded fill, sorted observations, known membership."""
    from analytics.universe import membership
    if df.empty:
        return pd.DataFrame(index=pd.DatetimeIndex([], tz='UTC', name='ts'))
    frame = df.copy().sort_values('ts')
    frame['ts'] = pd.to_datetime(frame['ts'], utc=True)
    frame = frame[frame['ts'] < pd.Timestamp.now(tz='UTC').floor('D')]
    if 'observed_at' in frame and value == 'close':
        # A day's closing price is known with the closed 23:00 candle even if
        # an earlier intraday candle is missing. Volume completeness is separate.
        frame.loc[pd.to_datetime(frame['observed_at'], utc=True).dt.hour != 23, value] = float('nan')
    frame['ts'] = frame['ts'].dt.floor('D')
    panel = frame.groupby(['ts','symbol'])[value].last().unstack().asfreq('D')
    if fill_days:
        panel = panel.ffill(limit=fill_days)
    mask, _ = membership(panel.index, panel.columns)
    return panel.where(mask)


def funding_zscores() -> dict[str, pd.DataFrame]:
    """Daily funding-rate panel and its rolling z-score panels."""
    panel = daily_panel(load_funding(), "rate")
    return {"value": panel} | {name: panel.apply(lambda s: rolling_z(s, days))
                               for name, days in WINDOWS_DAYS.items()}


def oi_zscores() -> dict[str, object]:
    """Freeze each coin's source at the first 90 observed daily values.

    No selection using future depth; no splice between sources. Binance wins
    only if it reaches the threshold first (or on the same day).
    """
    raw = {'binance': daily_panel(load_open_interest_binance(), 'oi_usd', fill_days=0),
           'coinalyze_agg': daily_panel(load_open_interest_coinalyze(), 'oi_usd', fill_days=0)}
    series, source = {}, {}
    symbols = sorted(set(raw['binance'].columns) | set(raw['coinalyze_agg'].columns))
    for symbol in symbols:
        candidates = []
        for priority, (name, panel) in enumerate(raw.items()):
            if symbol in panel:
                observed = panel[symbol].dropna()
                if len(observed) >= 90:
                    candidates.append((observed.index[89], priority, name))
        if not candidates:
            continue
        start, _, name = min(candidates)
        values = raw[name][symbol].loc[start:].ffill(limit=3)
        series[symbol], source[symbol] = values, name
    continuous = pd.DataFrame(series)
    change_7d = continuous.pct_change(7, fill_method=None)
    return {'value': continuous, 'change_7d': change_7d, 'source': source} | {
        name: change_7d.apply(lambda series: rolling_z(series, days)) for name, days in WINDOWS_DAYS.items()
    }


def momentum_zscores() -> dict[str, pd.DataFrame]:
    """Daily close panel, 30d return, and z-scores of the 30d return."""
    panel = daily_panel(load_daily_closes(), "close", fill_days=0)
    returns_30d = panel.pct_change(30, fill_method=None)
    return {"value": panel, "return_30d": returns_30d} | {
        name: returns_30d.apply(lambda s: rolling_z(s, days)) for name, days in WINDOWS_DAYS.items()
    }


def cross_sectional_table() -> pd.DataFrame:
    """Latest per-coin snapshot: funding, OI, momentum with z-scores and ranks."""
    funding = funding_zscores()
    oi = oi_zscores()
    momentum = momentum_zscores()

    def latest(panel: pd.DataFrame) -> pd.Series:
        # daily_panel already ffills up to 3 days; a second ffill here would let a
        # 6-day-old value masquerade as current.
        return panel.iloc[-1] if len(panel) else pd.Series(dtype=float)

    table = pd.DataFrame({
        "funding_rate": latest(funding["value"]),
        "funding_z90": latest(funding["z90"]),
        "oi_usd": latest(oi["value"]),
        "oi_src": pd.Series(oi.get("source", {}), dtype=object),
        "oi_change_7d": latest(oi["change_7d"]),
        "oi_z90": latest(oi["z90"]),
        "return_30d": latest(momentum["return_30d"]),
        "momentum_z90": latest(momentum["z90"]),
    })
    table.index.name = "symbol"
    table["funding_rank"] = table["funding_z90"].rank(ascending=False)
    table["oi_rank"] = table["oi_z90"].rank(ascending=False)
    return table.sort_values("oi_usd", ascending=False)


if __name__ == "__main__":
    table = cross_sectional_table()
    print(table.head(20).to_string(float_format=lambda x: f"{x:.4g}"))
    print(f"\n{len(table)} symbols")
