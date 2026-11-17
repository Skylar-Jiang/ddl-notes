import unittest
import json
from datetime import datetime

from ddl_notes.model import Task, Settings
from ddl_notes.scheduler import acknowledge, due_events
from ddl_notes.storage import Store


class MonthlyTests(unittest.TestCase):
    def task(self, due=datetime(2026, 1, 31, 20), day=31):
        return Task.create('续费', due, monthly_day=day, description='订阅备注', reminder_minutes=0)

    def test_completion_advances_and_preserves_original_day(self):
        task = self.task()
        task.reminder.seen = ['deadline']
        task.advance_monthly(datetime(2026, 1, 31, 21), completed=True)
        self.assertEqual(task.deadline, '2026-02-28T20:00:00')
        self.assertFalse(task.completed)
        self.assertEqual(task.reminder.seen, [])
        task.advance_monthly(datetime(2026, 2, 28, 21), completed=True)
        self.assertEqual(task.deadline, '2026-03-31T20:00:00')
        self.assertEqual((task.monthly_day, task.description), (31, '订阅备注'))

    def test_early_completion_and_year_rollover(self):
        task = self.task(datetime(2026, 12, 20, 9), 20)
        task.advance_monthly(datetime(2026, 12, 1), completed=True)
        self.assertEqual(task.deadline, '2027-01-20T09:00:00')

    def test_missed_months_roll_to_current_month_and_remind_once(self):
        task = self.task()
        acknowledge(task, 'deadline', datetime(2026, 1, 31, 20))
        self.assertTrue(task.advance_monthly(datetime(2028, 2, 29, 21)))
        self.assertEqual(task.deadline, '2028-02-29T20:00:00')
        self.assertEqual(due_events([task], Settings(), datetime(2028, 2, 29, 21))[0].kind, 'deadline')
        acknowledge(task, 'deadline', datetime(2028, 2, 29, 21))
        self.assertFalse(task.advance_monthly(datetime(2028, 2, 29, 22)))
        self.assertEqual(due_events([task], Settings(), datetime(2028, 2, 29, 22)), [])

    def test_late_completion_skips_past_occurrences(self):
        task = self.task()
        task.advance_monthly(datetime(2026, 5, 31, 21), completed=True)
        self.assertEqual(task.deadline, '2026-06-30T20:00:00')

    def test_roll_forward_before_due_keeps_upcoming_reminder(self):
        task = self.task()
        self.assertTrue(task.advance_monthly(datetime(2026, 2, 1)))
        self.assertEqual(task.deadline, '2026-02-28T20:00:00')
        self.assertFalse(task.advance_monthly(datetime(2026, 1, 1)))

    def test_storage_roundtrip_and_legacy(self):
        task = self.task()
        content = json.dumps({'version': 1, 'tasks': [task.to_dict()]})
        restored = Store.decode(content.encode())[0][0]
        self.assertEqual(restored, task)
        legacy = Task.create('普通任务').to_dict()
        legacy.pop('monthly_day', None)
        self.assertIsNone(Task.from_dict(legacy).monthly_day)

    def test_invalid_monthly_configuration_rejected(self):
        for day in (0, 32, True, '20'):
            with self.subTest(day=day), self.assertRaises(ValueError):
                self.task(day=day)
        with self.assertRaises(ValueError):
            Task.create('没有时间', monthly_day=20)
        with self.assertRaises(ValueError):
            Task.create('平台作业', datetime(2026, 1, 20), monthly_day=20, source_key='yuketang:1:2')

