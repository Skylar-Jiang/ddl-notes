import copy
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from ddl_notes.course_sync import merge_sync, parse_sync
from ddl_notes.model import ReminderState, Settings, Task
from ddl_notes.storage import Store


def record(**changes):
    item = {'external_id': 'course-1:task-1', 'title': '第一次作业', 'course': '数学',
            'deadline': '2026-10-21T20:00', 'completed': False,
            'url': 'https://nankai.ai-augmented.com/course/1/task/1'}
    item.update(changes)
    return item


def payload(*items, source='xiaoya'):
    return {'version': 1, 'source': source, 'tasks': list(items)}


class CourseSyncTests(unittest.TestCase):
    def setUp(self):
        clock = patch('ddl_notes.course_sync.datetime', wraps=datetime)
        self.addCleanup(clock.stop)
        clock.start().now.return_value = datetime(2026, 10, 20, 12)

    def test_removes_only_explicitly_excluded_rain_classrooms_without_deadlines(self):
        existing = [Task.create('旧课', source_key='yuketang:10:1'),
                    Task.create('本学期未返回的任务', source_key='yuketang:100:1'),
                    Task.create('未知学期', source_key='yuketang:20:1'),
                    Task.create('小雅', source_key='xiaoya:10:1'), Task.create('手动')]
        before = copy.deepcopy(existing)
        batch = {**payload(source='yuketang'), 'excluded_classroom_ids': ['10']}
        result = merge_sync(existing, batch)
        self.assertEqual(result.tasks, existing[1:])
        self.assertEqual(result.removed, 1)
        self.assertEqual(existing, before)
        self.assertEqual(merge_sync(result.tasks, batch).removed, 0)

    def test_rejects_invalid_or_conflicting_classroom_exclusions_before_cleanup(self):
        original = Task.create('旧课', source_key='yuketang:10:1')
        for excluded in (None, {}, '10', [10], [''], ['10:1'], ['10', '10'], ['1'] * 10001):
            with self.subTest(excluded_type=type(excluded).__name__):
                with self.assertRaises(ValueError):
                    merge_sync([original], {**payload(source='yuketang'),
                                           'excluded_classroom_ids': excluded})
        with self.assertRaises(ValueError):
            parse_sync({**payload(), 'excluded_classroom_ids': ['10']})
        with self.assertRaises(ValueError):
            parse_sync({**payload(record(external_id='10:1', url=None), source='yuketang'),
                        'excluded_classroom_ids': ['10']})
        self.assertIsNone(original.deadline)

    def test_skips_new_imports_only_when_more_than_48_hours_overdue(self):
        now = datetime(2026, 10, 20, 20)
        cutoff = now - timedelta(days=2)
        result = merge_sync([], payload(
            record(external_id='old', deadline=(cutoff-timedelta(minutes=1)).isoformat()),
            record(external_id='boundary', deadline=cutoff.isoformat()),
            record(external_id='recent', deadline=(cutoff+timedelta(minutes=1)).isoformat()),
            record(external_id='no-deadline', deadline=None)), now=now)
        self.assertEqual([t.source_key for t in result.tasks], [
            'xiaoya:boundary', 'xiaoya:recent', 'xiaoya:no-deadline'])
        self.assertEqual((result.added, result.skipped, result.removed), (3, 1, 0))

    def test_removes_expired_imports_but_keeps_manual_tasks_and_no_deadline(self):
        now = datetime(2026, 10, 20, 20)
        old = now-timedelta(days=3)
        manual = Task.create('手动旧任务', old)
        imported = Task.create('旧导入', old, source_key='xiaoya:old')
        completed = Task.create('已完成的旧导入', old, source_key='yuketang:old')
        completed.completed = True
        no_deadline = Task.create('无截止', source_key='yuketang:undated')
        existing = [manual, imported, completed, no_deadline]
        before = copy.deepcopy(existing)
        result = merge_sync(existing, payload(), now=now)
        self.assertEqual(result.tasks, [manual, no_deadline])
        self.assertEqual(result.removed, 2)
        self.assertEqual(existing, before)

    def test_extended_deadline_preserves_existing_import_before_cleanup(self):
        now = datetime(2026, 10, 20, 20)
        existing = Task.create('已导入', now-timedelta(days=3),
                               source_key='xiaoya:course-1:task-1', description='保留笔记')
        result = merge_sync([existing], payload(record(deadline='2026-10-25T20:00')), now=now)
        self.assertEqual(result.removed, 0)
        self.assertEqual(result.tasks[0].id, existing.id)
        self.assertEqual(result.tasks[0].description, '保留笔记')

    def test_remote_expired_deadline_removes_existing_import_even_if_local_deadline_was_future(self):
        now = datetime(2026, 10, 20, 20)
        existing = Task.create('已导入', now+timedelta(days=3), source_key='xiaoya:course-1:task-1')
        result = merge_sync([existing], payload(record(deadline='2026-10-17T20:00')), now=now)
        self.assertEqual(result.tasks, [])
        self.assertEqual((result.removed, result.skipped), (1, 1))

    def test_adds_course_title_and_stable_source_identity(self):
        result = merge_sync([], payload(record()))
        self.assertEqual((result.added, result.updated, result.unchanged), (1, 0, 0))
        task, = result.tasks
        self.assertEqual(task.title, '数学 · 第一次作业')
        self.assertEqual(task.source_key, 'xiaoya:course-1:task-1')
        self.assertEqual(task.source_url, record()['url'])
        self.assertEqual(task.deadline, '2026-10-21T20:00:00')

    def test_defaults_allow_no_course_deadline_or_link(self):
        task, = merge_sync([], payload({'external_id': '1', 'title': '作业'})).tasks
        self.assertEqual(task.title, '作业')
        self.assertIsNone(task.deadline)
        self.assertIsNone(task.source_url)
        self.assertFalse(task.completed)

    def test_repeat_and_restart_do_not_duplicate_or_reset_reminders(self):
        task, = merge_sync([], payload(record())).tasks
        task.reminder = ReminderState(['upcoming'], '2026-10-21T19:30:00',
                                      '2026-10-21T19:00:00')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.json'
            Store(path).save([task], Settings())
            restarted, _ = Store(path).load()
        result = merge_sync(restarted, payload(record()))
        self.assertEqual((result.added, result.updated, result.unchanged), (0, 0, 1))
        self.assertEqual(result.tasks, [task])
        self.assertIsNot(result.tasks[0], restarted[0])

    def test_changed_deadline_resets_reminders_and_preserves_user_fields(self):
        task, = merge_sync([], payload(record())).tasks
        task.description = '我的笔记'
        task.color = 'mint'
        task.reminder_minutes = 45
        task.reminder.seen = ['upcoming']
        before = copy.deepcopy(task)
        changed = record(title='更正的作业', course='高数', deadline='2026-10-22T18:30',
                         url='https://nankai.ai-augmented.com/course/1/task/2')
        result = merge_sync([task], payload(changed))
        updated, = result.tasks
        self.assertEqual((result.added, result.updated, result.unchanged), (0, 1, 0))
        self.assertEqual(updated.id, task.id)
        self.assertEqual(updated.title, '高数 · 更正的作业')
        self.assertEqual(updated.deadline, '2026-10-22T18:30:00')
        self.assertEqual(updated.description, '我的笔记')
        self.assertEqual((updated.color, updated.reminder_minutes), ('mint', 45))
        self.assertEqual(updated.reminder, ReminderState())
        self.assertEqual(task, before)

    def test_title_only_update_preserves_reminder_and_can_clear_deadline(self):
        task, = merge_sync([], payload(record())).tasks
        task.reminder.seen = ['upcoming']
        updated, = merge_sync([task], payload(record(title='新名称'))).tasks
        self.assertEqual(updated.reminder.seen, ['upcoming'])
        cleared, = merge_sync([updated], payload(record(deadline=None))).tasks
        self.assertIsNone(cleared.deadline)
        self.assertEqual(cleared.reminder.seen, [])

    def test_manual_and_missing_imported_tasks_are_untouched(self):
        manual = Task.create('数学 · 第一次作业', datetime(2026, 10, 21, 20))
        other = merge_sync([], payload(record(external_id='other'))).tasks[0]
        original = copy.deepcopy([manual, other])
        result = merge_sync([manual, other], payload(record()))
        self.assertEqual(result.tasks[:2], original)
        self.assertEqual(len(result.tasks), 3)
        result.tasks[0].reminder.seen.append('upcoming')
        self.assertEqual(manual.reminder.seen, [])

    def test_sources_and_course_task_keys_do_not_collide(self):
        tasks = merge_sync([], payload(record(), record(external_id='course-2:task-1'))).tasks
        result = merge_sync(tasks, payload(record(url='https://changjiang.yuketang.cn/task/1'),
                                            source='yuketang'))
        self.assertEqual(len(result.tasks), 3)
        self.assertEqual(result.added, 1)
        self.assertEqual(len({task.source_key for task in result.tasks}), 3)

    def test_completed_new_tasks_are_skipped(self):
        result = merge_sync([], payload(record(completed=True)))
        self.assertEqual(result.tasks, [])
        self.assertEqual(result.added, 0)

    def test_remote_completion_and_local_completion_are_monotonic(self):
        task, = merge_sync([], payload(record())).tasks
        result = merge_sync([task], payload(record(completed=True)))
        self.assertTrue(result.tasks[0].completed)
        self.assertEqual(result.updated, 1)
        reopened = merge_sync(result.tasks, payload(record(completed=False)))
        self.assertTrue(reopened.tasks[0].completed)
        self.assertEqual((reopened.updated, reopened.unchanged), (0, 1))

    def test_identical_duplicate_records_are_deduplicated(self):
        result = merge_sync([], payload(record(), record()))
        self.assertEqual(result.added, 1)

    def test_conflicting_duplicate_records_reject_entire_batch(self):
        with self.assertRaises(ValueError):
            merge_sync([], payload(record(), record(title='不同名称')))

    def test_malformed_later_record_does_not_mutate_existing_task(self):
        task, = merge_sync([], payload(record())).tasks
        before = copy.deepcopy(task)
        with self.assertRaises(ValueError):
            merge_sync([task], payload(record(title='changed'), record(external_id='2', title='')))
        self.assertEqual(task, before)

    def test_duplicate_existing_source_keys_are_rejected(self):
        first, = merge_sync([], payload(record())).tasks
        second = copy.deepcopy(first)
        second.id = 'second'
        with self.assertRaises(ValueError):
            merge_sync([first, second], payload(record()))

    def test_invalid_envelopes(self):
        for invalid in (None, [], {}, payload(source='unknown'),
                        {**payload(), 'version': True}, {**payload(), 'version': 2},
                        {**payload(), 'tasks': {}}, {**payload(), 'source': []},
                        payload(*[record()] * 10001)):
            with self.subTest(invalid_type=type(invalid).__name__):
                with self.assertRaises(ValueError):
                    parse_sync(invalid)

    def test_invalid_record_types_and_lengths(self):
        for invalid in (None, [], record(external_id=None), record(external_id=''),
                        record(external_id=' '), record(external_id=4), record(title=True),
                        record(title=''), record(title='x' * 301), record(course=[]),
                        record(course=None), record(course='x' * 301), record(completed=1),
                        record(deadline=123), record(url=5)):
            with self.subTest(record=invalid):
                with self.assertRaises(ValueError):
                    parse_sync(payload(invalid))

    def test_rejects_untrusted_and_wrong_source_urls(self):
        for url in ('http://nankai.ai-augmented.com/task/1', 'javascript:alert(1)',
                    'https://evil.test/task/1', 'https://nankai.ai-augmented.com.evil.test/',
                    'https://nankai.ai-augmented.com@evil.test/',
                    'https://user@nankai.ai-augmented.com/',
                    'https://nankai.ai-augmented.com:444/',
                    'https://changjiang.yuketang.cn/task/1', ''):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    parse_sync(payload(record(url=url)))

    def test_rejects_ambiguous_invalid_and_timezone_deadlines(self):
        for deadline in ('2026-10-21', '20261021T2000', '2026-10-21T20:00Z',
                         '2026-10-21T20:00+08:00', '2026-10-21T20:00:01',
                         '2026-10-21T20:00:00.123', '2026-02-30T20:00', ''):
            with self.subTest(deadline=deadline):
                with self.assertRaises(ValueError):
                    parse_sync(payload(record(deadline=deadline)))

    def test_accepts_local_minute_precision_in_both_persisted_formats(self):
        first = merge_sync([], payload(record())).tasks
        result = merge_sync(first, payload(record(deadline='2026-10-21T20:00:00')))
        self.assertEqual(result.unchanged, 1)

    def test_legacy_tasks_roundtrip_without_sync_fields(self):
        original = Task.create('manual')
        data = original.to_dict()
        data.pop('source_key', None)
        data.pop('source_url', None)
        loaded = Task.from_dict(data)
        self.assertIsNone(loaded.source_key)
        self.assertIsNone(loaded.source_url)

    def test_model_rejects_invalid_sync_metadata(self):
        for metadata in ({'source_key': 1}, {'source_key': 'unknown:1'},
                         {'source_key': 'xiaoya:'}, {'source_key': 'xiaoya: '},
                         {'source_url': 'https://nankai.ai-augmented.com/'},
                         {'source_key': 'xiaoya:1', 'source_url': 'https://evil.test/'},
                         {'source_key': 'xiaoya:1', 'source_url': 'https://changjiang.yuketang.cn/'}):
            with self.subTest(metadata=metadata):
                with self.assertRaises(ValueError):
                    Task.create('invalid', **metadata)


if __name__ == '__main__':
    unittest.main()
