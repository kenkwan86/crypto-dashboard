"""Cross-venue funding basis - Binance vs Hyperliquid vs Bybit, never averaged.

`analytics.data_access.load_funding()` averages the venues together, which is
exactly what hides the trade: when Binance longs pay 40% APR and Hyperliquid
longs pay 5%, the mean says 22% and nothing about where the crowd sits.

Here every row keeps its venue. Each row's stored `rate` is per its own
`interval_h` hours (read from disk as-is - the column is being relabelled by
another process and this module never writes it), so it is normalised to a
common 8h footing with `rate * 8 / interval_h` before any subtraction. The
spreads are then

    binance_hyperliquid = binance_8h - hyperliquid_8h
    binance_bybit       = binance_8h - bybit_8h

Only coins listed on all three venues in `data/universe.parquet` are kept; a
spread against a venue that does not list the coin is not a spread.

A positive spread means the Binance crowd is the one paying (its longs pay more
per 8h than the other venue's); negative means the other venue's crowd is.

Run: python -m analytics.funding_basis
"""

from __future__ import annotations

import pandas as pd

from analytics.data_access import query, table_path
from collectors.common import DATA_DIR

VENUES = ("binance", "bybit", "hyperliquid")
SPREADS = {"binance_hyperliquid": ("binance", "hyperliquid"),
           "binance_bybit": ("binance", "bybit")}
Z_WINDOW_HOURS = 30 * 24        # 30-day z-score of the hourly spread
Z_MIN_PERIODS = 48              # below two days of overlap a z-score is noise
# Hourly rows go stale fast; a "current" spread older than this is not current.
MAX_SPREAD_AGE_HOURS = 6
# Rate * 3 * 365 turns a per-8h rate into an annualised percentage (3 settlements/day).
APR_FACTOR = 3 * 365 * 100
# Annualised-% band inside which the two venues count as quoting the same rate.
FLAT_APR_DEADBAND = 1.0


def three_venue_universe() -> list[str]:
    """Bases in data/universe.parquet that carry a symbol on all three venues."""
    path = str(DATA_DIR / "universe.parquet").replace("\\", "/")
    frame = query(f"""
        SELECT base FROM read_parquet('{path}')
        WHERE binance_symbol IS NOT NULL
          AND bybit_symbol IS NOT NULL
          AND hyperliquid_symbol IS NOT NULL
        ORDER BY rank
    """)
    return frame["base"].tolist()


def load_venue_funding(symbols: list[str] | None = None) -> pd.DataFrame:
    """Long frame (symbol, ts, exchange, rate_8h) - one row per venue, no averaging.

    `interval_h` is read from whatever is on disk; rows without it are dropped
    because they cannot be put on the 8h footing.
    """
    if symbols is None:
        symbols = three_venue_universe()
    if not symbols:
        return pd.DataFrame(columns=["symbol", "ts", "exchange", "rate_8h"])
    in_list = ", ".join(f"'{s}'" for s in symbols)
    venue_list = ", ".join(f"'{v}'" for v in VENUES)
    return query(f"""
        WITH deduped AS (
            SELECT symbol, ts, exchange, max(rate) AS rate, max(interval_h) AS interval_h
            FROM read_parquet('{table_path('funding')}', union_by_name=true)
            WHERE symbol IN ({in_list}) AND exchange IN ({venue_list})
            GROUP BY symbol, ts, exchange
        )
        SELECT symbol, ts, exchange, rate * 8.0 / interval_h AS rate_8h
        FROM deduped
        WHERE interval_h IS NOT NULL AND interval_h > 0
        ORDER BY symbol, ts, exchange
    """)


def spread_panels(symbols: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Hourly wide panels (ts x symbol) per venue and per spread, plus z-scores."""
    long = load_venue_funding(symbols)
    out: dict[str, pd.DataFrame] = {}
    if long.empty:
        return out
    long["ts"] = pd.to_datetime(long["ts"], utc=True).dt.floor("h")
    venues = {venue: long[long["exchange"] == venue]
              .groupby(["ts", "symbol"])["rate_8h"].last().unstack()
              for venue in VENUES}
    index = pd.DatetimeIndex(sorted(set().union(*[v.index for v in venues.values()])))
    columns = sorted(set().union(*[v.columns for v in venues.values()]))
    venues = {name: panel.reindex(index=index, columns=columns) for name, panel in venues.items()}
    out |= {f"venue_{name}": panel for name, panel in venues.items()}
    for name, (left, right) in SPREADS.items():
        spread = venues[left] - venues[right]
        out[name] = spread
        out[f"{name}_z"] = spread.apply(
            lambda s: (s - s.rolling(Z_WINDOW_HOURS, min_periods=Z_MIN_PERIODS).mean())
            / s.rolling(Z_WINDOW_HOURS, min_periods=Z_MIN_PERIODS).std())
    return out


def _last_valid_ts(panel: pd.DataFrame, symbol: str) -> pd.Timestamp | None:
    series = panel[symbol].dropna() if symbol in panel else pd.Series(dtype=float)
    return None if series.empty else series.index[-1]


def _at(panel: pd.DataFrame, symbol: str, ts: pd.Timestamp | None) -> float:
    if ts is None or symbol not in panel or ts not in panel.index:
        return float("nan")
    return float(panel.at[ts, symbol])


def current_basis(symbols: list[str] | None = None,
                  panels: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """One row per coin: latest spread (annualised), its 30d z-score, which
    venue's crowd is paying, and how stale the reading is.

    Every number on a row is read at ONE timestamp - the last hour at which the
    Binance/Hyperliquid spread exists. Hyperliquid is usually the laggard, and
    quoting each venue at its own newest hour would compare rates set hours
    apart and make the spread column disagree with its own legs.
    """
    if panels is None:
        panels = spread_panels(symbols)
    if not panels:
        return pd.DataFrame()
    now = pd.Timestamp.now(tz="UTC")
    rows = []
    for symbol in panels["binance_hyperliquid"].columns:
        as_of = _last_valid_ts(panels["binance_hyperliquid"], symbol)
        if as_of is None:
            as_of = _last_valid_ts(panels["binance_bybit"], symbol)
        row: dict = {"symbol": symbol, "ts": as_of}
        row["age_h"] = float("nan") if as_of is None else round((now - as_of).total_seconds() / 3600, 1)
        for venue in VENUES:
            row[f"{venue}_apr_%"] = _at(panels[f"venue_{venue}"], symbol, as_of) * APR_FACTOR
        for name, (left, right) in SPREADS.items():
            value = _at(panels[name], symbol, as_of)
            row[f"{name}_apr_%"] = value * APR_FACTOR
            row[f"{name}_z"] = _at(panels[f"{name}_z"], symbol, as_of)
            row[f"{name}_paying"] = _paying(value, left, right)
        rows.append(row)
    frame = pd.DataFrame(rows).set_index("symbol")
    frame["stale"] = frame["age_h"].isna() | (frame["age_h"] > MAX_SPREAD_AGE_HOURS)
    return frame.sort_values("binance_hyperliquid_apr_%", ascending=False)


def _paying(spread_8h: float, left: str, right: str) -> str:
    """Which venue's longs are paying. Inside the deadband the two venues are
    quoting the same rate and naming a winner would be false precision."""
    if pd.isna(spread_8h):
        return "-"
    if abs(spread_8h) * APR_FACTOR < FLAT_APR_DEADBAND:
        return "level"
    return f"{left if spread_8h > 0 else right} longs"


def coverage(panels: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """How much overlapping history each spread actually has - the z-scores are
    only as good as this."""
    if panels is None:
        panels = spread_panels()
    rows = []
    for name in SPREADS:
        panel = panels.get(name)
        if panel is None or panel.empty:
            rows.append({"spread": name, "hours": 0, "coins": 0, "first": None, "last": None})
            continue
        valid = panel.notna()
        rows.append({"spread": name,
                     "hours": int(valid.any(axis=1).sum()),
                     "coins": int(valid.any().sum()),
                     "first": panel.index[valid.any(axis=1)].min() if valid.any().any() else None,
                     "last": panel.index[valid.any(axis=1)].max() if valid.any().any() else None})
    return pd.DataFrame(rows).set_index("spread")


def main() -> None:
    symbols = three_venue_universe()
    print(f"three-venue universe: {len(symbols)} coins -> {', '.join(symbols[:15])}"
          f"{' ...' if len(symbols) > 15 else ''}\n")
    panels = spread_panels(symbols)
    if not panels:
        print("no funding rows for the three-venue universe")
        return
    print("Overlap coverage (z-scores need "
          f"{Z_MIN_PERIODS}h min, {Z_WINDOW_HOURS}h window)")
    print(coverage(panels).to_string())
    frame = current_basis(panels=panels)
    show = ["binance_apr_%", "bybit_apr_%", "hyperliquid_apr_%",
            "binance_hyperliquid_apr_%", "binance_hyperliquid_z", "binance_hyperliquid_paying",
            "binance_bybit_apr_%", "binance_bybit_z", "binance_bybit_paying", "age_h"]
    print(f"\nCurrent cross-venue funding basis ({len(frame)} coins, annualised %)")
    print(frame[show].to_string(float_format=lambda x: f"{x:.2f}"))
    stale = frame["stale"].sum()
    if stale:
        print(f"\nstale: {stale}/{len(frame)} coins read at a spread hour older than "
              f"{MAX_SPREAD_AGE_HOURS}h (max age {frame['age_h'].max():.1f}h) - the "
              f"Hyperliquid feed is usually the laggard")


if __name__ == "__main__":
    main()
