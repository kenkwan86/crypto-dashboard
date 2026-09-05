"""Implied vs realised volatility for BTC and ETH.

Deribit DVOL is a 30-day forward implied-vol index in annualised % points. This
module builds the matching 30-day *realised* vol from the stored hourly candles
and takes the difference, so the number on screen answers one question: is the
option market charging more or less than the coin has actually been moving?

Two realised estimators are computed on the same 720-hour (30-day) window:

  close_to_close - stdev of hourly log returns, annualised by sqrt(24*365).
  parkinson      - high/low range estimator, sqrt(mean(ln(h/l)^2) / (4*ln 2)),
                   annualised the same way.

DEFAULT ESTIMATOR: close_to_close. It is the noisier of the two (Parkinson is
roughly five times more efficient per observation) but it is the one that
matches the trade. A short option position hedged at discrete intervals accrues
P&L against realised *return* variance, which is what close-to-close measures;
Parkinson measures the path's range and, on a 24/7 market with no open/close
gaps, systematically prints below close-to-close whenever intra-hour reversals
are frequent. Selling vol against a Parkinson-based spread therefore flatters
the edge. Parkinson is carried alongside as a lower-noise sanity check: when the
two estimators disagree materially the move has been chop rather than trend, and
the spread reading deserves less weight.

Run: python -m analytics.vol
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.data_access import query, table_path

CURRENCIES = ("BTC", "ETH")
WINDOW_HOURS = 720  # 30 days of hourly candles
MIN_PERIODS = 480  # 20 days: enough to be meaningful, tolerant of small gaps
HOURS_PER_YEAR = 24 * 365
ESTIMATORS = ("close_to_close", "parkinson")
DEFAULT_ESTIMATOR = "close_to_close"


def load_hourly_ohlcv(symbols: tuple[str, ...] = CURRENCIES) -> pd.DataFrame:
    """Hourly high/low/close per (symbol, ts), deduped across writer files."""
    quoted = ", ".join(f"'{s}'" for s in symbols)
    frame = query(f"""
        WITH deduped AS (
            SELECT symbol, ts, exchange, max(high) AS high, min(low) AS low, max(close) AS close
            FROM read_parquet('{table_path('ohlcv')}', union_by_name=true)
            WHERE symbol IN ({quoted})
            GROUP BY symbol, ts, exchange
        )
        SELECT symbol, ts, max(high) AS high, min(low) AS low, max(close) AS close
        FROM deduped
        GROUP BY symbol, ts ORDER BY symbol, ts
    """)
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame


def load_dvol_hourly(currencies: tuple[str, ...] = CURRENCIES) -> pd.DataFrame:
    """Hourly DVOL close per (currency, ts), deduped across writer files."""
    quoted = ", ".join(f"'{c}'" for c in currencies)
    frame = query(f"""
        SELECT currency, ts, max(close) AS dvol
        FROM read_parquet('{table_path('options_dvol')}', union_by_name=true)
        WHERE currency IN ({quoted})
        GROUP BY currency, ts ORDER BY currency, ts
    """)
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame


def realised_vol(candles: pd.DataFrame, window: int = WINDOW_HOURS) -> pd.DataFrame:
    """Both annualised realised-vol estimators (in % points) for one symbol.

    `candles` must be one symbol's hourly rows sorted by ts.
    """
    frame = candles.sort_values("ts").copy()
    log_return = np.log(frame["close"]).diff()
    close_to_close = log_return.rolling(window, min_periods=MIN_PERIODS).std()

    # Parkinson: sigma^2 = mean(ln(h/l)^2) / (4 ln 2) per bar.
    log_range_sq = np.log(frame["high"] / frame["low"]) ** 2
    parkinson_var = log_range_sq.rolling(window, min_periods=MIN_PERIODS).mean() / (4 * np.log(2))

    scale = np.sqrt(HOURS_PER_YEAR) * 100
    frame["rv30_close_to_close"] = close_to_close * scale
    frame["rv30_parkinson"] = np.sqrt(parkinson_var) * scale
    return frame[["ts", "close", "rv30_close_to_close", "rv30_parkinson"]]


def vol_spread(estimator: str = DEFAULT_ESTIMATOR,
               currencies: tuple[str, ...] = CURRENCIES) -> pd.DataFrame:
    """Per (currency, ts): DVOL, both RV30 estimators, the DVOL-minus-RV spread
    for the chosen estimator, and that spread's percentile over the full history.

    The percentile is a full-sample rank (0-100): 90 means the spread has been
    this rich or richer in only 10% of the hours on record.
    """
    if estimator not in ESTIMATORS:
        raise ValueError(f"estimator must be one of {ESTIMATORS}, got {estimator!r}")
    candles = load_hourly_ohlcv(currencies)
    dvol = load_dvol_hourly(currencies)
    if candles.empty or dvol.empty:
        return pd.DataFrame(columns=["currency", "ts", "dvol", "rv30_close_to_close",
                                     "rv30_parkinson", "spread", "spread_pct"])

    parts = []
    for currency in currencies:
        coin = candles[candles["symbol"] == currency]
        implied = dvol[dvol["currency"] == currency]
        if coin.empty or implied.empty:
            continue
        merged = implied.merge(realised_vol(coin), on="ts", how="inner")
        merged["spread"] = merged["dvol"] - merged[f"rv30_{estimator}"]
        merged["spread_pct"] = merged["spread"].rank(pct=True) * 100
        parts.append(merged)
    if not parts:
        return pd.DataFrame(columns=["currency", "ts", "dvol", "rv30_close_to_close",
                                     "rv30_parkinson", "spread", "spread_pct"])
    out = pd.concat(parts, ignore_index=True)
    return out.dropna(subset=["spread"]).sort_values(["currency", "ts"]).reset_index(drop=True)


def latest_spread(estimator: str = DEFAULT_ESTIMATOR,
                  currencies: tuple[str, ...] = CURRENCIES) -> pd.DataFrame:
    """One row per currency: the most recent DVOL / RV30 / spread / percentile."""
    history = vol_spread(estimator, currencies)
    if history.empty:
        return history
    latest = history.groupby("currency", as_index=False).last()
    latest["reading"] = [reading(row["spread_pct"]) for _, row in latest.iterrows()]
    return latest


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def reading(percentile: float) -> str:
    """The one-line trader reading for a spread percentile."""
    if pd.isna(percentile):
        return "not enough history"
    if percentile >= 80:
        word = "rich"
    elif percentile <= 20:
        word = "cheap"
    else:
        word = "fairly priced"
    return f"vol is {word} vs realised at the {_ordinal(round(percentile))} percentile"


if __name__ == "__main__":
    print(f"default estimator: {DEFAULT_ESTIMATOR} (window {WINDOW_HOURS}h)\n")
    latest = latest_spread()
    if latest.empty:
        print("no DVOL / OHLCV overlap yet")
    else:
        columns = ["currency", "ts", "dvol", "rv30_close_to_close", "rv30_parkinson",
                   "spread", "spread_pct"]
        print(latest[columns].to_string(index=False, float_format=lambda x: f"{x:.2f}"))
        print()
        for _, row in latest.iterrows():
            print(f"{row['currency']}: {row['reading']}")
        history = vol_spread()
        print(f"\n{len(history)} hourly rows, "
              f"{history['ts'].min():%Y-%m-%d} to {history['ts'].max():%Y-%m-%d}")
