import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from ddl_notes.model import Task, Settings, sort_tasks, parse_deadline
from ddl_notes.scheduler import due_events, acknowledge, snooze
from ddl_notes.storage import Store


NOW = datetime(2026, 10, 20, 19, 0)


class ModelTests(unittest.TestCase):
    def test_input_validation(self):
        with self.assertRaises(ValueError):
            Task.create('  ')
        with self.assertRaises(ValueError):
            parse_deadline('2026-02-30', '20:00')
        self.assertEqual(parse_deadline('2026-10-20', '20:00'), NOW + timedelta(hours=1))
        with self.assertRaises(ValueError):
            Task.create('x', reminder_minutes=-1)

    def test_sort_deadlines_and_completed(self):
        tasks = [Task.create('plain'), Task.create('later', NOW + timedelta(days=1)),
                 Task.create('done', NOW - timedelta(days=2)),
                 Task.create('late', NOW - timedelta(days=1)), Task.create('soon', NOW)]
        tasks[2].completed = True
        self.assertEqual([t.title for t in sort_tasks(tasks, NOW)],
                         ['late', 'soon', 'later', 'plain', 'done'])

    def test_update_deadline_resets_reminders_only_when_changed(self):
        task = Task.create('x', NOW)
        task.reminder.seen = ['deadline']
        task.update(title='renamed', deadline=NOW, description='', reminder_minutes=None, color='mint')
        self.assertEqual(task.reminder.seen, ['deadline'])
        task.update(title='renamed', deadline=NOW + timedelta(hours=1), description='',
                    reminder_minutes=None, color='mint')
        self.assertEqual(task.reminder.seen, [])


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.task = Task.create('编译原理', NOW + timedelta(hours=1))

    def events(self, now=NOW):
        return due_events([self.task], self.settings, now)

    def test_not_before_threshold(self):
        self.assertEqual(self.events(NOW - timedelta(seconds=1)), [])

    def test_threshold_and_deduplication(self):
        event, = self.events()
        self.assertEqual(event.kind, 'upcoming')
        acknowledge(self.task, event.kind, NOW)
        self.assertEqual(self.events(NOW + timedelta(minutes=30)), [])

    def test_completed_and_no_deadline_never_remind(self):
        self.task.completed = True
        self.assertEqual(self.events(), [])
        self.assertEqual(due_events([Task.create('plain')], self.settings, NOW), [])

    def test_deadline_supersedes_missed_upcoming(self):
        event, = self.events(NOW + timedelta(hours=2))
        self.assertEqual(event.kind, 'deadline')
        acknowledge(self.task, event.kind, NOW + timedelta(hours=2))
        self.assertEqual(self.events(NOW + timedelta(days=1)), [])

    def test_snooze_and_deadline_priority(self):
        acknowledge(self.task, 'upcoming', NOW)
        snooze(self.task, NOW, 10)
        self.assertEqual(self.events(NOW + timedelta(minutes=9)), [])
        event, = self.events(NOW + timedelta(minutes=10))
        self.assertEqual(event.kind, 'snooze')
        acknowledge(self.task, event.kind, NOW + timedelta(minutes=10))
        self.assertEqual(self.events(NOW + timedelta(minutes=11)), [])
        snooze(self.task, NOW + timedelta(minutes=50), 30)
        self.assertEqual(self.events(NOW + timedelta(hours=1))[0].kind, 'deadline')

    def test_optional_repeat_is_bounded_by_interval(self):
        self.settings.repeat_enabled = True
        acknowledge(self.task, 'upcoming', NOW)
        self.assertEqual(self.events(NOW + timedelta(minutes=29)), [])
        event, = self.events(NOW + timedelta(minutes=30))
        self.assertEqual(event.kind, 'repeat')
        acknowledge(self.task, event.kind, NOW + timedelta(minutes=30))
        self.assertEqual(self.events(NOW + timedelta(minutes=31)), [])

    def test_per_task_override(self):
        self.task.reminder_minutes = 10
        self.assertEqual(self.events(), [])
        self.assertEqual(len(self.events(NOW + timedelta(minutes=50))), 1)

    def test_many_missed_tasks_return_one_batch(self):
        tasks = [Task.create(str(i), NOW) for i in range(30)]
        events = due_events(tasks, self.settings, NOW + timedelta(days=2))
        self.assertEqual(len(events), 30)
        self.assertTrue(all(e.kind == 'deadline' for e in events))
        for task in tasks:
            acknowledge(task, 'deadline', NOW)
        self.assertEqual(due_events(tasks, self.settings, NOW + timedelta(days=3)), [])

    def test_time_backwards_does_not_duplicate(self):
        acknowledge(self.task, 'upcoming', NOW)
        self.assertEqual(self.events(NOW - timedelta(hours=2)), [])
        self.assertEqual(self.events(), [])


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'data.json'
        self.store = Store(self.path)

    def test_save_restart_restores_all_state(self):
        task = Task.create('任务', NOW)
        acknowledge(task, 'deadline', NOW)
        snooze(task, NOW, 30)
        settings = Settings(topmost=True, opacity=0.9)
        self.store.save([task], settings)
        tasks, loaded = Store(self.path).load()
        self.assertEqual(tasks[0], task)
        self.assertEqual(loaded, settings)
        self.assertEqual(due_events(tasks, loaded, NOW), [])

    def test_missing_and_corrupt_data(self):
        self.assertEqual(self.store.load()[0], [])
        self.path.write_text('{broken', encoding='utf-8')
        with self.assertLogs(level='ERROR'):
            self.assertEqual(self.store.load()[0], [])
        self.assertTrue(self.store.warning)
        self.assertTrue(list(self.path.parent.glob('*.corrupt-*')))

    def test_backup_recovery(self):
        self.store.save([Task.create('first')], Settings())
        self.store.save([Task.create('second')], Settings())
        self.path.write_text('bad', encoding='utf-8')
        with self.assertLogs(level='ERROR'):
            self.assertEqual(self.store.load()[0][0].title, 'first')

    def test_invalid_import_does_not_replace_data(self):
        self.store.save([Task.create('keep')], Settings())
        invalid = self.path.parent / 'invalid.json'
        invalid.write_text(json.dumps({'version': 1, 'tasks': [{'title': ''}]}), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.store.read_import(invalid)
        self.assertEqual(self.store.load()[0][0].title, 'keep')

    def test_interrupted_replace_keeps_previous_file(self):
        self.store.save([Task.create('keep')], Settings())
        original = self.path.read_bytes()
        with patch('ddl_notes.storage.os.replace', side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError):
                self.store.save([Task.create('not committed')], Settings())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_export_import_and_duplicate_ids(self):
        task = Task.create('备份', NOW)
        self.store.save([task], Settings())
        tasks, _ = self.store.read_import(self.path)
        self.assertEqual(tasks, [task])
        payload = json.loads(self.path.read_text(encoding='utf-8'))
        payload['tasks'].append(payload['tasks'][0])
        self.path.write_text(json.dumps(payload), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.store.read_import(self.path)


if __name__ == '__main__':
    unittest.main()
