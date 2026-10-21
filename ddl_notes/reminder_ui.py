import tkinter as tk
from datetime import datetime

from .model import remaining_text
from .scheduler import snooze
from .widgets import ScrollArea, SoftButton
from .windows import style_window


class ReminderWindow:
    """One independent, topmost window, even when the main note is hidden."""
    def __init__(self, app, task_ids):
        self.app, self.p = app, app.p
        self.task_ids = set(task_ids)
        self.window = tk.Toplevel(app.root)
        self.window.withdraw()
        self.window.title('DDL Notes · 截止时间提醒')
        self.window.configure(bg=self.p['bg'])
        self.window.attributes('-topmost', True)
        self.window.resizable(True, True)
        self.window.minsize(app.px(340), app.px(250))
        width, height = app.px(385), app.px(410)
        x = max(0, app.root.winfo_screenwidth()-width-app.px(35))
        y = max(0, app.root.winfo_screenheight()-height-app.px(85))
        self.window.geometry(f'{width}x{height}+{x}+{y}')
        header = tk.Frame(self.window, bg=self.p['header'], padx=app.px(18), pady=app.px(15))
        header.pack(fill='x')
        self.heading = tk.Label(header, text='有几件事，需要留意', bg=self.p['header'],
                                fg=self.p['text'], font=('Microsoft YaHei UI', 12, 'bold'), anchor='w')
        self.heading.pack(fill='x')
        tk.Label(header, text='做完就勾掉，也可以稍后再提醒。', bg=self.p['header'],
                 fg=self.p['muted'], font=('Microsoft YaHei UI', 9), anchor='w').pack(fill='x', pady=(5, 0))
        self.area = ScrollArea(self.window, self.p)
        self.area.pack(fill='both', expand=True, padx=app.px(12), pady=app.px(8))
        SoftButton(self.window, '知道了，收起提醒', self.close, palette=self.p, width=180,
                   height=35, filled=True, scale=app.scale).pack(pady=(0, app.px(12)))
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Escape>', lambda _: self.close())
        self.refresh()
        self.window.deiconify()
        style_window(self.window, dark=app.settings.theme == 'dark', tool=True)
        # No focus_set / focus_force / grab_set: keep the user's typing focus.

    def refresh(self):
        current = {t.id for t in self.app.tasks if not t.completed}
        self.task_ids.intersection_update(current)
        if not self.task_ids:
            self.close()
            return
        for child in self.area.inner.winfo_children():
            child.destroy()
        self.heading.configure(text=f'{len(self.task_ids)} 件事，需要留意')
        for task in self.app.tasks:
            if task.id not in self.task_ids:
                continue
            frame = tk.Frame(self.area.inner, bg=self.p['bg'], padx=6, pady=10)
            frame.pack(fill='x')
            tk.Label(frame, text=task.title, wraplength=self.app.px(315), justify='left', anchor='w',
                     font=('Microsoft YaHei UI', 10, 'bold'), bg=self.p['bg'], fg=self.p['text']).pack(fill='x')
            tk.Label(frame, text=remaining_text(task, datetime.now()), anchor='w',
                     font=('Microsoft YaHei UI', 9), bg=self.p['bg'], fg=self.p['danger']).pack(fill='x', pady=4)
            row = tk.Frame(frame, bg=self.p['bg']); row.pack(fill='x')
            for label, command, width in (
                    ('✓ 已完成', lambda t=task: self.app.toggle_task(t), 87),
                    ('10 分钟后', lambda t=task: self.snooze(t, 10), 88),
                    ('30 分钟后', lambda t=task: self.snooze(t, 30), 88)):
                SoftButton(row, label, command, palette=self.p, width=width, filled=True,
                           scale=self.app.scale).pack(side='left', padx=(0, 5))

    def snooze(self, task, minutes):
        snooze(task, datetime.now(), minutes)
        if self.app.save():
            self.task_ids.discard(task.id)
            self.refresh()

    def close(self):
        if self.window.winfo_exists():
            self.window.destroy()
        if self.app.alarm is self:
            self.app.alarm = None
