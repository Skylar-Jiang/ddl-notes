"""Validate and merge metadata from the browser helper without touching manual tasks."""
import copy
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .model import SOURCE_HOSTS, Task, validate_source_url


@dataclass(frozen=True)
class SyncRecord:
    external_id: str
    title: str
    course: str = ''
    deadline: str | None = None
    completed: bool = False
    url: str | None = None


@dataclass(frozen=True)
class SyncBatch:
    source: str
    tasks: tuple[SyncRecord, ...]
    excluded_classroom_ids: tuple[str, ...] = ()


@dataclass
class SyncResult:
    tasks: list[Task]
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    removed: int = 0


def parse_sync(payload):
    if (not isinstance(payload, dict) or not {'version', 'source', 'tasks'} <= payload.keys() or
            payload.keys() - {'version', 'source', 'tasks', 'excluded_classroom_ids'} or
            type(payload['version']) is not int or payload['version'] != 1 or
            not isinstance(payload['source'], str) or payload['source'] not in SOURCE_HOSTS or
            not isinstance(payload['tasks'], list) or len(payload['tasks']) > 10000):
        raise ValueError('课程同步数据格式不正确。')
    excluded = payload.get('excluded_classroom_ids', [])
    if (not isinstance(excluded, list) or len(excluded) > 10000 or
            ('excluded_classroom_ids' in payload and payload['source'] != 'yuketang') or
            any(not isinstance(cid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', cid)
                for cid in excluded) or len(set(excluded)) != len(excluded)):
        raise ValueError('排除的雨课堂班级 ID 无效。')
    excluded = set(excluded)
    records = {}
    for item in payload['tasks']:
        if (not isinstance(item, dict) or not {'external_id', 'title'} <= item.keys() or
                item.keys() - {'external_id', 'title', 'course', 'deadline', 'completed', 'url'}):
            raise ValueError('课程任务字段不正确。')
        record = SyncRecord(**item)
        for name, limit in (('external_id', 450), ('title', 300), ('course', 300)):
            value = getattr(record, name)
            if (not isinstance(value, str) or len(value) > limit or
                    any(ord(c) < 32 for c in value) or (name != 'course' and not value.strip())):
                raise ValueError('课程任务名称或 ID 无效。')
        if type(record.completed) is not bool:
            raise ValueError('课程任务完成状态无效。')
        validate_source_url(payload['source'], record.url)
        deadline = record.deadline
        if deadline is not None:
            if not isinstance(deadline, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:00)?', deadline):
                raise ValueError('截止时间必须是精确到分钟的本地时间。')
            deadline = datetime.fromisoformat(deadline).isoformat()
        title = record.title.strip()
        course = record.course.strip()
        display = f'{course} · {title}' if course else title
        if len(display) > 300:
            raise ValueError('课程与任务名称合计不能超过 300 字。')
        record = SyncRecord(record.external_id.strip(), title, course, deadline, record.completed, record.url)
        if payload['source'] == 'yuketang' and record.external_id.split(':', 1)[0] in excluded:
            raise ValueError('同步任务与排除的班级冲突，请重新同步。')
        if record.external_id in records and records[record.external_id] != record:
            raise ValueError('同一来源任务包含冲突记录，请重新同步。')
        records[record.external_id] = record
    return SyncBatch(payload['source'], tuple(records.values()), tuple(sorted(excluded)))


def merge_sync(existing_tasks, payload, *, now=None):
    batch = parse_sync(payload)
    cutoff = (now if now is not None else datetime.now()) - timedelta(days=2)
    result = SyncResult(copy.deepcopy(existing_tasks))
    by_source = {}
    for task in result.tasks:
        if task.source_key:
            if task.source_key in by_source:
                raise ValueError('本地数据含有重复课程来源 ID。')
            by_source[task.source_key] = task
    expired_keys = set()
    for record in batch.tasks:
        key = f'{batch.source}:{record.external_id}'
        if record.deadline and datetime.fromisoformat(record.deadline) < cutoff:
            expired_keys.add(key)
            result.skipped += 1
            continue
        title = f'{record.course} · {record.title}' if record.course else record.title
        task = by_source.get(key)
        if task is None:
            if record.completed:
                continue
            task = Task.create(title, datetime.fromisoformat(record.deadline) if record.deadline else None,
                               source_key=key, source_url=record.url)
            result.tasks.append(task)
            by_source[key] = task
            result.added += 1
            continue
        old = copy.deepcopy(task)
        task.update(title=title, deadline=datetime.fromisoformat(record.deadline) if record.deadline else None,
                    description=task.description, reminder_minutes=task.reminder_minutes, color=task.color)
        task.source_url = record.url
        if record.completed:
            task.completed = True
            task.reminder.snoozed_until = None
        if task == old:
            result.unchanged += 1
        else:
            result.updated += 1
    excluded = set(batch.excluded_classroom_ids)
    retained = [task for task in result.tasks if not (
        task.source_key in expired_keys or
        (task.source_key and task.source_key.startswith('yuketang:') and
         task.source_key.split(':', 2)[1] in excluded) or
        (task.source_key and task.deadline and datetime.fromisoformat(task.deadline) < cutoff))]
    result.removed = len(result.tasks) - len(retained)
    result.tasks = retained
    return result
