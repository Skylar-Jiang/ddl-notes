"""Atomic JSON replacement and one previous-good backup, independent of cwd."""
import json
import logging
import os
import shutil
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .model import Settings, Task


def data_directory():
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'DDLNotes'


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_directory() / 'data.json'
        self.backup = self.path.with_suffix('.json.bak')
        self.warning = ''
        self._last_good = None

    @staticmethod
    def decode(content):
        try:
            data = json.loads(content)
            if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('tasks'), list):
                raise ValueError('不是有效的 DDL Notes v1 备份。')
            tasks = [Task.from_dict(item) for item in data['tasks']]
            if len({t.id for t in tasks}) != len(tasks):
                raise ValueError('备份包含重复任务 ID。')
            return tasks, Settings(**data.get('settings', {}))
        except (TypeError, KeyError, AttributeError, ValueError) as exc:
            raise ValueError(f'数据格式不正确：{exc}') from exc

    def load(self):
        self.warning = ''
        for path in (self.path, self.backup):
            if not path.exists():
                continue
            try:
                content = path.read_bytes()
                result = self.decode(content)
                self._last_good = content
                if path == self.backup:
                    self.warning += '已恢复上一次有效备份。'
                return result
            except (OSError, ValueError, UnicodeError):
                logging.exception('Cannot read %s', path)
                self.warning = '数据读取失败；原文件已保留。'
                if path == self.path:
                    try:
                        shutil.copy2(path, path.with_suffix(f'.json.corrupt-{datetime.now():%Y%m%d-%H%M%S-%f}'))
                    except OSError:
                        logging.exception('Cannot preserve corrupt file')
        return [], Settings()

    def save(self, tasks, settings):
        content = json.dumps({'version': 1, 'tasks': [t.to_dict() for t in tasks],
                              'settings': asdict(settings)}, ensure_ascii=False, indent=2).encode('utf-8')
        self.decode(content)
        if self._last_good is not None:
            atomic_write(self.backup, self._last_good)
        atomic_write(self.path, content)
        self._last_good = content

    def read_import(self, path):
        return self.decode(Path(path).read_bytes())

    def export(self, path, tasks, settings):
        content = json.dumps({'version': 1, 'tasks': [t.to_dict() for t in tasks],
                              'settings': asdict(settings)}, ensure_ascii=False, indent=2).encode('utf-8')
        atomic_write(Path(path), content)
