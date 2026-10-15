"""Hourly liquidation/OI events using prior 30-day observations only.
OI source is selected causally per coin; baseline statistics reset on a source
change. Historical revisions can change results, but future rows cannot.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.data_access import query, deduped_sql, load_open_interest

FLUSH_Z = 3.0
MIN_HOURS = 72  # 3 days of hourly rows before a coin's z-score means anything
FORWARD_HOURS = 24
EVENT_COLUMNS = ["symbol", "ts", "side", "usd", "ratio", "z"]


def load_hourly_liquidations() -> pd.DataFrame:
    return query(f"SELECT symbol, ts, long_usd, short_usd FROM ({deduped_sql('liquidations')}) WHERE interval = '1h' ORDER BY symbol, ts")


def load_hourly_oi(exchange: str) -> pd.DataFrame:
    return load_open_interest(exchange)


def load_hourly_closes(since: pd.Timestamp | None = None) -> pd.DataFrame:
    clause = f"AND ts >= TIMESTAMPTZ '{since.isoformat()}'" if since is not None else ""
    return query(f"SELECT symbol, ts, close FROM ({deduped_sql('ohlcv')}) WHERE exchange = 'binance' {clause} ORDER BY symbol, ts")


def continuous_hourly_oi(hours_needed: pd.DataFrame) -> pd.DataFrame:
    """Choose once from the first 72 actual overlapping hours; never look ahead.

    Prefer aggregated OI if it covers half those first hours, else Binance.
    Do not silently switch source later when one feed misses an observation.
    """
    parts = []
    sources = {name: load_hourly_oi(name) for name in ('coinalyze_agg', 'binance')}
    for symbol, hours in hours_needed.groupby('symbol'):
        hours = hours[['ts']].drop_duplicates().sort_values('ts')
        if len(hours) < MIN_HOURS:
            continue
        calibration = hours.iloc[:MIN_HOURS]
        aggregate = sources['coinalyze_agg']
        aggregate = aggregate[aggregate['symbol'] == symbol]
        overlap = calibration.merge(aggregate[['ts']], on='ts', how='inner')
        source = 'coinalyze_agg' if len(overlap) >= MIN_HOURS / 2 else 'binance'
        chosen = sources[source]
        chosen = chosen[(chosen['symbol'] == symbol) & (chosen['ts'] >= calibration['ts'].iloc[-1])].copy()
        chosen['oi_src'] = source
        parts.append(chosen)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=['symbol','ts','oi_usd','oi_src'])


def flush_panel() -> pd.DataFrame:
    """Prior 30-day baseline, at least 72 valid hours, excluding the event itself."""
    columns = ['symbol','ts','long_usd','short_usd','oi_usd','oi_src',
               'long_ratio','short_ratio','long_z','short_z','long_flush','short_flush']
    liquidations = load_hourly_liquidations()
    if liquidations.empty:
        return pd.DataFrame(columns=columns)
    oi = continuous_hourly_oi(liquidations)
    frame = liquidations.merge(oi, on=['symbol','ts'], how='inner')
    frame = frame[(frame['oi_usd'] > 0) & (frame['long_usd'] >= 0) & (frame['short_usd'] >= 0)].copy()
    parts = []
    for _, coin in frame.groupby(['symbol','oi_src']):
        coin = coin.sort_values('ts').set_index('ts')
        for side in ('long','short'):
            ratio = coin[f'{side}_usd'] / coin['oi_usd']
            baseline = ratio.rolling('30D', min_periods=MIN_HOURS, closed='left')
            std = baseline.std()
            coin[f'{side}_ratio'] = ratio
            coin[f'{side}_z'] = (ratio - baseline.mean()) / std.where(std > 0)
            coin[f'{side}_flush'] = coin[f'{side}_z'] >= FLUSH_Z
        parts.append(coin.reset_index())
    return pd.concat(parts, ignore_index=True)[columns] if parts else pd.DataFrame(columns=columns)


def flush_events(panel: pd.DataFrame | None = None, hours: int = 48, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """One row per flagged (coin, hour, side) in the last `hours` hours."""
    panel = flush_panel() if panel is None else panel
    if panel.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    now = pd.Timestamp.now(tz="UTC") if now is None else now
    cutoff = now - pd.Timedelta(hours=hours)
    recent = panel[(panel["ts"] >= cutoff) & (panel["ts"] <= now)]
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


def top_flush_now(panel: pd.DataFrame | None = None, n: int = 10, now: pd.Timestamp | None = None) -> dict[str, pd.DataFrame]:
    """Top n coins by their most recent long-flush z and short-flush z.

    Coverage is uneven hour to hour, so each coin contributes its newest row -
    but only if that row is within STALE_HOURS of the current UTC time.
    """
    panel = flush_panel() if panel is None else panel
    if panel.empty:
        return {"long": pd.DataFrame(), "short": pd.DataFrame()}
    now = pd.Timestamp.now(tz="UTC") if now is None else now
    fresh = panel[(panel["ts"] >= now - pd.Timedelta(hours=STALE_HOURS)) & (panel["ts"] <= now)]
    latest = fresh.sort_values("ts").drop_duplicates("symbol", keep="last")
    out = {}
    for side in ("long", "short"):
        table = latest[["symbol", "ts", f"{side}_usd", f"{side}_ratio", f"{side}_z", "oi_usd", "oi_src"]]
        table = table.rename(columns={f"{side}_usd": "usd", f"{side}_ratio": "ratio", f"{side}_z": "z"})
        out[side] = table.dropna(subset=["z"]).sort_values("z", ascending=False).head(n).reset_index(drop=True)
    return out


def falsifier(panel: pd.DataFrame | None = None, threshold: float = FLUSH_Z) -> dict:
    """Do long-flush hours precede positive 24h returns more often than chance?

    Compares the hit rate (share of events followed by a positive
    FORWARD_HOURS-hour return) after each flush side against the base rate over
    every hour in the same sample. PRELIMINARY: flush hours cluster inside the same market-wide cascades, so the
    event counts are far from independent observations.
    """
    panel = flush_panel() if panel is None else panel
    result = {"threshold": threshold, "forward_hours": FORWARD_HOURS}
    if panel.empty:
        return result | {"base": None, "long": None, "short": None}

    closes = load_hourly_closes(panel["ts"].min())
    closes = closes.sort_values(["symbol", "ts"])
    future = closes[['symbol','ts','close']].rename(columns={'close':'future_close'})
    future['ts'] = future['ts'] - pd.Timedelta(hours=FORWARD_HOURS)
    closes = closes.merge(future, on=['symbol','ts'], how='left', validate='one_to_one')
    closes['forward_return'] = closes['future_close'] / closes['close'] - 1
    merged = panel.merge(closes[["symbol", "ts", "forward_return"]], on=["symbol", "ts"], how="left")
    merged = merged[merged["long_z"].notna() & merged["short_z"].notna()]
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
    print(f"z-score window: prior 30 days per coin (min {MIN_HOURS}h), "
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
          "(PRELIMINARY, dependent market events) ---")
    base = result["base"]
    print(f"base rate over all {base['n']} coin-hours: hit {base['hit_rate'] * 100:.1f}%, "
          f"mean 24h return {base['mean_return'] * 100:+.2f}%")
    for side in ("long", "short"):
        s = result[side]
        print(f"{side}-flush (z >= {result['threshold']}): n={s['n']}, "
              f"hit {s['hit_rate'] * 100:.1f}%, mean 24h return {s['mean_return'] * 100:+.2f}%")
