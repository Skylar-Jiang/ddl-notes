import logging
import tkinter as tk
from dataclasses import replace
from datetime import datetime, timedelta
from tkinter import ttk

from .model import Task, parse_deadline
from .widgets import SoftButton


class Dialog:
    def __init__(self, app, title, width=390):
        self.app, self.p = app, app.p
        self.width = width
        self.window = tk.Toplevel(app.root)
        self.window.title(title)
        self.window.configure(bg=self.p['bg'])
        self.window.resizable(False, False)
        self.window.transient(app.root)
        self.window.attributes('-topmost', app.settings.topmost)
        self.window.geometry(f'{app.px(width)}x{app.px(570)}+{max(0, app.root.winfo_x()+25)}+{max(0, app.root.winfo_y()+10)}')
        self.body = tk.Frame(self.window, bg=self.p['bg'], padx=app.px(22), pady=app.px(16))
        self.body.pack(fill='both', expand=True)
        self.label(title, size=15, bold=True, pady=(0, 12))
        self.error_var = tk.StringVar()
        self.window.bind('<Escape>', lambda _: self.window.destroy())
        self.window.protocol('WM_DELETE_WINDOW', self.window.destroy)
        self.window.grab_set()

    def label(self, text, *, size=9, bold=False, pady=(8, 4), parent=None):
        label = tk.Label(parent or self.body, text=text, bg=self.p['bg'], fg=self.p['text'],
                         font=('Microsoft YaHei UI', size, 'bold' if bold else 'normal'), anchor='w')
        label.pack(fill='x', pady=pady)
        return label

    def entry(self, variable, parent=None, width=None):
        entry = ttk.Entry(parent or self.body, textvariable=variable, font=('Microsoft YaHei UI', 10), width=width)
        entry.pack(fill='x', ipady=self.app.px(5))
        return entry

    def check(self, text, variable, command=None):
        control = tk.Checkbutton(self.body, text=text, variable=variable, command=command,
                                 bg=self.p['bg'], fg=self.p['text'], activebackground=self.p['bg'],
                                 activeforeground=self.p['text'], selectcolor=self.p['field'],
                                 font=('Microsoft YaHei UI', 9), anchor='w', highlightthickness=0)
        control.pack(fill='x', pady=(6, 0))
        return control

    def footer(self, save_label='保存'):
        tk.Label(self.body, textvariable=self.error_var, bg=self.p['bg'], fg=self.p['danger'],
                 font=('Microsoft YaHei UI', 9), wraplength=self.app.px(340), anchor='w').pack(fill='x', pady=8)
        row = tk.Frame(self.body, bg=self.p['bg'])
        row.pack(side='bottom', fill='x', pady=(4, 0))
        SoftButton(row, save_label, self.save, palette=self.p, width=110, height=36,
                   filled=True, scale=self.app.scale).pack(side='right')
        SoftButton(row, '取消', self.window.destroy, palette=self.p, width=65, height=36,
                   scale=self.app.scale).pack(side='right', padx=8)
        self.window.bind('<Control-Return>', lambda _: self.save())
        self.window.update_idletasks()
        # Size from actual local font/DPI metrics so packed footer controls retain their height.
        self.window.geometry(f'{self.app.px(self.width)}x{self.body.winfo_reqheight()}')


class TaskEditor(Dialog):
    def __init__(self, app, task=None):
        super().__init__(app, '编辑任务' if task else '记下一件事')
        self.task = task
        due = datetime.fromisoformat(task.deadline) if task and task.deadline else datetime.now() + timedelta(days=1)
        self.title_var = tk.StringVar(value=task.title if task else '')
        self.has_deadline = tk.BooleanVar(value=bool(task.deadline) if task else True)
        self.date_var = tk.StringVar(value=due.strftime('%Y-%m-%d'))
        self.time_var = tk.StringVar(value=due.strftime('%H:%M') if task and task.deadline else '20:00')
        self.advance_var = tk.StringVar(value='' if not task or task.reminder_minutes is None else str(task.reminder_minutes))
        self.label('任务名称')
        self.title_entry = self.entry(self.title_var)
        self.label('描述 · 可选')
        self.description = tk.Text(self.body, height=3, font=('Microsoft YaHei UI', 10), wrap='word',
                                   bg=self.p['field'], fg=self.p['text'], insertbackground=self.p['text'],
                                   relief='flat', padx=8, pady=7, highlightthickness=1,
                                   highlightbackground=self.p['line'], highlightcolor=self.p['accent'])
        self.description.pack(fill='x')
        self.description.insert('1.0', task.description if task else '')
        self.check('设置截止时间', self.has_deadline, self.deadline_state)
        dates = tk.Frame(self.body, bg=self.p['bg'])
        dates.pack(fill='x', pady=6)
        left = tk.Frame(dates, bg=self.p['bg']); left.pack(side='left', fill='x', expand=True)
        right = tk.Frame(dates, bg=self.p['bg']); right.pack(side='left', padx=(10, 0))
        self.label('日期  YYYY-MM-DD', parent=left, pady=(0, 4))
        self.date_entry = self.entry(self.date_var, parent=left, width=17)
        self.label('时间  HH:MM', parent=right, pady=(0, 4))
        self.time_entry = self.entry(self.time_var, parent=right, width=9)
        self.label(f'提前提醒（分钟）· 留空跟随全局 {app.settings.reminder_minutes} 分钟')
        self.advance_entry = self.entry(self.advance_var)
        self.footer('保存任务')
        self.deadline_state()
        self.title_entry.focus_set()

    def deadline_state(self):
        state = 'normal' if self.has_deadline.get() else 'disabled'
        for entry in (self.date_entry, self.time_entry, self.advance_entry):
            entry.configure(state=state)

    def save(self):
        try:
            due = parse_deadline(self.date_var.get(), self.time_var.get()) if self.has_deadline.get() else None
            advance = int(self.advance_var.get()) if self.advance_var.get().strip() and due else None
            values = dict(title=self.title_var.get(), deadline=due, description=self.description.get('1.0', 'end-1c'),
                          reminder_minutes=advance)
            if self.task:
                self.task.update(**values, color=self.task.color)
            else:
                self.task = Task.create(**values)
                self.app.tasks.append(self.task)
            if self.app.save():
                self.window.destroy()
                self.app.sync_alarm()
                self.app.render_tasks()
                self.app.check_reminders()
        except ValueError as exc:
            self.error_var.set(str(exc) if 'invalid literal' not in str(exc) else '提醒分钟数应为整数。')


class SettingsDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, '让便签适合你', width=410)
        s = app.settings
        self.advance_var = tk.StringVar(value=str(s.reminder_minutes))
        self.repeat_var = tk.BooleanVar(value=s.repeat_enabled)
        self.repeat_minutes_var = tk.StringVar(value=str(s.repeat_minutes))
        self.startup_var = tk.BooleanVar(value=app.startup.enabled())
        self.close_var = tk.BooleanVar(value=s.close_to_tray)
        self.theme_var = tk.StringVar(value=s.theme)
        self.opacity_var = tk.DoubleVar(value=s.opacity*100)
        self.label('默认提前提醒 · 分钟', pady=(0, 4)); self.entry(self.advance_var)
        self.check('临期后重复提醒（截止后不再自动重复）', self.repeat_var)
        self.label('重复提醒间隔 · 分钟'); self.entry(self.repeat_minutes_var)
        self.check('Windows 登录后自动启动', self.startup_var)
        self.check('关闭窗口时隐藏到托盘', self.close_var)
        self.label('窗口透明度 · 45% — 100%')
        tk.Scale(self.body, from_=45, to=100, orient='horizontal', variable=self.opacity_var,
                 bg=self.p['bg'], fg=self.p['muted'], troughcolor=self.p['header'],
                 highlightthickness=0, activebackground=self.p['accent'], relief='flat').pack(fill='x')
        self.label('外观')
        row = tk.Frame(self.body, bg=self.p['bg']); row.pack(fill='x')
        for value, text in (('light', '糖果浅色'), ('dark', '柔和深色')):
            tk.Radiobutton(row, text=text, variable=self.theme_var, value=value, bg=self.p['bg'],
                           fg=self.p['text'], selectcolor=self.p['field'], activebackground=self.p['bg'],
                           font=('Microsoft YaHei UI', 9)).pack(side='left', padx=(0, 16))
        backup = tk.Frame(self.body, bg=self.p['bg']); backup.pack(fill='x', pady=(18, 0))
        SoftButton(backup, '导出备份', app.export_data, palette=self.p, width=95, scale=app.scale).pack(side='left')
        SoftButton(backup, '导入备份', app.import_data, palette=self.p, width=95, scale=app.scale).pack(side='left')
        SoftButton(backup, '打开数据目录', app.open_data_folder, palette=self.p, width=110, scale=app.scale).pack(side='left')
        self.footer('保存设置')

    def save(self):
        try:
            settings = replace(self.app.settings, reminder_minutes=int(self.advance_var.get()),
                               repeat_enabled=self.repeat_var.get(), repeat_minutes=int(self.repeat_minutes_var.get()),
                               close_to_tray=self.close_var.get(), theme=self.theme_var.get(),
                               opacity=round(self.opacity_var.get()/100, 2))
            if not self.app.demo:
                if self.startup_var.get():
                    self.app.startup.enable()
                else:
                    self.app.startup.disable()
            elif self.startup_var.get():
                raise ValueError('预览模式不注册自启动，请在正式程序中设置。')
            self.app.settings = settings
            if self.app.save():
                self.window.destroy()
                self.app.apply_appearance()
                self.app.build_shell()
                self.app.check_reminders()
        except (ValueError, OSError) as exc:
            logging.warning('Settings not saved: %s', exc)
            self.error_var.set(str(exc) if 'invalid literal' not in str(exc) else '提醒时间应为整数分钟。')
