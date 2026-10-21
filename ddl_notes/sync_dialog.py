import sys
import tkinter as tk
import webbrowser
from pathlib import Path

from .dialogs import Dialog
from .native_sync import register_host
from .widgets import SoftButton


class CourseSyncDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, '连接课程作业', width=450)
        self.extension_var = tk.StringVar()
        self.label('首次连接', bold=True)
        self.label('1. 在 Chrome / Edge 扩展管理页加载 browser-helper 文件夹。\n'
                   '2. 复制助手的扩展 ID，粘贴到下面并连接。\n'
                   '3. 在同一个浏览器登录课程平台，之后点一次同步。').configure(wraplength=app.px(390), justify='left')
        SoftButton(self.body, '打开浏览器助手目录', self.open_helper, palette=self.p, width=210,
                   filled=True, height=34, scale=app.scale).pack(anchor='w', pady=8)
        self.label('浏览器助手扩展 ID')
        self.entry(self.extension_var)
        SoftButton(self.body, '连接助手', self.connect, palette=self.p, width=110, height=34,
                   filled=True, scale=app.scale).pack(anchor='w', pady=8)
        self.label('已连接后', bold=True)
        self.label('在助手中点“同步小雅”或“同步雨课堂”，会自动遍历课程。\n'
                   '助手只传递作业信息；手动任务和本地笔记会保留。').configure(wraplength=app.px(390), justify='left')
        for name, url in (('打开南开小雅', 'https://nankai.ai-augmented.com/app/jx-web/mycourse'),
                          ('打开长江雨课堂', 'https://changjiang.yuketang.cn/v2/web/index')):
            SoftButton(self.body, name, lambda u=url: webbrowser.open(u), palette=self.p,
                       width=180, height=32, scale=app.scale).pack(anchor='w', pady=3)
        self.label('同步状态')
        tk.Label(self.body, textvariable=app.sync_status, bg=self.p['bg'], fg=self.p['muted'],
                 font=('Microsoft YaHei UI', 9), wraplength=app.px(390), justify='left').pack(fill='x')
        self.footer('关闭')

    def bundle_directory(self):
        return Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1] / 'dist'

    def open_helper(self):
        import os
        directory = self.bundle_directory() / 'browser-helper'
        if not directory.exists():
            directory = Path(__file__).resolve().parents[1] / 'browser-helper'
        os.startfile(directory)

    def connect(self):
        try:
            register_host(self.extension_var.get(), self.bundle_directory() / 'DDLNotesSync.exe')
            self.error_var.set('已连接。可在浏览器助手中开始同步。')
        except (OSError, ValueError) as exc:
            self.error_var.set(str(exc))

    def save(self):
        self.window.destroy()
