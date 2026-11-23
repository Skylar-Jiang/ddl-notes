"""Nonblocking desktop scheduling; browser work runs in an owned subprocess."""
import json
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from .storage import atomic_write


NAMES = {'xiaoya': '小雅', 'yuketang': '雨课堂'}


class AutoSync:
    def __init__(self, directory, *, launch=None, clock=None):
        self.directory = Path(directory)
        self.launch = launch or subprocess.Popen
        self.clock = clock or time.monotonic
        self.process = None
        self.next_run = None
        self.needs_login = set()
        self.status = '自动同步未开启；请先登录课程平台。'
        self.job_directory = None

    def configure(self, settings):
        self.next_run = self.clock() + 5 if settings.auto_sync_enabled else None

    def start(self, action, sources):
        if self.process:
            raise ValueError('已有登录或同步正在进行，请稍候。')
        if action not in ('login', 'sync') or not sources or any(s not in NAMES for s in sources):
            raise ValueError('请选择有效的课程平台。')
        if action == 'login' and len(sources) != 1:
            raise ValueError('请逐个平台登录。')
        if getattr(sys, 'frozen', False):
            worker = Path(sys.executable).parent / 'DDLNotesAutoSync' / 'DDLNotesAutoSync.exe'
            if not worker.is_file():
                raise ValueError('缺少自动同步组件，请下载完整新版压缩包并解压。')
            command = [str(worker)]
        else:
            command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'sync_worker.py')]
        self.job_directory = self.directory / 'auto-sync' / uuid4().hex
        self.job_directory.mkdir(parents=True)
        self.status_path = self.job_directory / 'status.json'
        self.action = action
        command += ['--data-dir', str(self.directory), '--job-dir', str(self.job_directory),
                    '--action', action, '--sources', *sources]
        self.process = self.launch(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.started = self.clock()
        self.status = '请在弹出的独立窗口登录，登录成功后窗口自动关闭。' if action == 'login' else '正在后台读取课程…'

    def poll(self, settings):
        if self.process:
            state = {}
            try:
                state = json.loads(self.status_path.read_bytes())
            except (OSError, ValueError):
                pass
            if self.process.poll() is None:
                if self.clock() - self.started > (930 if self.action == 'login' else 600):
                    self.close()
                    self.status = '后台操作超时，请检查网络或重新登录。'
                    self.next_run = self.clock() + settings.auto_sync_minutes * 60
                elif state.get('message'):
                    self.status = state['message']
                return
            self.process = None
            if state.get('stage') == 'done':
                results = state.get('results', [])
                for result in results:
                    source = result.get('source')
                    if source not in NAMES:
                        continue
                    if result.get('ok'):
                        self.needs_login.discard(source)
                    elif result.get('needs_login'):
                        self.needs_login.add(source)
                self.status = '；'.join(f'{NAMES[r["source"]]}：{r["message"]}'
                                       for r in results if r.get('source') in NAMES)
                atomic_write(self.directory / 'auto-sync-last.json', json.dumps(state, ensure_ascii=False).encode('utf-8'))
            else:
                self.status = '后台组件意外退出，请重试登录或同步。'
            delay = 5 if self.action == 'login' else settings.auto_sync_minutes * 60
            self.next_run = self.clock() + delay
            for name in ('status.json', 'cancel'):
                (self.job_directory / name).unlink(missing_ok=True)
            self.job_directory.rmdir()
        if not settings.auto_sync_enabled:
            self.next_run = None
            return
        if self.next_run is None:
            self.configure(settings)
        if self.clock() >= self.next_run:
            sources = [s for s in NAMES if getattr(settings, f'sync_{s}') and s not in self.needs_login]
            self.next_run = self.clock() + settings.auto_sync_minutes * 60
            if sources:
                try:
                    self.start('sync', sources)
                except (OSError, ValueError) as exc:
                    self.status = str(exc)

    def close(self):
        if self.process and self.process.poll() is None:
            (self.job_directory / 'cancel').touch()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        self.process = None
