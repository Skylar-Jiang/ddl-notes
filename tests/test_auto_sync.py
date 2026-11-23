import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ddl_notes.model import Settings
from ddl_notes.auto_sync import AutoSync
from ddl_notes.session_store import seal, unseal
from ddl_notes.background_browser import load_session


class FakeProcess:
    pid = 987654321
    returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0


class AutoSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 0
        self.calls = []
        self.process = FakeProcess()

        def launch(command, **kwargs):
            self.calls.append(command)
            return self.process

        self.manager = AutoSync(Path(self.temp.name), launch=launch, clock=lambda: self.now)
        self.addCleanup(self.manager.close)
        self.settings = Settings(auto_sync_enabled=True, auto_sync_minutes=30)

    def finish(self, results):
        self.manager.status_path.write_text(json.dumps({'stage': 'done', 'results': results}), encoding='utf-8')
        self.process.returncode = 0
        self.manager.poll(self.settings)

    def test_opt_in_and_interval_survive_settings_roundtrip(self):
        self.assertFalse(Settings().auto_sync_enabled)
        self.assertEqual(Settings(**self.settings.__dict__), self.settings)
        for change in ({'auto_sync_minutes': 0}, {'auto_sync_minutes': True},
                       {'auto_sync_enabled': 1}, {'sync_xiaoya': 'yes'},
                       {'auto_sync_enabled': True, 'sync_xiaoya': False, 'sync_yuketang': False}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(Settings(), **change)

    def test_disabled_never_launches_and_enabled_runs_without_browser_tab(self):
        self.manager.poll(Settings())
        self.assertEqual(self.calls, [])
        self.manager.configure(self.settings)
        self.now = 5
        self.manager.poll(self.settings)
        self.assertEqual(len(self.calls), 1)
        self.assertIn('--action', self.calls[0])
        self.assertIn('sync', self.calls[0])
        self.assertNotIn('--password', self.calls[0])
        self.manager.poll(self.settings)
        self.assertEqual(len(self.calls), 1)

    def test_completed_job_waits_for_interval_and_sleep_causes_only_one_run(self):
        self.manager.start('sync', ['xiaoya'])
        self.finish([{'source': 'xiaoya', 'ok': True, 'message': '已发送'}])
        self.now = 1799
        self.manager.poll(self.settings)
        self.assertEqual(len(self.calls), 1)
        self.now = 10000
        self.process = FakeProcess()
        self.manager.poll(self.settings)
        self.manager.poll(self.settings)
        self.assertEqual(len(self.calls), 2)

    def test_login_expiry_pauses_affected_platform_until_login(self):
        self.manager.start('sync', ['xiaoya', 'yuketang'])
        self.finish([{'source': 'xiaoya', 'ok': False, 'needs_login': True, 'message': '请登录'},
                     {'source': 'yuketang', 'ok': True, 'message': '已发送'}])
        self.assertEqual(self.manager.needs_login, {'xiaoya'})
        self.now = 2000
        self.process = FakeProcess()
        self.manager.poll(self.settings)
        self.assertIn('yuketang', self.calls[-1])
        self.assertNotIn('xiaoya', self.calls[-1])
        self.finish([{'source': 'yuketang', 'ok': True, 'message': '已发送'}])
        self.process = FakeProcess()
        self.manager.start('login', ['xiaoya'])
        self.finish([{'source': 'xiaoya', 'ok': True, 'message': '登录已保存'}])
        self.assertNotIn('xiaoya', self.manager.needs_login)

    def test_worker_crash_does_not_loop_or_modify_tasks(self):
        self.manager.start('sync', ['xiaoya'])
        self.process.returncode = 1
        self.manager.poll(self.settings)
        self.assertIn('退出', self.manager.status)
        self.assertFalse(list(Path(self.temp.name).glob('inbox/*.json')))
        self.manager.poll(self.settings)
        self.assertEqual(len(self.calls), 1)

    def test_own_worker_receives_shutdown_signal(self):
        self.manager.start('login', ['xiaoya'])
        cancel = self.manager.job_directory / 'cancel'
        self.manager.close()
        self.assertTrue(cancel.exists())

    def test_invalid_sources_and_overlap_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.start('sync', ['evil'])
        self.manager.start('sync', ['xiaoya'])
        with self.assertRaises(ValueError):
            self.manager.start('login', ['xiaoya'])

    def test_session_state_is_protected_for_current_windows_user(self):
        value = b'{"cookies":["test-secret-not-a-real-login"]}'
        protected = seal(value)
        self.assertNotIn(b'test-secret', protected)
        self.assertEqual(unseal(protected), value)

    def test_invalid_session_state_allows_clean_relogin(self):
        path = Path(self.temp.name)/'invalid.bin'
        path.write_bytes(b'invalid-session')
        self.assertIsNone(load_session(path))
