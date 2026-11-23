import tkinter as tk
from dataclasses import replace
from tkinter import ttk

from .dialogs import Dialog
from .widgets import SoftButton


class AutoSyncDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, '自动同步课程', width=450)
        settings = app.settings
        self.enabled_var = tk.BooleanVar(value=settings.auto_sync_enabled)
        self.interval_var = tk.StringVar(value=str(settings.auto_sync_minutes))
        self.xiaoya_var = tk.BooleanVar(value=settings.sync_xiaoya)
        self.rain_var = tk.BooleanVar(value=settings.sync_yuketang)
        self.label('只需打开便签，无需保持日常浏览器开启。\n首次在专用 Edge 窗口登录，过期后重新登录。').configure(
            wraplength=app.px(395), justify='left')
        self.check('启用自动同步', self.enabled_var)
        self.label('同步间隔 · 分钟（5—1440）')
        ttk.Spinbox(self.body, from_=5, to=1440, textvariable=self.interval_var,
                    font=('Microsoft YaHei UI', 10)).pack(fill='x', ipady=app.px(5))
        self.check('同步南开小雅 · 进行中的课程', self.xiaoya_var)
        self.check('同步长江雨课堂 · 仅 2026 年秋', self.rain_var)
        self.label('登录一次，会话仅在本机保存并由 Windows 用户保护。\n检测到有效登录后，登录窗口会自动关闭。').configure(
            wraplength=app.px(395), justify='left')
        for source, name in (('xiaoya', '登录 / 重新登录小雅'), ('yuketang', '登录 / 重新登录雨课堂')):
            SoftButton(self.body, name, lambda s=source: self.start('login', [s]),
                       palette=self.p, width=235, height=33, scale=app.scale).pack(anchor='w', pady=3)
        SoftButton(self.body, '立即后台同步', self.sync_now, palette=self.p, width=235,
                   height=33, filled=True, scale=app.scale).pack(anchor='w', pady=6)
        tk.Label(self.body, textvariable=app.auto_sync_status, bg=self.p['bg'], fg=self.p['muted'],
                 font=('Microsoft YaHei UI', 9), wraplength=app.px(395), justify='left', anchor='w').pack(fill='x', pady=6)
        self.footer('保存设置')

    def start(self, action, sources):
        try:
            if self.app.demo:
                raise ValueError('预览模式不连接真实账号，请打开正式便签。')
            self.app.auto_sync.start(action, sources)
            self.app.auto_sync_status.set(self.app.auto_sync.status)
            self.error_var.set('')
        except (OSError, ValueError) as exc:
            self.error_var.set(str(exc))

    def sync_now(self):
        self.start('sync', [source for source, enabled in
                           (('xiaoya', self.xiaoya_var.get()), ('yuketang', self.rain_var.get())) if enabled])

    def save(self):
        try:
            settings = replace(self.app.settings, auto_sync_enabled=self.enabled_var.get(),
                               auto_sync_minutes=int(self.interval_var.get()),
                               sync_xiaoya=self.xiaoya_var.get(), sync_yuketang=self.rain_var.get())
            old = self.app.settings
            self.app.settings = settings
            if self.app.save():
                self.app.auto_sync.configure(settings)
                self.window.destroy()
            else:
                self.app.settings = old
        except ValueError as exc:
            self.error_var.set('同步间隔应为 5 至 1440 分钟的整数。' if 'invalid literal' in str(exc) else str(exc))
