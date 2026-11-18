import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from ddl_notes.model import Task, Settings, remaining_text, sort_tasks
from ddl_notes.scheduler import due_events, acknowledge, snooze
from ddl_notes.course_sync import merge_sync

CHINA = timezone(timedelta(hours=8))
PACIFIC_WINTER = timezone(timedelta(hours=-8))
PACIFIC_SUMMER = timezone(timedelta(hours=-7))


class TimezoneTests(unittest.TestCase):
    def test_manual_and_imported_deadlines_share_beijing_instant(self):
        for source in (None, 'xiaoya:1:2', 'yuketang:1:2'):
            task = Task.create('作业', datetime(2026, 11, 20, 23, 59), source_key=source)
            self.assertEqual(task.deadline_instant(), datetime(2026, 11, 20, 15, 59, tzinfo=timezone.utc))
            self.assertEqual(task.deadline, '2026-11-20T23:59:00')

    def test_winter_and_summer_reminders_use_actual_instant(self):
        for month, local_zone, hour in ((1, PACIFIC_WINTER, 4), (7, PACIFIC_SUMMER, 5)):
            task = Task.create('作业', datetime(2027, month, 20, 20))
            now = datetime(2027, month, 20, hour-1, tzinfo=local_zone)
            event, = due_events([task], Settings(), now)
            self.assertEqual(event.kind, 'upcoming')
            self.assertEqual(remaining_text(task, now), '剩余 1 小时 0 分')
            acknowledge(task, 'upcoming', now)
            self.assertEqual(due_events([task], Settings(), now+timedelta(minutes=59)), [])
            self.assertEqual(due_events([task], Settings(), now+timedelta(hours=1))[0].kind, 'deadline')

    def test_timezone_change_does_not_replay_or_delay_snooze(self):
        task = Task.create('作业', datetime(2027, 1, 20, 20))
        now = datetime(2027, 1, 20, 19, tzinfo=CHINA)
        acknowledge(task, 'upcoming', now)
        snooze(task, now, 10)
        local_now = now.astimezone(PACIFIC_WINTER)
        self.assertEqual(due_events([task], Settings(), local_now+timedelta(minutes=9)), [])
        self.assertEqual(due_events([task], Settings(), local_now+timedelta(minutes=10))[0].kind, 'snooze')

    def test_dst_repeated_hour_does_not_lose_elapsed_time(self):
        task = Task.create('作业', datetime(2026, 11, 1, 19))
        first = datetime(2026, 11, 1, 1, 30, tzinfo=PACIFIC_SUMMER)
        acknowledge(task, 'upcoming', first)
        snooze(task, first, 60)
        second = datetime(2026, 11, 1, 1, 30, tzinfo=PACIFIC_WINTER)
        self.assertEqual(due_events([task], Settings(), second)[0].kind, 'snooze')

    def test_existing_tasks_migrate_without_changing_raw_dates_or_monthly_rules(self):
        ordinary = Task.create('作业', datetime(2026, 12, 20, 20)).to_dict()
        ordinary.pop('deadline_timezone', None)
        ordinary['reminder']['seen'] = ['upcoming', 'deadline']
        monthly = Task.create('续费', datetime(2026, 12, 20, 9), monthly_day=20).to_dict()
        monthly.pop('deadline_timezone', None)
        monthly['reminder']['seen'] = ['upcoming']
        with patch('ddl_notes.model.datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 11, 18, tzinfo=timezone.utc)
            task = Task.from_dict(ordinary)
        self.assertEqual(task.deadline, ordinary['deadline'])
        self.assertEqual(task.reminder.seen, [])
        self.assertEqual(task.deadline_timezone, 'Asia/Shanghai')
        repeat = Task.from_dict(monthly)
        self.assertEqual(repeat.deadline_timezone, 'local')
        self.assertEqual(repeat.reminder.seen, ['upcoming'])
        self.assertEqual(repeat.monthly_day, 20)
        acknowledge(task, 'deadline', datetime(2026, 12, 20, 20, tzinfo=CHINA))
        self.assertEqual(Task.from_dict(task.to_dict()), task)

    def test_migration_does_not_replay_already_notified_past_deadlines(self):
        data = Task.create('已提醒的旧作业', datetime(2020, 1, 1, 20)).to_dict()
        data.pop('deadline_timezone')
        data['reminder']['seen'] = ['upcoming', 'deadline']
        with patch('ddl_notes.model.datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 11, 18, tzinfo=timezone.utc)
            task = Task.from_dict(data)
        self.assertEqual(task.reminder.seen, ['upcoming', 'deadline'])

    def test_48_hour_cleanup_uses_elapsed_time_in_beijing(self):
        payload = {'version': 1, 'source': 'xiaoya', 'tasks': [
            {'external_id': 'boundary', 'title': '作业', 'deadline': '2026-11-18T20:00'},
            {'external_id': 'expired', 'title': '旧作业', 'deadline': '2026-11-18T19:59'}]}
        result = merge_sync([], payload, now=datetime(2026, 11, 20, 4, tzinfo=PACIFIC_WINTER))
        self.assertEqual([t.source_key for t in result.tasks], ['xiaoya:boundary'])
        self.assertEqual(result.skipped, 1)

    def test_mixed_clock_sort_and_monthly_stays_local(self):
        ordinary = Task.create('北京时间20点', datetime(2026, 11, 20, 20))
        monthly = Task.create('本地9点', datetime(2026, 11, 20, 9, tzinfo=PACIFIC_WINTER), monthly_day=20)
        now = datetime(2026, 11, 20, 0, tzinfo=PACIFIC_WINTER)
        self.assertEqual(sort_tasks([monthly, ordinary], now), [ordinary, monthly])
        self.assertEqual(monthly.deadline_timezone, 'local')

    def test_real_system_pacific_conversion_observes_future_dst(self):
        if (datetime(2027, 1, 20).astimezone().utcoffset() != timedelta(hours=-8) or
                datetime(2027, 7, 20).astimezone().utcoffset() != timedelta(hours=-7)):
            self.skipTest('This test checks the Windows Pacific timezone')
        winter = Task.create('冬季', datetime(2027, 1, 20, 20))
        summer = Task.create('夏季', datetime(2027, 7, 20, 20))
        self.assertEqual(winter.local_deadline(), datetime(2027, 1, 20, 4))
        self.assertEqual(summer.local_deadline(), datetime(2027, 7, 20, 5))
