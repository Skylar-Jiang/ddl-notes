import argparse
import hashlib
import logging
import sys
import tempfile
import tkinter as tk
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import messagebox

from .app import App
from .model import Settings, Task
from .storage import Store, data_directory
from .windows import InstanceGuard, Startup, enable_dpi_awareness


def main():
    parser = argparse.ArgumentParser(description='DDL Notes — 安静的桌面截止时间便签')
    parser.add_argument('--startup', action='store_true', help='由 Windows 登录启动')
    parser.add_argument('--remove-startup', action='store_true', help='移除当前用户自启动项后退出')
    parser.add_argument('--demo', action='store_true', help='使用隔离的示例任务预览界面')
    parser.add_argument('--data-dir', type=Path, help='使用独立数据目录（测试或便携备份用途）')
    args = parser.parse_args()
    if args.remove_startup:
        Startup().disable()
        return
    directory = args.data_dir or (Path(tempfile.gettempdir()) / 'DDLNotes-preview' if args.demo else data_directory())
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / 'ddl-notes.log', maxBytes=512_000, backupCount=2, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s')
    guard = InstanceGuard('DDLNotes-' + hashlib.sha256(str(directory.resolve()).lower().encode()).hexdigest()[:16])
    if not guard.acquire():
        guard.close()
        return
    root = None
    app = None
    try:
        enable_dpi_awareness()
        store = Store(directory / 'data.json')
        if args.demo and not store.path.exists():
            now = datetime.now().replace(second=0, microsecond=0)
            tasks = [Task.create('编译原理 · 预习作业', now + timedelta(days=2), color='lavender'),
                     Task.create('密码比赛 · 复赛提交', now + timedelta(days=5), color='butter'),
                     Task.create('操作系统 · 实验报告', now + timedelta(days=9), color='mint'),
                     Task.create('给自己留一点休息时间', color='peach')]
            store.save(tasks, Settings())
        root = tk.Tk()
        app = App(root, store, guard=guard, demo=args.demo)
        # Update an existing registration after moving the executable, without enabling it implicitly.
        if not args.demo and not args.data_dir and Startup().enabled():
            try:
                Startup().enable()
            except OSError:
                logging.exception('Cannot refresh startup path')
        logging.info('Started DDL Notes; frozen=%s; data=%s', getattr(sys, 'frozen', False), directory)
        root.mainloop()
    except Exception:
        logging.exception('Fatal application error')
        if root:
            messagebox.showerror('DDL Notes 未能启动', f'请查看日志：\n{directory / "ddl-notes.log"}', parent=root)
        else:
            raise
    finally:
        if app and app.tray and not app._closing:
            app.tray.stop()
        guard.close()
        logging.info('Stopped DDL Notes')


if __name__ == '__main__':
    main()
