"""Non-sensitive run summaries; no API payloads or exception messages."""
import json
import os
from datetime import datetime, timezone

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
