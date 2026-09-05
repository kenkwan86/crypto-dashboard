"""Liquidation-flush trigger from the hourly long/short split.

A flush is an hour in which forced selling (or forced buying) is large relative
to the positioning it is unwinding. The raw dollar figure is useless across
coins - $50m is a rounding error in BTC and a cascade in a mid-cap - so every
hour is normalised by that coin's open interest:

    long_ratio  = long_usd  / oi_usd     (longs stopped out: forced selling)
    short_ratio = short_usd / oi_usd     (shorts squeezed:  forced buying)

Z-SCORE WINDOW: the full hourly history available, per coin, as one sample mean
and standard deviation (an expanding window, not a rolling one). The hourly
liquidation rows only start 2026-08-24, so there is not yet enough data for the
30/90/365-day rolling windows used elsewhere in analytics/zscores.py; a 30-day
rolling window would return all-NaN today. Coins with fewer than MIN_HOURS
hourly observations are dropped. Revisit this once a few months of hourly rows
exist - the intended end state is rolling z30.

THRESHOLD: FLUSH_Z = 3.0. Chosen from the data, not from theory. The ratio
distribution is heavily right-skewed, so a normal-tail reading of z >= 3 (0.13%
of hours) is far off: on the history to date z >= 3 fires on about 2.2% of
long-side hours and 2.1% of short-side hours, i.e. roughly one flagged hour per
coin every two days. That is the level where the flag still picks out visible
cascades rather than ordinary hourly noise, while leaving enough events to test.
z >= 4 (about 1.4% of hours) is the stricter alternative if the table is noisy.

OPEN INTEREST SOURCE: one continuous source per coin, never a sum across the
live venues and the Coinalyze backfill (see CLAUDE.md). Coinalyze aggregated OI
is preferred here because the liquidation figures are themselves Coinalyze's
cross-exchange aggregate - dividing an all-venue numerator by a single venue's
OI would overstate every ratio. Binance-only OI is the fallback when a coin has
no usable Coinalyze hourly coverage; the source used is reported per coin.

Run: python -m analytics.flush
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.data_access import query, table_exists, table_path

FLUSH_Z = 3.0
MIN_HOURS = 72  # 3 days of hourly rows before a coin's z-score means anything
FORWARD_HOURS = 24
EVENT_COLUMNS = ["symbol", "ts", "side", "usd", "ratio", "z"]


def load_hourly_liquidations() -> pd.DataFrame:
    """The interval='1h' rows only, deduped on (symbol, ts). The 1d backfill
    rows and the 'unknown' rows are excluded - see analytics/liquidations.py."""
    if not table_exists("liquidations"):
        return pd.DataFrame(columns=["symbol", "ts", "long_usd", "short_usd"])
    frame = query(f"""
        SELECT symbol, ts, max(long_usd) AS long_usd, max(short_usd) AS short_usd
        FROM read_parquet('{table_path('liquidations')}', union_by_name=true)
        WHERE interval = '1h'
        GROUP BY symbol, ts ORDER BY symbol, ts
    """)
    if not frame.empty:
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame


def load_hourly_oi(exchange: str) -> pd.DataFrame:
    """Hourly OI for one exchange tag, deduped on (symbol, ts)."""
    frame = query(f"""
        SELECT symbol, ts, max(oi_usd) AS oi_usd
        FROM read_parquet('{table_path('open_interest')}', union_by_name=true)
        WHERE exchange = '{exchange}'
        GROUP BY symbol, ts ORDER BY symbol, ts
    """)
    if not frame.empty:
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame


def load_hourly_closes(since: pd.Timestamp | None = None) -> pd.DataFrame:
    """Hourly closes, deduped on (symbol, ts)."""
    clause = f"WHERE ts >= TIMESTAMPTZ '{since:%Y-%m-%d %H:%M:%S}+00'" if since is not None else ""
    frame = query(f"""
        WITH deduped AS (
            SELECT symbol, ts, exchange, max(close) AS close
            FROM read_parquet('{table_path('ohlcv')}', union_by_name=true)
            {clause}
            GROUP BY symbol, ts, exchange
        )
        SELECT symbol, ts, max(close) AS close
        FROM deduped GROUP BY symbol, ts ORDER BY symbol, ts
    """)
    if not frame.empty:
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame


def continuous_hourly_oi(hours_needed: pd.DataFrame) -> pd.DataFrame:
    """One OI series per coin from a single source, plus an `oi_src` column.

    `hours_needed` is the liquidation frame; a coin takes Coinalyze aggregated
    OI when that source covers at least half of the coin's liquidation hours,
    and Binance-only OI otherwise.
    """
    coinalyze = load_hourly_oi("coinalyze_agg")
    binance = load_hourly_oi("binance")
    if hours_needed.empty:
        return pd.DataFrame(columns=["symbol", "ts", "oi_usd", "oi_src"])
    start = hours_needed["ts"].min()
    coinalyze = coinalyze[coinalyze["ts"] >= start]
    binance = binance[binance["ts"] >= start]

    wanted = hours_needed.groupby("symbol")["ts"].nunique()
    coinalyze_hours = coinalyze.groupby("symbol")["ts"].nunique()
    parts = []
    for symbol, needed in wanted.items():
        have = coinalyze_hours.get(symbol, 0)
        if have >= 0.5 * needed:
            part = coinalyze[coinalyze["symbol"] == symbol].copy()
            part["oi_src"] = "coinalyze_agg"
        else:
            part = binance[binance["symbol"] == symbol].copy()
            part["oi_src"] = "binance"
        if not part.empty:
            parts.append(part)
    if not parts:
        return pd.DataFrame(columns=["symbol", "ts", "oi_usd", "oi_src"])
    return pd.concat(parts, ignore_index=True)


def flush_panel() -> pd.DataFrame:
    """Per (symbol, ts): the two liquidation/OI ratios, their z-scores over the
    coin's full hourly history, and the flush flags."""
    columns = ["symbol", "ts", "long_usd", "short_usd", "oi_usd", "oi_src",
               "long_ratio", "short_ratio", "long_z", "short_z",
               "long_flush", "short_flush"]
    liquidations = load_hourly_liquidations()
    if liquidations.empty:
        return pd.DataFrame(columns=columns)
    oi = continuous_hourly_oi(liquidations)
    if oi.empty:
        return pd.DataFrame(columns=columns)

    frame = liquidations.merge(oi, on=["symbol", "ts"], how="inner")
    frame = frame[frame["oi_usd"] > 0].sort_values(["symbol", "ts"])
    if frame.empty:
        return pd.DataFrame(columns=columns)

    counts = frame.groupby("symbol")["ts"].transform("size")
    frame = frame[counts >= MIN_HOURS].copy()
    if frame.empty:
        return pd.DataFrame(columns=columns)

    frame["long_ratio"] = frame["long_usd"] / frame["oi_usd"]
    frame["short_ratio"] = frame["short_usd"] / frame["oi_usd"]
    grouped = frame.groupby("symbol")
    for side in ("long", "short"):
        ratio = f"{side}_ratio"
        mean = grouped[ratio].transform("mean")
        std = grouped[ratio].transform("std")
        frame[f"{side}_z"] = np.where(std > 0, (frame[ratio] - mean) / std, np.nan)
        frame[f"{side}_flush"] = frame[f"{side}_z"] >= FLUSH_Z
    return frame[columns].reset_index(drop=True)


def flush_events(panel: pd.DataFrame | None = None, hours: int = 48) -> pd.DataFrame:
    """One row per flagged (coin, hour, side) in the last `hours` hours."""
    panel = flush_panel() if panel is None else panel
    if panel.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    cutoff = panel["ts"].max() - pd.Timedelta(hours=hours)
    recent = panel[panel["ts"] >= cutoff]
    rows = []
    for side in ("long", "short"):
        hit = recent[recent[f"{side}_flush"]]
        if hit.empty:
            continue
        rows.append(pd.DataFrame({
            "symbol": hit["symbol"], "ts": hit["ts"], "side": side,
            "usd": hit[f"{side}_usd"], "ratio": hit[f"{side}_ratio"],
            "z": hit[f"{side}_z"],
        }))
    if not rows:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    events = pd.concat(rows, ignore_index=True)
    return events.sort_values(["ts", "z"], ascending=[False, False]).reset_index(drop=True)


STALE_HOURS = 6  # a coin's newest hour must be this fresh to count as "current"


def top_flush_now(panel: pd.DataFrame | None = None, n: int = 10) -> dict[str, pd.DataFrame]:
    """Top n coins by their most recent long-flush z and short-flush z.

    Coverage is uneven hour to hour, so each coin contributes its newest row -
    but only if that row is within STALE_HOURS of the panel's latest hour.
    """
    panel = flush_panel() if panel is None else panel
    if panel.empty:
        return {"long": pd.DataFrame(), "short": pd.DataFrame()}
    fresh = panel[panel["ts"] >= panel["ts"].max() - pd.Timedelta(hours=STALE_HOURS)]
    latest = fresh.sort_values("ts").groupby("symbol", as_index=False).last()
    out = {}
    for side in ("long", "short"):
        table = latest[["symbol", "ts", f"{side}_usd", f"{side}_ratio", f"{side}_z", "oi_usd", "oi_src"]]
        table = table.rename(columns={f"{side}_usd": "usd", f"{side}_ratio": "ratio", f"{side}_z": "z"})
        out[side] = table.sort_values("z", ascending=False).head(n).reset_index(drop=True)
    return out


def falsifier(panel: pd.DataFrame | None = None, threshold: float = FLUSH_Z) -> dict:
    """Do long-flush hours precede positive 24h returns more often than chance?

    Compares the hit rate (share of events followed by a positive
    FORWARD_HOURS-hour return) after each flush side against the base rate over
    every hour in the same sample. PRELIMINARY: the hourly history is under two
    weeks, and flush hours cluster inside the same market-wide cascades, so the
    event counts are far from independent observations.
    """
    panel = flush_panel() if panel is None else panel
    result = {"threshold": threshold, "forward_hours": FORWARD_HOURS}
    if panel.empty:
        return result | {"base": None, "long": None, "short": None}

    closes = load_hourly_closes(panel["ts"].min())
    closes = closes.sort_values(["symbol", "ts"])
    closes["forward_return"] = (closes.groupby("symbol")["close"].shift(-FORWARD_HOURS)
                                / closes["close"] - 1)
    merged = panel.merge(closes[["symbol", "ts", "forward_return"]], on=["symbol", "ts"], how="left")
    base = merged["forward_return"].dropna()

    def stats(sample: pd.Series) -> dict:
        return {"n": int(len(sample)),
                "hit_rate": float((sample > 0).mean()) if len(sample) else float("nan"),
                "mean_return": float(sample.mean()) if len(sample) else float("nan")}

    result["base"] = stats(base)
    result["start"] = panel["ts"].min()
    result["end"] = panel["ts"].max()
    for side in ("long", "short"):
        sample = merged.loc[merged[f"{side}_z"] >= threshold, "forward_return"].dropna()
        result[side] = stats(sample)
    return result


if __name__ == "__main__":
    panel = flush_panel()
    if panel.empty:
        print("no hourly liquidation rows yet")
        raise SystemExit(0)

    print(f"hourly panel: {len(panel)} rows, {panel['symbol'].nunique()} coins, "
          f"{panel['ts'].min()} -> {panel['ts'].max()}")
    print(f"z-score window: full hourly history per coin (min {MIN_HOURS}h), "
          f"flush threshold z >= {FLUSH_Z}")
    print(f"flagged hours: long {panel['long_flush'].mean() * 100:.2f}%, "
          f"short {panel['short_flush'].mean() * 100:.2f}%\n")

    events = flush_events(panel)
    print(f"--- flush events, last 48h ({len(events)}) ---")
    if events.empty:
        print("none")
    else:
        show = events.head(25).copy()
        show["usd"] = show["usd"] / 1e6
        print(show.rename(columns={"usd": "usd_m"}).to_string(
            index=False, float_format=lambda x: f"{x:.3f}"))

    tops = top_flush_now(panel)
    for side in ("long", "short"):
        print(f"\n--- top 10 by current {side}-flush z ---")
        table = tops[side].copy()
        table["usd"] = table["usd"] / 1e6
        print(table.rename(columns={"usd": "usd_m"}).to_string(
            index=False, float_format=lambda x: f"{x:.3f}"))

    result = falsifier(panel)
    print("\n--- falsifier: do flush hours precede positive 24h returns? "
          "(PRELIMINARY, <2 weeks of hourly data) ---")
    base = result["base"]
    print(f"base rate over all {base['n']} coin-hours: hit {base['hit_rate'] * 100:.1f}%, "
          f"mean 24h return {base['mean_return'] * 100:+.2f}%")
    for side in ("long", "short"):
        s = result[side]
        print(f"{side}-flush (z >= {result['threshold']}): n={s['n']}, "
              f"hit {s['hit_rate'] * 100:.1f}%, mean 24h return {s['mean_return'] * 100:+.2f}%")
