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
    return (series - mean) / std


def daily_panel(df: pd.DataFrame, value: str) -> pd.DataFrame:
    """Pivot (symbol, ts, value) to a daily-indexed wide panel, ffilled max 3 days."""
    frame = df.copy()
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True).dt.floor("D")
    panel = frame.groupby(["ts", "symbol"])[value].last().unstack()
    panel = panel.asfreq("D").ffill(limit=3)
    return panel


def funding_zscores() -> dict[str, pd.DataFrame]:
    """Daily funding-rate panel and its rolling z-score panels."""
    panel = daily_panel(load_funding(), "rate")
    return {"value": panel} | {name: panel.apply(lambda s: rolling_z(s, days))
                               for name, days in WINDOWS_DAYS.items()}


def oi_zscores() -> dict[str, object]:
    """Daily OI panels from a single-source continuous series per coin (mixing
    sources across time fakes jumps at the seams): Binance history where it is
    deep enough (the backfilled top 10), Coinalyze aggregated otherwise. The
    displayed level, the 7d change and its z-scores all come from that one
    source, named per symbol in the "source" entry."""
    binance_panel = daily_panel(load_open_interest_binance(), "oi_usd")
    coinalyze_panel = daily_panel(load_open_interest_coinalyze(), "oi_usd")
    series, source = {}, {}
    for symbol in sorted(set(binance_panel.columns) | set(coinalyze_panel.columns)):
        binance = binance_panel.get(symbol)
        if binance is not None and binance.notna().sum() >= 90:
            series[symbol] = binance
            source[symbol] = "binance"
        elif symbol in coinalyze_panel:
            series[symbol] = coinalyze_panel[symbol]
            source[symbol] = "coinalyze_agg"
    continuous = pd.DataFrame(series)
    change_7d = continuous.pct_change(7)
    return {"value": continuous, "change_7d": change_7d, "source": source} | {
        name: change_7d.apply(lambda s: rolling_z(s, days)) for name, days in WINDOWS_DAYS.items()
    }


def momentum_zscores() -> dict[str, pd.DataFrame]:
    """Daily close panel, 30d return, and z-scores of the 30d return."""
    panel = daily_panel(load_daily_closes(), "close")
    returns_30d = panel.pct_change(30)
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
