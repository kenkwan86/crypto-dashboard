import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get('RUN_HOURLY_PS1', str(WORKTREE / 'tools' / 'run_hourly.ps1')))
OLD_ROOT = 'C:\\01. Coding\\Crypto-Dashboard'
POWERSHELL = shutil.which('powershell.exe') or shutil.which('powershell')

STUB = (
    "import pathlib\n"
    "p = pathlib.Path('data/x.txt')\n"
    "p.parent.mkdir(exist_ok=True)\n"
    "n = len(p.read_text().splitlines()) if p.exists() else 0\n"
    "with p.open('a') as f:\n"
    "    f.write('line%d\\n' % n)\n"
)


def git(cwd, *args, check=True):
    run = subprocess.run(['git', *args], cwd=str(cwd), capture_output=True, text=True)
    if check and run.returncode != 0:
        raise RuntimeError('git %s failed: %s' % (' '.join(args), run.stderr))
    return run


@unittest.skipUnless(POWERSHELL, 'powershell.exe not found')
class RunHourly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print('P1-powershell-ran')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        base = Path(self.temp.name)
        self.remote = base / 'remote.git'
        self.clone = base / 'clone'
        subprocess.run(['git', 'init', '--bare', '-b', 'main', str(self.remote)], check=True, capture_output=True)
        subprocess.run(['git', 'clone', str(self.remote), str(self.clone)], check=True, capture_output=True)
        git(self.clone, 'checkout', '-B', 'main')
        git(self.clone, 'config', 'user.name', 'tester')
        git(self.clone, 'config', 'user.email', 'tester@example.com')
        git(self.clone, 'config', 'core.autocrlf', 'false')
        (self.clone / 'collectors').mkdir()
        (self.clone / 'collectors' / 'hourly.py').write_text(STUB, encoding='utf-8')
        (self.clone / 'data').mkdir()
        (self.clone / 'data' / 'x.txt').write_text('base\n', encoding='utf-8')
        (self.clone / 'notes.txt').write_text('notes\n', encoding='utf-8')
        (self.clone / '.gitignore').write_text('logs/\n__pycache__/\n', encoding='utf-8')
        (self.clone / 'tools').mkdir()
        text = SCRIPT.read_text(encoding='utf-8').replace(OLD_ROOT, str(self.clone))
        self.assertNotIn('Crypto-Dashboard', text)
        (self.clone / 'tools' / 'run_hourly.ps1').write_text(text, encoding='utf-8')
        git(self.clone, 'add', '-A')
        git(self.clone, 'commit', '-m', 'initial')
        git(self.clone, 'push', 'origin', 'main')

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self):
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8'}
        return subprocess.run(
            [POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
             str(self.clone / 'tools' / 'run_hourly.ps1')],
            cwd=str(self.clone), capture_output=True, text=True, env=env, timeout=180)

    def log_text(self):
        return (self.clone / 'logs' / 'hourly.log').read_text(encoding='utf-8', errors='replace')

    def status(self):
        raw = (self.clone / 'logs' / 'sync-status.json').read_bytes()
        return json.loads(raw.decode('utf-8'))

    def remote_head(self):
        return git(self.remote, 'rev-parse', 'main').stdout.strip()

    def remote_file(self, name):
        return git(self.remote, 'show', 'main:' + name).stdout

    def rebase_in_progress(self):
        for name in ('rebase-merge', 'rebase-apply'):
            path = git(self.clone, 'rev-parse', '--git-path', name).stdout.strip()
            if (self.clone / path).exists():
                return True
        return False

    def test_clean_tree_pushes_and_records_success(self):
        before = self.remote_head()
        run = self.run_script()
        self.assertEqual(run.returncode, 0, self.log_text())
        self.assertNotEqual(self.remote_head(), before)
        self.assertIn('line1', self.remote_file('data/x.txt'))
        self.assertIs(self.status()['ok'], True)
        self.assertTrue(self.log_text().rstrip().endswith('=== run ok ==='))

    def test_rejected_push_exits_nonzero(self):
        hook = self.remote / 'hooks' / 'pre-receive'
        hook.write_bytes(b'#!/bin/sh\nexit 1\n')
        run = self.run_script()
        log = self.log_text()
        self.assertEqual(run.returncode, 1, log)
        self.assertIn('sync FAILED', log)
        self.assertFalse(log.rstrip().endswith('=== run ok ==='))
        self.assertIs(self.status()['ok'], False)

    def test_rebase_conflict_aborts_and_exits_nonzero(self):
        other = Path(self.temp.name) / 'other'
        subprocess.run(['git', 'clone', str(self.remote), str(other)], check=True, capture_output=True)
        git(other, 'config', 'user.name', 'other')
        git(other, 'config', 'user.email', 'other@example.com')
        (other / 'data' / 'x.txt').write_text('remote change\n', encoding='utf-8')
        git(other, 'commit', '-am', 'remote edit')
        git(other, 'push', 'origin', 'main')
        (self.clone / 'data' / 'x.txt').write_text('local change\n', encoding='utf-8')
        git(self.clone, 'commit', '-am', 'local edit')
        run = self.run_script()
        log = self.log_text()
        self.assertEqual(run.returncode, 1, log)
        self.assertIn('sync FAILED', log)
        self.assertFalse(self.rebase_in_progress())

    def test_dirty_code_tree_blocks_sync(self):
        before = self.remote_head()
        (self.clone / 'notes.txt').write_text('changed\n', encoding='utf-8')
        run = self.run_script()
        log = self.log_text()
        self.assertEqual(run.returncode, 1, log)
        self.assertIn('sync BLOCKED', log)
        self.assertEqual(self.remote_head(), before)

    def test_staged_code_is_never_committed(self):
        head = git(self.clone, 'rev-parse', 'HEAD').stdout.strip()
        (self.clone / 'notes.txt').write_text('staged change\n', encoding='utf-8')
        git(self.clone, 'add', 'notes.txt')
        run = self.run_script()
        self.assertEqual(run.returncode, 1, self.log_text())
        touched = git(self.clone, 'log', head + '..HEAD', '--name-only', '--format=').stdout
        self.assertNotIn('notes.txt', touched)
        self.assertIn('notes.txt', git(self.clone, 'diff', '--cached', '--name-only').stdout)

    def test_blocked_data_is_synced_after_code_is_resolved(self):
        (self.clone / 'notes.txt').write_text('changed\n', encoding='utf-8')
        first = self.run_script()
        self.assertEqual(first.returncode, 1, self.log_text())
        git(self.clone, 'checkout', '--', 'notes.txt')
        second = self.run_script()
        self.assertEqual(second.returncode, 0, self.log_text())
        lines = self.remote_file('data/x.txt').splitlines()
        self.assertIn('line1', lines)
        self.assertIn('line2', lines)


if __name__ == '__main__':
    unittest.main()
