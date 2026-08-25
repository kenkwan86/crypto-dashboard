"""Options metrics from Deribit chain snapshots: ATM term structure and
25-delta risk-reversal skew. Deltas are computed with Black-Scholes from each
instrument's mark IV (the book summary endpoint has no greeks).

Run: python -m analytics.options_metrics
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from analytics.data_access import query, table_path

MIN_EXPIRY_DAYS = 2  # ignore expiries closer than this: IV is noise there


def load_chain() -> pd.DataFrame:
    df = query(f"SELECT * FROM read_parquet('{table_path('options_chain')}')")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["expiry_ts"] = pd.to_datetime(df["expiry"], format="%d%b%y", utc=True) + pd.Timedelta(hours=8)
    df["tau_years"] = (df["expiry_ts"] - df["ts"]).dt.total_seconds() / (365 * 24 * 3600)
    df = df[(df["tau_years"] > MIN_EXPIRY_DAYS / 365) & (df["mark_iv"] > 0)]
    return df


def bs_delta(row) -> float:
    sigma = row["mark_iv"] / 100
    tau = row["tau_years"]
    if row["underlying_price"] is None or row["underlying_price"] <= 0:
        return math.nan
    d1 = (math.log(row["underlying_price"] / row["strike"]) + 0.5 * sigma**2 * tau) / (sigma * math.sqrt(tau))
    call_delta = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
    return call_delta if row["option_type"] == "C" else call_delta - 1


def chain_metrics() -> pd.DataFrame:
    """Per (ts, currency, expiry): ATM IV, IV at +0.25 call delta and -0.25 put
    delta (interpolated across strikes), and the 25-delta risk reversal."""
    chain = load_chain()
    if chain.empty:
        return pd.DataFrame()
    chain["delta"] = chain.apply(bs_delta, axis=1)
    rows = []
    for (ts, currency, expiry), group in chain.groupby(["ts", "currency", "expiry_ts"]):
        calls = group[group["option_type"] == "C"].sort_values("delta")
        puts = group[group["option_type"] == "P"].sort_values("delta")
        if len(calls) < 3 or len(puts) < 3:
            continue
        atm_row = group.iloc[(group["strike"] - group["underlying_price"]).abs().argsort().iloc[0]]
        call_25 = np.interp(0.25, calls["delta"], calls["mark_iv"])
        put_25 = np.interp(-0.25, puts["delta"], puts["mark_iv"])
        rows.append({
            "ts": ts, "currency": currency, "expiry": expiry,
            "days_to_expiry": (expiry - ts).total_seconds() / 86400,
            "atm_iv": atm_row["mark_iv"], "call25_iv": call_25, "put25_iv": put_25,
            "rr25": call_25 - put_25, "total_oi": group["open_interest"].sum(),
        })
    return pd.DataFrame(rows).sort_values(["ts", "currency", "days_to_expiry"])


def latest_term_structure() -> pd.DataFrame:
    metrics = chain_metrics()
    if metrics.empty:
        return metrics
    latest_ts = metrics["ts"].max()
    return metrics[metrics["ts"] == latest_ts]


if __name__ == "__main__":
    ts = latest_term_structure()
    if ts.empty:
        print("no chain snapshots yet")
    else:
        print(ts.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
