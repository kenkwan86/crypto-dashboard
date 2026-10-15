import json
import logging
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from collectors.run_status import sync_warning

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def stamp(delta):
    return (NOW - delta).strftime('%Y-%m-%dT%H:%M:%SZ')


def sync_app():
    import os
    from pathlib import Path
    from dashboard import shared
    shared.SYNC_STATUS_PATH = Path(os.environ['SYNC_STATUS_TEST_PATH'])
    shared.render_sync_status()


class SyncStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logging.getLogger('streamlit.runtime.scriptrunner_utils.script_run_context').disabled = True

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self.temp.name) / 'sync-status.json'

    def tearDown(self):
        self.temp.cleanup()

    def write(self, ok, success, error=None, attempt=timedelta(minutes=1)):
        content = {'last_attempt_utc': stamp(attempt), 'last_success_utc': success, 'ok': ok, 'error': error}
        self.path.write_text(json.dumps(content), encoding='utf-8')

    def test_failed_sync_warns_immediately(self):
        self.write(False, stamp(timedelta(minutes=10)), 'sync FAILED: push exit=1')
        message = sync_warning(self.path, NOW)
        self.assertIsNotNone(message)
        self.assertIn('sync FAILED: push exit=1', message)

    def test_never_succeeded_is_named(self):
        self.write(False, None, 'sync BLOCKED: uncommitted changes outside data/')
        self.assertIn('never', sync_warning(self.path, NOW))

    def test_overdue_success_warns(self):
        self.write(True, stamp(timedelta(hours=5)))
        self.assertIsNotNone(sync_warning(self.path, NOW))

    def test_recent_success_is_silent(self):
        self.write(True, stamp(timedelta(minutes=30)))
        self.assertIsNone(sync_warning(self.path, NOW))

    def test_missing_file_is_silent(self):
        self.assertIsNone(sync_warning(self.path, NOW))

    def test_corrupt_file_warns(self):
        self.path.write_text('{not json', encoding='utf-8')
        self.assertIsNotNone(sync_warning(self.path, NOW))

    def test_render_sync_status_shows_error(self):
        self.write(False, stamp(timedelta(minutes=10)), 'sync FAILED: push exit=1')
        with patch.dict(os.environ, {'SYNC_STATUS_TEST_PATH': str(self.path)}):
            at = AppTest.from_function(sync_app, default_timeout=30).run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(len(at.error), 1)
        self.assertIn('sync FAILED: push exit=1', at.error[0].value)

    def test_every_page_renders_sync_status(self):
        files = [ROOT / 'dashboard' / 'app.py', *sorted((ROOT / 'dashboard' / 'pages').glob('*.py'))]
        self.assertGreaterEqual(len(files), 8)
        for file in files:
            text = file.read_text(encoding='utf-8')
            self.assertTrue('render_freshness(' in text or 'render_sync_status(' in text, file.name)


if __name__ == '__main__':
    unittest.main()
