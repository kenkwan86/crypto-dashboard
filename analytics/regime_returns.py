"""Descriptive forward returns using prior-history regime quintile boundaries.
The first 365 valid scores form a warmup. Prices require actual daily closing
candles at both endpoints. Unknown historical universe membership and legacy
availability times remain explicit limitations, not inferred history.
"""
from __future__ import annotations

import pandas as pd

from analytics.data_access import load_daily_closes
from analytics.regime import compute_regime
from analytics.zscores import daily_panel, oi_zscores

N_BUCKETS = 5
HORIZONS = (7, 30)
# A bucket's numbers are noise below this many observations; flagged, not dropped.
MIN_OBS_PER_BUCKET = 30
# Below this many contributing coins the "universe" average is a handful of
# survivors, not a market. Reported per bucket so the reader can discount it.
THIN_UNIVERSE_COINS = 10


def past_only_buckets(scores: pd.Series, min_history: int = 365) -> pd.Series:
    """Classify against prior observations only; ties deterministically go colder."""
    values = scores.sort_index()
    cuts = pd.DataFrame({q: values.expanding(min_periods=min_history).quantile(q).shift(1)
                         for q in (0.2,0.4,0.6,0.8)})
    bucket = 1 + cuts.lt(values, axis=0).sum(axis=1)
    result = bucket.map(lambda value: f'{value}/{N_BUCKETS}').astype('string')
    return result.where(cuts.notna().all(axis=1) & values.notna()).reindex(scores.index)


def forward_return_frame() -> pd.DataFrame:
    """Per-date: regime score, bucket, contributing coin count, forward returns."""
    regime = compute_regime()
    closes = daily_panel(load_daily_closes(), "close", fill_days=0)

    frame = pd.DataFrame(index=regime.index)
    frame["regime"] = regime["regime"]
    frame["n_components"] = regime["n_components"]
    frame["universe_recorded"] = regime.get("universe_recorded", False)

    btc = closes["BTC"].reindex(frame.index) if "BTC" in closes.columns else None
    for horizon in HORIZONS:
        forward = closes.shift(-horizon) / closes - 1
        forward = forward.reindex(frame.index)
        frame[f"n_coins_{horizon}d"] = forward.notna().sum(axis=1)
        frame[f"universe_fwd_{horizon}d"] = forward.mean(axis=1, skipna=True)
        if btc is not None:
            frame[f"btc_fwd_{horizon}d"] = (closes["BTC"].shift(-horizon) / closes["BTC"] - 1).reindex(frame.index)

    labels = [f"{i}/{N_BUCKETS}" for i in range(1, N_BUCKETS + 1)]
    frame['bucket'] = past_only_buckets(frame['regime'])
    return frame


def bucket_table(frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """Median / p25 / p75 forward returns per regime bucket, with counts."""
    if frame is None:
        frame = forward_return_frame()
    rows = []
    for bucket, group in frame.groupby("bucket", observed=True):
        row = {
            "bucket": bucket,
            "regime_lo": group["regime"].min(),
            "regime_hi": group["regime"].max(),
            "n_days": len(group),
            "avg_coins": group[f"n_coins_{HORIZONS[0]}d"].mean(),
            "avg_components": group["n_components"].mean(),
            "recorded_universe_days": int(group.get("universe_recorded", pd.Series(False, index=group.index)).sum()),
        }
        for horizon in HORIZONS:
            for who in ("btc", "universe"):
                column = f"{who}_fwd_{horizon}d"
                if column not in group:
                    continue
                series = group[column].dropna()
                prefix = f"{who}_{horizon}d"
                row[f"{prefix}_n"] = len(series)
                row[f"{prefix}_p25_%"] = series.quantile(0.25) * 100 if len(series) else float("nan")
                row[f"{prefix}_med_%"] = series.median() * 100 if len(series) else float("nan")
                row[f"{prefix}_p75_%"] = series.quantile(0.75) * 100 if len(series) else float("nan")
        rows.append(row)
    return pd.DataFrame(rows).set_index("bucket") if rows else pd.DataFrame()


def is_flat(table: pd.DataFrame, column: str = "btc_30d_med_%", spread_pct: float = 5.0) -> bool:
    """True when medians barely move across buckets - the table is then
    descriptive only, not a sizing input."""
    if column not in table:
        return True
    values = table[column].dropna()
    return len(values) < 2 or (values.max() - values.min()) < spread_pct


def current_reading(frame: pd.DataFrame | None = None,
                    table: pd.DataFrame | None = None) -> dict:
    """The one-line reading for the Home page."""
    if frame is None:
        frame = forward_return_frame()
    if table is None:
        table = bucket_table(frame)
    if frame.empty:
        return {"line": "No completed daily regime observations", "bucket": "unavailable", "flat": True}
    latest = frame.iloc[-1]
    bucket = latest["bucket"]
    row = table.loc[bucket] if pd.notna(bucket) and bucket in table.index else None
    reading = {
        "ts": frame.index[-1],
        "regime": float(latest["regime"]),
        "bucket": str(bucket),
        "flat": is_flat(table),
    }
    if row is not None:
        reading |= {
            "btc_30d_med_%": float(row.get("btc_30d_med_%", float("nan"))),
            "btc_30d_n": int(row.get("btc_30d_n", 0)),
            "universe_30d_med_%": float(row.get("universe_30d_med_%", float("nan"))),
            "btc_7d_med_%": float(row.get("btc_7d_med_%", float("nan"))),
        }
        reading["line"] = (
            f"regime bucket {bucket}: median BTC 30d fwd "
            f"{reading['btc_30d_med_%']:+.1f}%, n={reading['btc_30d_n']}"
        )
    else:
        reading["line"] = "regime bucket unavailable"
    return reading


def main() -> None:
    frame = forward_return_frame()
    table = bucket_table(frame)
    sources = oi_zscores()["source"]
    print(f"regime days: {len(frame)}  {frame.index.min().date()} .. {frame.index.max().date()}")
    print(f"OI source map: {len(sources)} coins, "
          f"{sum(1 for v in sources.values() if v == 'binance')} binance / "
          f"{sum(1 for v in sources.values() if v != 'binance')} coinalyze_agg")
    print(f"buckets: {N_BUCKETS} quintile boundaries fitted to prior history\n")

    counts = ["n_days", "avg_coins", "avg_components", "regime_lo", "regime_hi"]
    print("Regime buckets (score range, sample size)")
    print(table[counts].to_string(float_format=lambda x: f"{x:.2f}"))
    for horizon in HORIZONS:
        columns = [c for c in table.columns if f"_{horizon}d_" in c]
        print(f"\n{horizon}d forward returns by regime bucket")
        print(table[columns].to_string(float_format=lambda x: f"{x:.2f}"))

    thin = table[table["avg_coins"] < THIN_UNIVERSE_COINS]
    if len(thin):
        print(f"\nsurvivorship warning: buckets {list(thin.index)} average "
              f"< {THIN_UNIVERSE_COINS} contributing coins")
    small = table[table["btc_30d_n"] < MIN_OBS_PER_BUCKET] if "btc_30d_n" in table else table.iloc[:0]
    if len(small):
        print(f"small-sample warning: buckets {list(small.index)} have < {MIN_OBS_PER_BUCKET} obs")

    reading = current_reading(frame, table)
    print(f"\nFalsifier: BTC 30d medians flat across buckets? {reading['flat']}"
          f"  (spread {table['btc_30d_med_%'].max() - table['btc_30d_med_%'].min():.1f} pp)")
    print(f"Current: {reading['line']}")


if __name__ == "__main__":
    main()
