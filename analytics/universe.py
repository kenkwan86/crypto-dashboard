"""Current and recorded membership; history before first observation is unknown."""
import pandas as pd
from analytics import data_access as da


def current_universe() -> pd.DataFrame:
    path = da.DATA_DIR / 'universe.parquet'
    columns = ['base','binance_symbol','bybit_symbol','hyperliquid_symbol']
    return pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=columns)


def membership(index: pd.DatetimeIndex, columns) -> tuple[pd.DataFrame, pd.Series]:
    mask = pd.DataFrame(True, index=index, columns=columns)
    recorded = pd.Series(False, index=index, dtype=bool)
    directory = da.DATA_DIR / 'universe_history'
    files = sorted(directory.glob('*.parquet')) if directory.exists() else []
    snapshots = [pd.read_parquet(path) for path in files]
    # Daily analytics use membership known at the start of each UTC day.
    for snapshot in sorted(snapshots, key=lambda frame: frame['effective_at'].iloc[0]):
        effective = pd.Timestamp(snapshot['effective_at'].iloc[0])
        rows = index >= effective
        mask.loc[rows, :] = [symbol in set(snapshot['base']) for symbol in columns]
        recorded.loc[rows] = True
    return mask, recorded
