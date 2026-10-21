import logging
import json
import os
import queue
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .dialogs import SettingsDialog, TaskEditor
from .model import COLORS, local_datetime, remaining_text, sort_tasks
from .reminder_ui import ReminderWindow
from .scheduler import acknowledge, due_events
from .widgets import DARK, DARK_PASTELS, LIGHT, PASTELS, RoundCheck, RoundedCard, ScrollArea, SoftButton
from .windows import Startup, Tray, move_window, screen_bounds, style_window
from .course_sync import merge_sync


class App:
    def __init__(self, root, store, guard=None, with_tray=True, demo=False):
        self.root, self.store, self.guard, self.demo = root, store, guard, demo
        self.tasks, self.settings = store.load()
        self.scale = root.winfo_fpixels('1i') / 96
        self.queue = queue.Queue()
        self.tray = None
        self.alarm = None
        self.editor = None
        self.settings_dialog = None
        self.sync_dialog = None
        self.sync_status = tk.StringVar(value='尚未同步课程作业')
        self._sync_poll_count = 0
        self._closing = False
        self._geometry_after = None
        self._last_minute = None
        self._after_ids = []
        self.startup = Startup()
        root.title('DDL Notes' + (' · 预览' if demo else ''))
        icon = Path(__file__).parent / 'assets' / 'app.ico'
        if icon.exists():
            root.iconbitmap(default=str(icon))
        root.withdraw()
        root.report_callback_exception = self.callback_error
        self.apply_appearance()
        s = self.settings
        # Window sizes are logical 96-DPI pixels; positions are native screen pixels.
        width, height = self.px(s.width), self.px(44 if s.collapsed else s.height)
        x, y = s.x, s.y
        left, top, right, bottom = screen_bounds(root)
        if x + width < left+40 or x > right-40 or y < top or y > bottom-40:
            x, y = 80, 100
        root.geometry(f'{width}x{height}+{max(0, x)}+{max(0, y)}')
        root.minsize(self.px(300), self.px(44 if s.collapsed else 320))
        self.build_shell()
        root.protocol('WM_DELETE_WINDOW', self.request_close)
        root.bind('<Configure>', self.geometry_changed)
        root.bind('<Control-n>', lambda _: self.open_editor())
        root.bind('<Control-comma>', lambda _: self.open_settings())
        root.bind('<Escape>', lambda _: self.request_close())
        root.deiconify()
        style_window(root, dark=s.theme == 'dark')
        move_window(root, x, y)
        if with_tray:
            self.tray = Tray(self.queue)
            try:
                self.tray.start()
            except (ImportError, OSError):
                logging.exception('Tray unavailable')
                self.tray = None
                self.root.after(500, lambda: messagebox.showwarning(
                    '托盘暂不可用', '窗口关闭时将退出程序。请检查依赖安装，或查看日志。', parent=root))
        self._after_ids.append(root.after(750, self.poll_queue))
        self._after_ids.append(root.after(1200, self.tick))
        if store.warning:
            root.after(600, lambda: messagebox.showwarning('数据恢复', store.warning, parent=root))

    def px(self, value):
        return round(value * self.scale)

    def callback_error(self, exc_type, value, tb):
        logging.error('GUI callback failed', exc_info=(exc_type, value, tb))
        messagebox.showerror('操作没有完成', f'{value}\n详细信息已记录到日志。', parent=self.root)

    def apply_appearance(self):
        self.p = DARK if self.settings.theme == 'dark' else LIGHT
        self.root.configure(bg=self.p['bg'])
        self.root.attributes('-topmost', self.settings.topmost)
        self.root.attributes('-alpha', self.settings.opacity)
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('TEntry', fieldbackground=self.p['field'], foreground=self.p['text'],
                        bordercolor=self.p['line'], lightcolor=self.p['line'], darkcolor=self.p['line'],
                        insertcolor=self.p['text'], padding=3)
        style.map('TEntry', bordercolor=[('focus', self.p['accent'])])
        style.configure('Vertical.TScrollbar', background=self.p['header'], troughcolor=self.p['bg'],
                        borderwidth=0, arrowsize=self.px(10), gripcount=0)
        if self.root.winfo_viewable():
            style_window(self.root, dark=self.settings.theme == 'dark')

    def build_shell(self):
        for child in self.root.winfo_children():
            if not isinstance(child, tk.Toplevel):
                child.destroy()
        p = self.p
        self.header = tk.Frame(self.root, bg=p['header'], height=self.px(44))
        self.header.pack(fill='x')
        self.header.pack_propagate(False)
        title = tk.Label(self.header, text='DDL Notes', bg=p['header'], fg=p['text'],
                         font=('Segoe UI', 11, 'bold'), padx=self.px(14))
        title.pack(side='left', fill='y')
        for widget in (self.header, title):
            widget.bind('<Button-1>', self.start_drag)
            widget.bind('<B1-Motion>', self.drag)
            widget.bind('<Double-Button-1>', lambda _: self.toggle_collapse())
        # Pack right to left, keeping every control available at the minimum width.
        for name, icon, action in (
                ('关闭 / 隐藏', 'close', self.request_close), ('最小化', 'minimize', self.root.iconify),
                ('更多选项', 'more', self.show_menu),
                ('展开 / 折叠', 'expand' if self.settings.collapsed else 'collapse', self.toggle_collapse),
                ('取消置顶' if self.settings.topmost else '置顶', 'pin', self.toggle_pin)):
            button = SoftButton(self.header, '', action, palette=p, icon=icon, width=30,
                                height=30, filled=(icon == 'pin' and self.settings.topmost), scale=self.scale)
            button.pack(side='right', padx=(0, self.px(2)), pady=self.px(7))
            self.tooltip(button, name)
        self.main = tk.Frame(self.root, bg=p['bg'])
        if not self.settings.collapsed:
            self.main.pack(fill='both', expand=True)
        intro = tk.Frame(self.main, bg=p['bg'], padx=self.px(17), pady=self.px(13))
        intro.pack(fill='x')
        self.day_label = tk.Label(intro, bg=p['bg'], fg=p['text'], font=('Microsoft YaHei UI', 12, 'bold'), anchor='w')
        self.day_label.pack(side='left')
        self.count_label = tk.Label(intro, bg=p['bg'], fg=p['muted'], font=('Microsoft YaHei UI', 9))
        self.count_label.pack(side='right')
        footer = tk.Frame(self.main, bg=p['bg'], padx=self.px(15), pady=self.px(10))
        footer.pack(side='bottom', fill='x')
        SoftButton(footer, '＋  添加任务', self.open_editor, palette=p, width=150, height=36,
                   filled=True, scale=self.scale).pack(side='left')
        self.complete_button = SoftButton(footer, '', self.toggle_completed_view, palette=p,
                                          width=110, height=36, scale=self.scale)
        self.complete_button.pack(side='right')
        self.area = ScrollArea(self.main, p)
        self.area.pack(fill='both', expand=True, padx=(self.px(13), self.px(3)))
        self.render_tasks()

    def tooltip(self, widget, text):
        tip = [None, None]
        def leave(_=None):
            if tip[1]:
                self.root.after_cancel(tip[1]); tip[1] = None
            if tip[0]:
                tip[0].destroy(); tip[0] = None
        def show():
            tip[1] = None
            if not widget.winfo_exists():
                return
            tip[0] = tk.Toplevel(self.root)
            tip[0].overrideredirect(True)
            tip[0].attributes('-topmost', True)
            tk.Label(tip[0], text=text, bg=self.p['field'], fg=self.p['text'],
                     font=('Microsoft YaHei UI', 9), padx=7, pady=4).pack()
            tip[0].geometry(f'+{widget.winfo_rootx()-25}+{widget.winfo_rooty()+self.px(33)}')
        widget.bind('<Enter>', lambda _: tip.__setitem__(1, self.root.after(650, show)), add='+')
        widget.bind('<Leave>', leave, add='+')
        widget.bind('<Destroy>', leave, add='+')
        widget.bind('<Button-1>', leave, add='+')

    def render_tasks(self):
        position = self.area.canvas.yview()[0]
        for child in self.area.inner.winfo_children():
            child.destroy()
        now = datetime.now()
        weekday = '一二三四五六日'[now.weekday()]
        self.day_label.configure(text=f'{now.month} 月 {now.day} 日 · 周{weekday}')
        unfinished = sum(not t.completed for t in self.tasks)
        done = len(self.tasks) - unfinished
        self.count_label.configure(text=f'{unfinished} 件待办')
        self.complete_button.text = f'{"收起" if self.settings.show_completed else "已完成"} · {done}'
        self.complete_button.draw()
        visible = [t for t in sort_tasks(self.tasks, now, self.settings.sort_by)
                   if self.settings.show_completed or not t.completed]
        if not visible:
            empty = tk.Frame(self.area.inner, bg=self.p['bg'], pady=self.px(45))
            empty.pack(fill='x')
            tk.Label(empty, text='今天，轻一点。' if not self.tasks else '待办都完成了',
                     font=('Microsoft YaHei UI', 14), fg=self.p['text'], bg=self.p['bg']).pack()
            tk.Label(empty, text='把要紧的事记在这里。' if not self.tasks else '下一件事，准备好再开始。',
                     font=('Microsoft YaHei UI', 9), fg=self.p['muted'], bg=self.p['bg']).pack(pady=10)
        for index, task in enumerate(visible):
            self.task_card(task, now, COLORS[index % len(COLORS)])
        self.area.update_idletasks()
        self.area.canvas.yview_moveto(position)

    def task_card(self, task, now, color):
        colors = DARK_PASTELS if self.settings.theme == 'dark' else PASTELS
        fill, border = colors[color]
        title = task.title if len(task.title) <= 85 else task.title[:84] + '…'
        # Long names get another line; full title remains available in the editor.
        lines = max(1, (len(title) + 15) // 16)
        height = 77 + (min(lines, 6)-1)*19
        card = RoundedCard(self.area.inner, fill, border, height=self.px(height), scale=self.scale)
        card.pack(fill='x', pady=(0, self.px(9)), padx=(0, self.px(3)))
        content = card.content
        check = RoundCheck(content, task.completed, lambda: self.toggle_task(task), self.p, self.scale)
        check.pack(side='left', anchor='n', padx=(0, self.px(6)), pady=self.px(1))
        body = tk.Frame(content, bg=fill)
        body.pack(side='left', fill='both', expand=True)
        title_label = tk.Label(body, text=title, bg=fill,
                               fg=self.p['muted'] if task.completed else self.p['text'],
                               font=('Microsoft YaHei UI', 10, 'overstrike' if task.completed else 'normal'),
                               anchor='w', justify='left', cursor='hand2')
        title_label.pack(fill='x')
        body.bind('<Configure>', lambda e: title_label.configure(wraplength=max(self.px(110), e.width)))
        due_text = local_datetime(task.deadline).strftime('%m月%d日  %H:%M') if task.deadline else '没有截止时间'
        tk.Label(body, text=due_text, bg=fill, fg=self.p['muted'],
                 font=('Microsoft YaHei UI', 8), anchor='w').pack(fill='x', pady=(self.px(5), 0))
        due = local_datetime(task.deadline) if task.deadline else None
        advance = task.reminder_minutes if task.reminder_minutes is not None else self.settings.reminder_minutes
        urgent = due and not task.completed and (due-now).total_seconds() <= advance*60
        tk.Label(body, text=remaining_text(task, now), bg=fill,
                 fg=self.p['danger'] if urgent else self.p['muted'],
                 font=('Microsoft YaHei UI', 8), anchor='w').pack(fill='x', pady=(self.px(3), 0))
        for widget in (card, title_label):
            widget.bind('<Double-Button-1>', lambda _, t=task: self.open_editor(t))
            widget.bind('<Button-3>', lambda e, t=task: self.task_menu(e, t))
        title_label.bind('<ButtonRelease-1>', lambda _, t=task: self.open_editor(t))
        more = SoftButton(content, '', lambda: self.open_editor(task), palette=self.p,
                          icon='more', width=24, height=24, scale=self.scale)
        more.pack(side='right', anchor='n')
        self.tooltip(more, '编辑任务 · 右键可删除')

    def start_drag(self, event):
        self._drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def drag(self, event):
        sx, sy, wx, wy = self._drag_origin
        move_window(self.root, wx+event.x_root-sx, wy+event.y_root-sy)

    def geometry_changed(self, event):
        if event.widget is not self.root or self._closing or self.root.state() != 'normal':
            return
        if self._geometry_after:
            self.root.after_cancel(self._geometry_after)
        self._geometry_after = self.root.after(700, self.remember_geometry)

    def remember_geometry(self):
        if self._geometry_after:
            self.root.after_cancel(self._geometry_after)
        self._geometry_after = None
        if self.root.state() != 'normal':
            return
        s = self.settings
        s.x, s.y = self.root.winfo_x(), self.root.winfo_y()
        s.width = max(300, round(self.root.winfo_width()/self.scale))
        if not s.collapsed:
            s.height = max(320, round(self.root.winfo_height()/self.scale))
        self.save()

    def toggle_pin(self):
        self.settings.topmost = not self.settings.topmost
        self.root.attributes('-topmost', self.settings.topmost)
        self.save()
        self.build_shell()

    def toggle_collapse(self):
        if not self.settings.collapsed:
            self.remember_geometry()
        self.settings.collapsed = not self.settings.collapsed
        height = 44 if self.settings.collapsed else self.settings.height
        self.root.minsize(self.px(300), self.px(44 if self.settings.collapsed else 320))
        self.root.geometry(f'{self.px(self.settings.width)}x{self.px(height)}')
        self.build_shell()
        self.save()

    def toggle_completed_view(self):
        self.settings.show_completed = not self.settings.show_completed
        self.save()
        self.render_tasks()

    def toggle_task(self, task):
        task.completed = not task.completed
        task.reminder.snoozed_until = None
        self.save()
        self.render_tasks()
        self.sync_alarm()

    def sync_alarm(self):
        if self.alarm:
            self.alarm.refresh()

    def task_menu(self, event, task):
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label='编辑任务', command=lambda: self.open_editor(task))
        menu.add_command(label='取消完成' if task.completed else '标记完成', command=lambda: self.toggle_task(task))
        menu.add_separator()
        menu.add_command(label='删除任务…', command=lambda: self.delete_task(task))
        menu.tk_popup(event.x_root, event.y_root)

    def delete_task(self, task):
        if messagebox.askyesno('删除任务', f'删除“{task.title[:60]}”？', parent=self.root):
            self.tasks.remove(task)
            self.save()
            self.render_tasks()
            self.sync_alarm()

    def show_menu(self):
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label='设置…', command=self.open_settings)
        menu.add_command(label='连接 / 同步课程作业…', command=self.open_course_sync)
        menu.add_command(label='按创建时间排序' if self.settings.sort_by == 'deadline' else '按截止时间排序', command=self.toggle_sort)
        menu.add_command(label='隐藏到托盘', command=self.hide)
        menu.add_separator()
        menu.add_command(label='退出 DDL Notes', command=self.quit)
        menu.tk_popup(self.root.winfo_rootx()+self.px(135), self.root.winfo_rooty()+self.px(42))

    def toggle_sort(self):
        self.settings.sort_by = 'created' if self.settings.sort_by == 'deadline' else 'deadline'
        self.save(); self.render_tasks()

    def open_editor(self, task=None):
        if self.editor and self.editor.window.winfo_exists():
            self.editor.window.lift()
            return self.editor
        self.show()
        self.editor = TaskEditor(self, task)
        return self.editor

    def open_settings(self):
        if self.settings_dialog and self.settings_dialog.window.winfo_exists():
            self.settings_dialog.window.lift()
            return self.settings_dialog
        self.show()
        self.settings_dialog = SettingsDialog(self)
        return self.settings_dialog

    def open_course_sync(self):
        from .sync_dialog import CourseSyncDialog
        if self.sync_dialog and self.sync_dialog.window.winfo_exists():
            self.sync_dialog.window.lift()
            return self.sync_dialog
        self.show()
        self.sync_dialog = CourseSyncDialog(self)
        return self.sync_dialog

    def consume_sync(self):
        inbox = self.store.path.parent / 'inbox'
        if not inbox.exists():
            return
        for path in sorted(inbox.glob('*.json'))[:5]:
            old_tasks = self.tasks
            try:
                if path.stat().st_size > 1_000_000:
                    raise ValueError('同步数据过大。')
                result = merge_sync(self.tasks, json.loads(path.read_bytes()))
                if result.removed:
                    backup = self.store.path.parent / f'before-sync-cleanup-{datetime.now():%Y%m%d-%H%M%S-%f}.json'
                    self.store.export(backup, old_tasks, self.settings)
                self.tasks = result.tasks
                if not self.save():
                    raise OSError('同步结果尚未保存。')
            except (OSError, ValueError, TypeError) as exc:
                self.tasks = old_tasks
                logging.warning('Cannot apply sync batch %s: %s', path.name, exc)
                try:
                    path.rename(path.with_suffix('.failed'))
                except OSError:
                    logging.warning('Cannot preserve failed sync batch %s', path.name)
                self.sync_status.set(f'同步未完成：{exc}')
                self.count_label.configure(text='同步未完成')
                continue
            try:
                path.unlink()
            except OSError:
                logging.warning('Cannot remove applied sync batch %s; next read is idempotent', path.name)
            self.sync_status.set(f'已新增 {result.added} 条，更新 {result.updated} 条，未变化 {result.unchanged} 条；'
                                 f'清理 {result.removed} 条，忽略超期 {result.skipped} 条')
            self.render_tasks()
            self.count_label.configure(text=f'同步 +{result.added} 条')
            self.sync_alarm()
            self.check_reminders()

    def save(self):
        try:
            self.store.save(self.tasks, self.settings)
            return True
        except (OSError, ValueError):
            logging.exception('Saving user data failed')
            messagebox.showerror('尚未保存', '无法写入数据文件。请检查磁盘空间和目录权限。\n当前窗口保留了修改，请重试保存。', parent=self.root)
            return False

    def check_reminders(self):
        events = due_events(self.tasks, self.settings, datetime.now())
        if not events:
            return
        ids = {event.task_id for event in events}
        if self.alarm:
            self.alarm.task_ids.update(ids)
            self.alarm.refresh()
        else:
            self.alarm = ReminderWindow(self, ids)
        self.root.update_idletasks()
        by_id = {t.id: t for t in self.tasks}
        now = datetime.now()
        for event in events:
            acknowledge(by_id[event.task_id], event.kind, now)
        self.save()

    def tick(self):
        if self._closing:
            return
        self.check_reminders()
        minute = datetime.now().strftime('%Y%m%d%H%M')
        if minute != self._last_minute:
            self._last_minute = minute
            if self.root.state() == 'normal':
                self.render_tasks()
        self._after_ids.append(self.root.after(15000, self.tick))
        self._after_ids = self._after_ids[-3:]

    def poll_queue(self):
        if self._closing:
            return
        if self.guard and self.guard.show_requested():
            self.show()
        self._sync_poll_count = (self._sync_poll_count + 1) % 4
        if self._sync_poll_count == 0:
            self.consume_sync()
        while True:
            try:
                action = self.queue.get_nowait()
            except queue.Empty:
                break
            if action == 'quit':
                self.quit(); return
            elif action == 'show':
                self.show()
            elif action == 'add':
                self.open_editor()
            elif action == 'settings':
                self.open_settings()
            elif action == 'tray_ready' and self.tray:
                self.tray.ready = True
            elif action == 'tray_failed':
                if self.tray:
                    self.tray.ready = False
                self.show()
                messagebox.showwarning('托盘不可用', '请用窗口菜单退出程序，或重新启动。', parent=self.root)
        self._after_ids.append(self.root.after(750, self.poll_queue))
        self._after_ids = self._after_ids[-3:]

    def hide(self):
        if self.tray and self.tray.ready:
            self.remember_geometry()
            self.root.withdraw()
        else:
            self.root.iconify()

    def show(self):
        self.root.deiconify()
        self.root.attributes('-topmost', self.settings.topmost)
        style_window(self.root, dark=self.settings.theme == 'dark')

    def request_close(self):
        if self.settings.close_to_tray and self.tray and self.tray.ready:
            self.hide()
        else:
            self.quit()

    def quit(self):
        if self._closing:
            return
        if self.root.state() == 'normal':
            self.remember_geometry()
        if not self.save():
            return
        self._closing = True
        if self._geometry_after:
            self.root.after_cancel(self._geometry_after)
        # All after callbacks belong to this Tcl interpreter, including tooltip/dialog timers.
        for token in self.root.tk.call('after', 'info'):
            try:
                self.root.after_cancel(token)
            except tk.TclError:
                pass
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def export_data(self):
        path = filedialog.asksaveasfilename(parent=self.root, title='导出任务备份', defaultextension='.json',
                                           initialfile=f'DDLNotes-{datetime.now():%Y%m%d}.json',
                                           filetypes=[('JSON 备份', '*.json')])
        if path:
            try:
                self.store.export(path, self.tasks, self.settings)
            except OSError as exc:
                messagebox.showerror('无法导出', str(exc), parent=self.root)

    def import_data(self):
        path = filedialog.askopenfilename(parent=self.root, title='导入任务备份', filetypes=[('JSON 备份', '*.json')])
        if not path:
            return
        try:
            tasks, _ = self.store.read_import(path)
            if messagebox.askyesno('导入备份', f'用备份中的 {len(tasks)} 条任务替换当前任务？\n外观与自启动设置保持当前值。', parent=self.root):
                # Export the full current state before replacing tasks.
                backup = self.store.path.parent / f'before-import-{datetime.now():%Y%m%d-%H%M%S-%f}.json'
                self.store.export(backup, self.tasks, self.settings)
                self.tasks = tasks
                self.save(); self.render_tasks(); self.sync_alarm(); self.check_reminders()
        except (OSError, ValueError) as exc:
            messagebox.showerror('无法导入', str(exc), parent=self.root)

    def open_data_folder(self):
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        os.startfile(self.store.path.parent)
