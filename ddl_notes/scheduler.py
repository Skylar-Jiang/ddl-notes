"""Pure reminder decisions. The UI acknowledges a batch only after displaying it."""
from dataclasses import dataclass
from datetime import timedelta

from .model import as_instant


@dataclass(frozen=True)
class ReminderEvent:
    task_id: str
    kind: str


def due_events(tasks, settings, now):
    now = as_instant(now)
    events = []
    for task in tasks:
        if task.completed or not task.deadline:
            continue
        due = task.deadline_instant()
        state = task.reminder
        kind = None
        # Catch up to the most recent milestone, never replay every missed milestone.
        if now >= due and 'deadline' not in state.seen:
            kind = 'deadline'
        elif state.snoozed_until:
            if now >= as_instant(state.snoozed_until):
                kind = 'snooze'
        elif now < due:
            advance = task.reminder_minutes if task.reminder_minutes is not None else settings.reminder_minutes
            if now >= due - timedelta(minutes=advance) and 'upcoming' not in state.seen:
                kind = 'upcoming'
            elif (settings.repeat_enabled and state.last_notified and
                  now >= as_instant(state.last_notified) + timedelta(minutes=settings.repeat_minutes)):
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
    task.reminder.last_notified = as_instant(now).isoformat()


def snooze(task, now, minutes):
    task.reminder.snoozed_until = (as_instant(now) + timedelta(minutes=minutes)).isoformat()
