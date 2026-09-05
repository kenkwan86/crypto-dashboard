"""Crowding quadrant per coin: funding z90 x OI-change z90.

Each coin-day gets one of four labels from the two z-scores that
`analytics/zscores.py` already computes side by side:

  crowded long        funding z high  + OI-change z high   longs paying up while leverage builds
  short-squeeze fuel  funding z low   + OI-change z high   shorts paying up while leverage builds
  capitulation        funding z low   + OI-change z low    shorts paying up while leverage bleeds out
  apathy              everything else                      no crowd worth trading against

"apathy" is the residual bucket, so it also swallows the un-named fourth
corner (funding high, OI falling - longs quietly unwinding). That corner is
rare and its forward returns look like the residual, so it is not split out.

Thresholds were chosen from the 2021-2026 history so a label fires a couple of
times a month per coin rather than daily: at 0.75 / 0.50 the three active
labels cover ~14% of coin-days and start ~2.1 distinct episodes per coin-month
(see `frequency_table()` / `python -m analytics.crowding`).

Run: python -m analytics.crowding
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.zscores import funding_zscores, momentum_zscores, oi_zscores

# Cutoffs on the 90d z-scores. Tuned on 2021-2026 (see module docstring):
# tighter and the labels almost never fire, looser and they are on most days.
FUNDING_Z_HI = 0.75   # |funding z90| at or beyond this = one side is paying up
OI_Z_HI = 0.50        # |OI-change z90| at or beyond this = leverage building / bleeding

CROWDED_LONG = "crowded long"
SQUEEZE_FUEL = "short-squeeze fuel"
CAPITULATION = "capitulation"
APATHY = "apathy"

LABELS = (CROWDED_LONG, SQUEEZE_FUEL, CAPITULATION, APATHY)
ACTIVE_LABELS = (CROWDED_LONG, SQUEEZE_FUEL, CAPITULATION)

# Colours for the Screener column and the quadrant scatter.
LABEL_COLORS = {
    CROWDED_LONG: "#ef4444",   # red - crowd is long, downside if it unwinds
    SQUEEZE_FUEL: "#22c55e",   # green - crowd is short, upside if it unwinds
    CAPITULATION: "#3b82f6",   # blue - leverage flushed out
    APATHY: "#6b7280",         # grey - nothing to fade
}


def _aligned_panels() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """funding z90, OI-change z90 and the close panel on one index/column set."""
    funding = funding_zscores()["z90"]
    oi = oi_zscores()["z90"]
    closes = momentum_zscores()["value"]
    columns = sorted(set(funding.columns) & set(oi.columns))
    index = funding.index.union(oi.index)
    return (funding.reindex(index=index, columns=columns),
            oi.reindex(index=index, columns=columns),
            closes.reindex(index=index, columns=columns))


def label_panel(funding_z: pd.DataFrame | None = None,
                oi_z: pd.DataFrame | None = None) -> pd.DataFrame:
    """Daily wide panel (ts x symbol) of quadrant labels; NaN where a z is missing."""
    if funding_z is None or oi_z is None:
        funding_z, oi_z, _ = _aligned_panels()
    labels = pd.DataFrame(APATHY, index=funding_z.index, columns=funding_z.columns)
    labels = labels.mask((funding_z >= FUNDING_Z_HI) & (oi_z >= OI_Z_HI), CROWDED_LONG)
    labels = labels.mask((funding_z <= -FUNDING_Z_HI) & (oi_z >= OI_Z_HI), SQUEEZE_FUEL)
    labels = labels.mask((funding_z <= -FUNDING_Z_HI) & (oi_z <= -OI_Z_HI), CAPITULATION)
    return labels.where(funding_z.notna() & oi_z.notna())


def label_row(funding_z: float | None, oi_z: float | None) -> str | float:
    """Label for one (funding z90, OI z90) pair - used on the latest snapshot."""
    if funding_z is None or oi_z is None or pd.isna(funding_z) or pd.isna(oi_z):
        return np.nan
    if funding_z >= FUNDING_Z_HI and oi_z >= OI_Z_HI:
        return CROWDED_LONG
    if funding_z <= -FUNDING_Z_HI and oi_z >= OI_Z_HI:
        return SQUEEZE_FUEL
    if funding_z <= -FUNDING_Z_HI and oi_z <= -OI_Z_HI:
        return CAPITULATION
    return APATHY


def label_table(table: pd.DataFrame) -> pd.Series:
    """Add-on for `analytics.zscores.cross_sectional_table()`: one label per coin."""
    return pd.Series(
        [label_row(f, o) for f, o in zip(table["funding_z90"], table["oi_z90"])],
        index=table.index, name="crowding", dtype=object,
    )


def frequency_table(labels: pd.DataFrame | None = None) -> pd.DataFrame:
    """How often each label fires: coin-days, share, days per coin-month, and
    distinct episodes (a run of consecutive days counts once) per coin-month."""
    if labels is None:
        labels = label_panel()
    stacked = labels.stack().dropna()
    total = len(stacked)
    coin_months = total / 30.0
    episodes = {}
    for symbol in labels.columns:
        column = labels[symbol].fillna("__na__")
        starts = column != column.shift()
        for label, count in column[starts].value_counts().items():
            if label != "__na__":
                episodes[label] = episodes.get(label, 0) + int(count)
    counts = stacked.value_counts()
    out = pd.DataFrame({
        "coin_days": counts,
        "share_%": counts / total * 100,
        "days_per_coin_month": counts / coin_months,
        "episodes": pd.Series(episodes),
        "episodes_per_coin_month": pd.Series(episodes) / coin_months,
    }).reindex(LABELS)
    out.index.name = "label"
    return out


def forward_return_by_quadrant(horizon_days: int = 7) -> pd.DataFrame:
    """Falsifier: bucket forward returns by quadrant over the whole history.

    If "crowded long" does not separate from the rest, this table says so.
    """
    funding_z, oi_z, closes = _aligned_panels()
    labels = label_panel(funding_z, oi_z)
    forward = closes.shift(-horizon_days) / closes - 1
    joined = pd.DataFrame({"label": labels.stack(), "fwd": forward.stack()}).dropna()
    grouped = joined.groupby("label")["fwd"]
    out = pd.DataFrame({
        "n": grouped.size(),
        "median_%": grouped.median() * 100,
        "mean_%": grouped.mean() * 100,
        "p25_%": grouped.quantile(0.25) * 100,
        "p75_%": grouped.quantile(0.75) * 100,
        "win_rate_%": grouped.apply(lambda s: (s > 0).mean() * 100),
    }).reindex([label for label in LABELS if label in grouped.groups])
    baseline = forward.stack().dropna()
    out.loc["ALL coin-days"] = [len(baseline), baseline.median() * 100, baseline.mean() * 100,
                                baseline.quantile(0.25) * 100, baseline.quantile(0.75) * 100,
                                (baseline > 0).mean() * 100]
    out.index.name = f"label ({horizon_days}d forward return)"
    return out


def main() -> None:
    labels = label_panel()
    print(f"crowding thresholds: |funding z90| >= {FUNDING_Z_HI}, |OI z90| >= {OI_Z_HI}")
    print(f"history: {labels.index.min().date()} .. {labels.index.max().date()}, "
          f"{labels.shape[1]} symbols\n")
    print("Frequency table")
    print(frequency_table(labels).to_string(float_format=lambda x: f"{x:.2f}"))
    for horizon in (7, 30):
        print(f"\nFalsifier: {horizon}d forward return by quadrant")
        print(forward_return_by_quadrant(horizon).to_string(float_format=lambda x: f"{x:.2f}"))
    print("\nLatest labels")
    latest = labels.iloc[-1].dropna()
    print(latest.value_counts().to_string())
    for label in ACTIVE_LABELS:
        hits = sorted(latest[latest == label].index)
        print(f"  {label}: {', '.join(hits) if hits else '-'}")


if __name__ == "__main__":
    main()
