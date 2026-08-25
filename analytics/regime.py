"""Composite market regime index.

Daily score = mean of available component z-scores/percentile-scores, clipped to
[-3, 3]. Positive = hot/euphoric positioning, negative = washed-out. Components:
  funding_z   - median 90d funding z across the universe (heating/cooling speed)
  funding_pct - 1y percentile of the median funding LEVEL (absolute crowdedness;
                z-scores alone miss long-lasting hot periods like Nov 2021)
  oi_z        - median 90d z of 7d OI change (leverage building when high)
  momentum_z  - median 90d z of 30d returns
  breadth     - % of coins above their 50d MA, rescaled to [-2, 2]
  dvol_pct    - BTC DVOL 1y percentile, rescaled to [-2, 2] (high vol regime when high)

Run: python -m analytics.regime  (writes data/analytics_cache/regime.parquet)
"""

from __future__ import annotations

import pandas as pd

from analytics.data_access import load_dvol
from analytics.zscores import daily_panel, funding_zscores, momentum_zscores, oi_zscores
from analytics.data_access import load_daily_closes
from collectors.common import DATA_DIR

CACHE_PATH = DATA_DIR / "analytics_cache" / "regime.parquet"


def compute_regime() -> pd.DataFrame:
    funding_panels = funding_zscores()
    funding = funding_panels["z90"].median(axis=1)
    funding_level = funding_panels["value"].median(axis=1)
    funding_pct = (funding_level.rolling(365, min_periods=180).rank(pct=True) - 0.5) * 4
    oi = oi_zscores()["z90"].median(axis=1)
    momentum = momentum_zscores()["z90"].median(axis=1)

    closes = daily_panel(load_daily_closes(), "close")
    ma_50d = closes.rolling(50, min_periods=25).mean()
    valid = ma_50d.notna() & closes.notna()
    valid_counts = valid.sum(axis=1).astype(float)
    breadth_pct = (closes > ma_50d)[valid].sum(axis=1) / valid_counts.where(valid_counts > 0)
    breadth = (breadth_pct - 0.5) * 4  # 0%..100% -> -2..+2

    dvol = load_dvol()
    btc_dvol = (dvol[dvol["currency"] == "BTC"].set_index("ts")["close"]
                .groupby(lambda ts: ts.floor("D")).last())
    dvol_rank = btc_dvol.rolling(365, min_periods=180).rank(pct=True)
    dvol_score = (dvol_rank - 0.5) * 4

    components = pd.DataFrame({
        "funding_z": funding, "funding_pct": funding_pct, "oi_z": oi,
        "momentum_z": momentum, "breadth": breadth, "dvol_pct": dvol_score,
    }).clip(-3, 3)
    component_names = ["funding_z", "funding_pct", "oi_z", "momentum_z", "breadth", "dvol_pct"]
    components["regime"] = components[component_names].mean(axis=1, skipna=True)
    components["n_components"] = components[component_names].notna().sum(axis=1)
    return components.dropna(subset=["regime"])


def main() -> None:
    regime = compute_regime()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    regime.reset_index(names="ts").to_parquet(CACHE_PATH, index=False)
    print(f"regime: {len(regime)} days -> {CACHE_PATH}")
    print(regime.tail(10).to_string(float_format=lambda x: f"{x:.2f}"))


if __name__ == "__main__":
    main()
