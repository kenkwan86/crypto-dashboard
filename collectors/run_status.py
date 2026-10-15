"""Non-sensitive run summaries; no API payloads or exception messages."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from collectors.common import DATA_DIR


def collection_succeeded(counts: dict, healthy: bool = False) -> bool:
    positive = any(isinstance(value, int) and value > 0 for value in counts.values())
    return positive or (healthy and 'failed' not in counts.values())


def save_run_status(counts: dict, health: dict, elapsed: float) -> None:
    directory = DATA_DIR / 'collection_health'
    directory.mkdir(parents=True, exist_ok=True)
    tag = os.environ.get('DATA_WRITER_TAG', 'local')
    if not tag.replace('-', '').replace('_', '').isalnum():
        raise ValueError('Invalid writer tag')
    path = directory / f'latest-{tag}.json'
    content = {'observed_at': datetime.now(timezone.utc).isoformat(),
               'elapsed_s': round(elapsed, 1), 'counts': counts, 'coverage': health,
               'status': 'healthy' if all(v['status'] == 'healthy' for v in health.values()) else 'degraded'}
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(content, default=str, indent=2), encoding='utf-8')
    temporary.replace(path)


SYNC_OVERDUE = timedelta(hours=3)


def _parse_utc(value) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def sync_warning(path, now: datetime) -> str | None:
    """Message for the dashboard when the hourly git sync is failing or overdue.

    Reads logs/sync-status.json written by tools/run_hourly.ps1. A missing file
    (cloud run, fresh clone) is silent; an unreadable one warns.
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        status = json.loads(path.read_text(encoding='utf-8'))
        ok = status['ok']
        if not isinstance(ok, bool):
            raise ValueError('ok is not a boolean')
        raw_success = status.get('last_success_utc')
        success = None if raw_success is None else _parse_utc(raw_success)
        error = status.get('error')
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 'Sync status file is unreadable, so data syncing cannot be confirmed.'
    if not ok:
        last = 'never succeeded' if success is None else f'{success:%Y-%m-%d %H:%M UTC}'
        return f'Data sync is failing: {error or "unknown error"}. Last successful sync: {last}.'
    if success is None or now - success > SYNC_OVERDUE:
        last = 'never' if success is None else f'{success:%Y-%m-%d %H:%M UTC}'
        return f'Data sync is overdue: last successful sync {last}.'
    return None
