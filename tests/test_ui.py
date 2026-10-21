"""Real Tk widgets with temporary user data; no changes to the user's tasks/startup."""
import tempfile
import ctypes
import os
import time
import tkinter as tk
import unittest
from datetime import datetime, timedelta
from pathlib import Path
import json
from unittest.mock import patch

from ddl_notes.app import App
from ddl_notes.model import Task
from ddl_notes.storage import Store
from ddl_notes.windows import Tray
from ddl_notes.widgets import RoundedCard


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk()
        self.app = App(self.root, Store(Path(self.temp.name) / 'data.json'), with_tray=False)
        self.root.update()
        self.addCleanup(self.close)

    def close(self):
        try:
            if self.root.winfo_exists():
                self.app.quit()
        except tk.TclError:
            pass

    def test_exit_cancels_all_owned_timers(self):
        form = self.app.open_editor()
        form.window.destroy()
        self.app.remember_geometry()
        self.app.quit()
        self.assertFalse(self.root.tk.call('after', 'info'))

    def test_create_edit_complete_and_restart(self):
        form = self.app.open_editor()
        self.root.update()
        form.title_var.set('真实 GUI 任务')
        form.has_deadline.set(True)
        form.date_var.set('2026-12-20')
        form.time_var.set('20:00')
        form.save()
        self.root.update()
        self.assertEqual(self.app.tasks[0].title, '真实 GUI 任务')
        form = self.app.open_editor(self.app.tasks[0])
        form.title_var.set('已编辑')
        form.save()
        self.app.toggle_task(self.app.tasks[0])
        tasks, _ = self.app.store.load()
        self.assertEqual(tasks[0].title, '已编辑')
        self.assertTrue(tasks[0].completed)

    def test_bad_input_stays_in_editor(self):
        form = self.app.open_editor()
        form.title_var.set('test')
        form.has_deadline.set(True)
        form.date_var.set('2026-02-30')
        form.save()
        self.assertTrue(form.window.winfo_exists())
        self.assertTrue(form.error_var.get())
        self.assertEqual(self.app.tasks, [])
        form.window.destroy()

    def test_task_colors_alternate_after_sorting_filtering_and_theme_changes(self):
        self.app.tasks = [Task.create(str(i), datetime.now() + timedelta(days=10-i), color='mint')
                          for i in range(9)]
        self.app.tasks[3].completed = True
        for theme in ('light', 'dark'):
            self.app.settings.theme = theme
            self.app.apply_appearance()
            for mode in ('deadline', 'created'):
                self.app.settings.sort_by = mode
                for show_completed in (False, True):
                    with self.subTest(theme=theme, mode=mode, show_completed=show_completed):
                        self.app.settings.show_completed = show_completed
                        self.app.render_tasks()
                        cards = [w for w in self.app.area.inner.winfo_children() if isinstance(w, RoundedCard)]
                        self.assertEqual(len(cards), 9 if show_completed else 8)
                        self.assertTrue(all(a.fill != b.fill for a, b in zip(cards, cards[1:])))

    def test_task_editor_has_no_manual_color_picker(self):
        form = self.app.open_editor()
        pending = [form.body]
        while pending:
            widget = pending.pop()
            self.assertNotIsInstance(widget, tk.Radiobutton)
            pending.extend(widget.winfo_children())
        form.window.destroy()

    def test_browser_sync_inbox_merges_without_replacing_manual_tasks(self):
        self.app.tasks = [Task.create('手动任务')]
        inbox = self.app.store.path.parent / 'inbox'
        inbox.mkdir()
        payload = {'version': 1, 'source': 'yuketang', 'tasks': [
            {'external_id': '1:2', 'title': '第一次作业', 'course': '数据库',
             'deadline': '2027-01-01T20:00'}]}
        file = inbox / 'batch.json'
        file.write_text(json.dumps(payload), encoding='utf-8')
        self.app.consume_sync()
        self.assertFalse(file.exists())
        self.assertEqual([t.title for t in self.app.tasks], ['手动任务', '数据库 · 第一次作业'])
        file.write_text(json.dumps(payload), encoding='utf-8')
        self.app.consume_sync()
        self.assertEqual(len(self.app.tasks), 2)
        self.assertEqual(len(self.app.store.load()[0]), 2)

    def test_invalid_sync_file_is_preserved_without_retry_storm(self):
        inbox = self.app.store.path.parent / 'inbox'
        inbox.mkdir()
        file = inbox / 'broken.json'
        file.write_text('{bad', encoding='utf-8')
        with self.assertLogs(level='WARNING'):
            self.app.consume_sync()
        self.assertEqual(self.app.tasks, [])
        self.assertTrue(file.with_suffix('.failed').exists())
        self.app.consume_sync()

    def test_sync_cleans_expired_imports_with_a_separate_recovery_backup(self):
        old = Task.create('过期导入', datetime.now()-timedelta(days=3), source_key='yuketang:old')
        manual = Task.create('手动旧任务', datetime.now()-timedelta(days=3))
        manual.completed = True
        self.app.tasks = [old, manual]
        self.app.store.save(self.app.tasks, self.app.settings)
        inbox = self.app.store.path.parent / 'inbox'
        inbox.mkdir()
        (inbox / 'empty.json').write_text(json.dumps({'version': 1, 'source': 'yuketang', 'tasks': []}), encoding='utf-8')
        self.app.consume_sync()
        self.assertEqual(self.app.tasks, [manual])
        self.assertEqual(self.app.store.load()[0], [manual])
        backup, = self.app.store.path.parent.glob('before-sync-cleanup-*.json')
        self.assertEqual(Store(backup).load()[0], [old, manual])
        self.assertIn('清理 1', self.app.sync_status.get())

    def test_expired_imports_are_kept_if_cleanup_backup_cannot_be_saved(self):
        old = Task.create('过期导入', datetime.now()-timedelta(days=3), source_key='yuketang:old')
        self.app.tasks = [old]
        self.app.store.save(self.app.tasks, self.app.settings)
        inbox = self.app.store.path.parent / 'inbox'
        inbox.mkdir()
        (inbox / 'empty.json').write_text(json.dumps({'version': 1, 'source': 'yuketang', 'tasks': []}), encoding='utf-8')
        with patch.object(self.app.store, 'export', side_effect=OSError('disk full')):
            with self.assertLogs(level='WARNING'):
                self.app.consume_sync()
        self.assertEqual(self.app.tasks, [old])
        self.assertEqual(self.app.store.load()[0], [old])

    def test_sync_removes_old_semester_without_deadline_and_backs_up_first(self):
        old = Task.create('旧学期无截止任务', source_key='yuketang:10:1')
        current = Task.create('本学期无截止任务', source_key='yuketang:20:1')
        self.app.tasks = [old, current]
        self.app.store.save(self.app.tasks, self.app.settings)
        inbox = self.app.store.path.parent / 'inbox'
        inbox.mkdir()
        (inbox / 'semester.json').write_text(json.dumps({
            'version': 1, 'source': 'yuketang', 'tasks': [],
            'excluded_classroom_ids': ['10']}), encoding='utf-8')
        self.app.consume_sync()
        self.assertEqual(self.app.tasks, [current])
        self.assertEqual(self.app.store.load()[0], [current])
        backup, = self.app.store.path.parent.glob('before-sync-cleanup-*.json')
        self.assertEqual(Store(backup).load()[0], [old, current])
        self.assertFalse(list(inbox.glob('*.json')))

    def test_sync_cleanup_failure_does_not_undo_saved_tasks(self):
        inbox = self.app.store.path.parent / 'inbox'
        inbox.mkdir()
        file = inbox / 'batch.json'
        file.write_text(json.dumps({'version': 1, 'source': 'xiaoya', 'tasks': [
            {'external_id': '1', 'title': '作业'}]}), encoding='utf-8')
        with patch.object(Path, 'unlink', side_effect=OSError('busy')):
            with self.assertLogs(level='WARNING'):
                self.app.consume_sync()
        self.assertEqual(len(self.app.tasks), 1)
        self.assertEqual(self.app.tasks, self.app.store.load()[0])
        self.app.consume_sync()
        self.assertEqual(len(self.app.tasks), 1)

    def test_dialog_footer_controls_are_not_clipped(self):
        for form in (self.app.open_editor(), self.app.open_settings(), self.app.open_course_sync()):
            self.root.update()
            footer = form.body.winfo_children()[-1]
            for button in footer.winfo_children():
                self.assertGreaterEqual(button.winfo_height(), button.winfo_reqheight())
            form.window.destroy()

    @unittest.skipUnless(os.name == 'nt', 'Windows native coordinates')
    def test_negative_saved_x_restores_at_native_coordinate(self):
        self.app.settings.x = -100
        self.app.store.save([], self.app.settings)
        root = tk.Toplevel(self.root)
        other_app = App(root, self.app.store, with_tray=False)
        try:
            root.update()
            self.assertAlmostEqual(root.winfo_x(), -100, delta=8)
        finally:
            other_app.quit()

    def test_collapsed_geometry_and_topmost(self):
        self.app.toggle_collapse()
        self.root.update()
        self.assertLess(self.root.winfo_height(), 100)
        self.app.toggle_collapse()
        self.root.update()
        self.assertGreaterEqual(self.root.winfo_height(), 320)
        self.app.toggle_pin()
        self.root.update()
        self.assertTrue(self.root.attributes('-topmost'))

    def test_native_style_preserves_requested_client_size(self):
        self.assertAlmostEqual(self.root.winfo_height(), self.app.px(450), delta=2)
        for _ in range(3):
            self.app.show()
            self.root.update()
        self.assertAlmostEqual(self.root.winfo_height(), self.app.px(450), delta=2)

    def test_one_alarm_for_batch_and_completion_closes_it(self):
        self.app.tasks = [Task.create(str(i), datetime.now() - timedelta(minutes=5)) for i in range(12)]
        self.app.check_reminders()
        self.root.update()
        alarm = self.app.alarm
        self.assertIsNotNone(alarm)
        self.assertEqual(len(alarm.task_ids), 12)
        self.app.check_reminders()
        self.assertIs(self.app.alarm, alarm)
        for task in self.app.tasks:
            self.app.toggle_task(task)
        self.root.update()
        self.assertIsNone(self.app.alarm)

    def test_hidden_main_still_shows_alarm(self):
        self.root.withdraw()
        self.app.tasks = [Task.create('hidden reminder', datetime.now() - timedelta(minutes=1))]
        self.app.check_reminders()
        self.root.update()
        self.assertEqual(self.root.state(), 'withdrawn')
        self.assertTrue(self.app.alarm.window.winfo_viewable())
        self.assertTrue(self.app.alarm.window.attributes('-topmost'))

    @unittest.skipUnless(os.name == 'nt', 'Windows focus behavior')
    def test_alarm_preserves_foreground_and_main_topmost(self):
        other = tk.Toplevel(self.root)
        other.title('Focus test surface')
        other.update()
        other.focus_force()
        self.root.update()
        before = ctypes.windll.user32.GetForegroundWindow()
        self.app.tasks = [Task.create('test alarm', datetime.now() - timedelta(minutes=1))]
        self.app.check_reminders()
        self.root.update()
        self.assertEqual(ctypes.windll.user32.GetForegroundWindow(), before)
        self.assertFalse(self.root.attributes('-topmost'))
        self.app.alarm.close()
        self.assertFalse(self.root.attributes('-topmost'))
        other.destroy()

    def test_close_hides_and_show_restores_with_ready_tray(self):
        class ReadyTray:
            ready = True
            def stop(self):
                pass
        self.app.tray = ReadyTray()
        self.app.request_close()
        self.root.update()
        self.assertEqual(self.root.state(), 'withdrawn')
        self.app.show()
        self.root.update()
        self.assertEqual(self.root.state(), 'normal')

    @unittest.skipUnless(os.name == 'nt', 'Windows notification area')
    def test_actual_tray_open_action_and_worker_exit(self):
        self.app.tray = Tray(self.app.queue)
        self.app.tray.start()
        end = time.monotonic() + 5
        while not self.app.tray.ready and time.monotonic() < end:
            self.root.update()
            time.sleep(0.02)
        self.assertTrue(self.app.tray.ready)
        self.app.request_close()
        self.assertEqual(self.root.state(), 'withdrawn')
        self.app.tray.icon.menu.items[0](self.app.tray.icon)
        self.app.poll_queue()
        self.root.update()
        self.assertEqual(self.root.state(), 'normal')
        tray_thread = self.app.tray.thread
        self.app.quit()
        self.assertFalse(tray_thread.is_alive())

    def test_settings_save_and_theme(self):
        class TestStartup:
            def enabled(self):
                return False
            def disable(self):
                pass
        self.app.startup = TestStartup()
        form = self.app.open_settings()
        self.root.update()
        form.advance_var.set('30')
        form.theme_var.set('dark')
        form.opacity_var.set(90)
        form.save()
        self.root.update()
        self.assertEqual(self.app.settings.reminder_minutes, 30)
        self.assertEqual(self.app.settings.theme, 'dark')
        self.assertAlmostEqual(self.root.attributes('-alpha'), 0.9, places=1)
