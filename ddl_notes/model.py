"""Local wall-clock times are stored without timezone offsets, to minute precision."""
from dataclasses import asdict, dataclass, field
from datetime import datetime
from uuid import uuid4
from urllib.parse import urlsplit
import re


COLORS = ('lavender', 'peach', 'mint', 'blue', 'butter')
SOURCE_HOSTS = {'xiaoya': 'nankai.ai-augmented.com', 'yuketang': 'changjiang.yuketang.cn'}


def validate_source_url(source, url):
    if url is None:
        return
    if not isinstance(url, str) or len(url) > 2000 or any(ord(c) < 32 for c in url):
        raise ValueError('课程来源链接无效。')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != SOURCE_HOSTS.get(source) or
            parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError('课程来源链接与平台不符。')


def parse_deadline(date_text, time_text):
    try:
        return datetime.strptime(f'{date_text.strip()} {time_text.strip()}', '%Y-%m-%d %H:%M')
    except ValueError as exc:
        raise ValueError('请输入有效日期和时间，例如 2026-10-20、20:00。') from exc


def local_datetime(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is not None:
        raise ValueError('日期时间应采用系统本地时间，不带时区偏移。')
    return result


@dataclass
class ReminderState:
    seen: list[str] = field(default_factory=list)
    snoozed_until: str | None = None
    last_notified: str | None = None


@dataclass
class Task:
    id: str
    title: str
    created_at: str
    deadline: str | None = None
    description: str = ''
    completed: bool = False
    reminder_minutes: int | None = None
    color: str = 'lavender'
    reminder: ReminderState = field(default_factory=ReminderState)
    source_key: str | None = None
    source_url: str | None = None

    def __post_init__(self):
        if self.source_key is not None:
            if (not isinstance(self.source_key, str) or len(self.source_key) > 500 or
                    not re.fullmatch(r'(xiaoya|yuketang):\S[^\x00-\x1f]*', self.source_key)):
                raise ValueError('课程任务来源 ID 无效。')
            validate_source_url(self.source_key.split(':', 1)[0], self.source_url)
        elif self.source_url is not None:
            raise ValueError('课程来源链接缺少来源 ID。')
        if not isinstance(self.title, str) or not self.title.strip() or len(self.title) > 300:
            raise ValueError('任务名称不能为空，且最多 300 个字符。')
        self.title = self.title.strip()
        if not isinstance(self.id, str) or not self.id or len(self.id) > 100:
            raise ValueError('任务 ID 无效。')
        if not isinstance(self.description, str) or len(self.description) > 5000:
            raise ValueError('描述最多 5000 个字符。')
        if type(self.completed) is not bool or self.color not in COLORS:
            raise ValueError('任务状态或颜色无效。')
        if self.reminder_minutes is not None and (
                type(self.reminder_minutes) is not int or not 0 <= self.reminder_minutes <= 525600):
            raise ValueError('提前提醒应为 0 至 525600 分钟的整数。')
        local_datetime(self.created_at)
        if self.deadline:
            local_datetime(self.deadline)
        if not isinstance(self.reminder, ReminderState):
            raise ValueError('提醒状态无效。')
        if not isinstance(self.reminder.seen, list) or any(
                x not in ('upcoming', 'deadline') for x in self.reminder.seen):
            raise ValueError('提醒记录无效。')
        for value in (self.reminder.snoozed_until, self.reminder.last_notified):
            if value is not None:
                local_datetime(value)

    @classmethod
    def create(cls, title, deadline=None, **kwargs):
        return cls(id=str(uuid4()), title=title, created_at=datetime.now().isoformat(),
                   deadline=deadline.replace(second=0, microsecond=0).isoformat() if deadline else None,
                   **kwargs)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data['reminder'] = ReminderState(**data.get('reminder', {}))
        return cls(**data)

    def update(self, *, title, deadline, description, reminder_minutes, color):
        candidate = Task.create(title, deadline, description=description,
                                reminder_minutes=reminder_minutes, color=color)
        if (self.deadline, self.reminder_minutes) != (candidate.deadline, reminder_minutes):
            self.reminder = ReminderState()
        for name in ('title', 'deadline', 'description', 'reminder_minutes', 'color'):
            setattr(self, name, getattr(candidate, name))

    def to_dict(self):
        return asdict(self)


@dataclass
class Settings:
    topmost: bool = False
    opacity: float = 1.0
    close_to_tray: bool = True
    reminder_minutes: int = 60
    repeat_enabled: bool = False
    repeat_minutes: int = 30
    theme: str = 'light'
    sort_by: str = 'deadline'
    show_completed: bool = False
    collapsed: bool = False
    width: int = 340
    height: int = 450
    x: int = 80
    y: int = 100

    def __post_init__(self):
        for name in ('topmost', 'close_to_tray', 'repeat_enabled', 'show_completed', 'collapsed'):
            if type(getattr(self, name)) is not bool:
                raise ValueError('设置开关无效。')
        for name, lower, upper in [('reminder_minutes', 0, 525600), ('repeat_minutes', 1, 10080),
                                  ('width', 300, 5000), ('height', 320, 5000),
                                  ('x', -100000, 100000), ('y', -100000, 100000)]:
            value = getattr(self, name)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f'设置 {name} 超出允许范围。')
        if not isinstance(self.opacity, (int, float)) or not 0.45 <= self.opacity <= 1:
            raise ValueError('透明度应在 45% 至 100% 之间。')
        if self.theme not in ('light', 'dark') or self.sort_by not in ('deadline', 'created'):
            raise ValueError('主题或排序方式无效。')


def sort_tasks(tasks, now, mode='deadline'):
    def key(task):
        due = local_datetime(task.deadline) if task.deadline else None
        group = 3 if task.completed else 0 if due and due <= now else 1 if due else 2
        if mode == 'created':
            return (task.completed, task.created_at)
        return (group, task.deadline or task.created_at, task.created_at)
    return sorted(tasks, key=key)


def remaining_text(task, now):
    if task.completed:
        return '已完成'
    if not task.deadline:
        return '不赶时间'
    minutes = int((local_datetime(task.deadline) - now).total_seconds() // 60)
    if minutes < 0:
        minutes = abs(minutes)
        amount = f'{minutes // 1440} 天' if minutes >= 1440 else f'{minutes // 60} 小时' if minutes >= 60 else f'{minutes} 分钟'
        return f'已逾期 {amount}'
    if minutes == 0:
        return '即将截止'
    if minutes < 60:
        return f'剩余 {minutes} 分钟'
    if minutes < 1440:
        return f'剩余 {minutes // 60} 小时 {minutes % 60} 分'
    return f'还有 {minutes // 1440} 天'
