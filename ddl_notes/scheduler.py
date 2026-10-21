"""Pure reminder decisions. The UI acknowledges a batch only after displaying it."""
from dataclasses import dataclass
from datetime import timedelta

from .model import local_datetime


@dataclass(frozen=True)
class ReminderEvent:
    task_id: str
    kind: str


def due_events(tasks, settings, now):
    events = []
    for task in tasks:
        if task.completed or not task.deadline:
            continue
        due = local_datetime(task.deadline)
        state = task.reminder
        kind = None
        # Catch up to the most recent milestone, never replay every missed milestone.
        if now >= due and 'deadline' not in state.seen:
            kind = 'deadline'
        elif state.snoozed_until:
            if now >= local_datetime(state.snoozed_until):
                kind = 'snooze'
        elif now < due:
            advance = task.reminder_minutes if task.reminder_minutes is not None else settings.reminder_minutes
            if now >= due - timedelta(minutes=advance) and 'upcoming' not in state.seen:
                kind = 'upcoming'
            elif (settings.repeat_enabled and state.last_notified and
                  now >= local_datetime(state.last_notified) + timedelta(minutes=settings.repeat_minutes)):
                kind = 'repeat'
        if kind:
            events.append(ReminderEvent(task.id, kind))
    return events


def acknowledge(task, kind, now):
    if kind == 'deadline':
        task.reminder.seen = ['upcoming', 'deadline']
    elif kind == 'upcoming' and kind not in task.reminder.seen:
        task.reminder.seen.append(kind)
    task.reminder.snoozed_until = None
    task.reminder.last_notified = now.isoformat()


def snooze(task, now, minutes):
    task.reminder.snoozed_until = (now + timedelta(minutes=minutes)).isoformat()
