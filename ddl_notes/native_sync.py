"""One-shot Chrome/Edge native messaging bridge; receives task metadata only."""
import json
import logging
import re
import struct
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from .course_sync import parse_sync
from .storage import atomic_write, data_directory


HOST_NAME = 'com.ddlnotes.sync'
MAX_MESSAGE = 1_000_000


def read_message(stream):
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise ValueError('同步消息头不完整。')
    size, = struct.unpack('<I', header)
    if not 0 < size <= MAX_MESSAGE:
        raise ValueError('同步数据过大。')
    content = stream.read(size)
    if len(content) != size:
        raise ValueError('同步数据不完整。')
    return json.loads(content)


def write_message(stream, value):
    content = json.dumps(value, ensure_ascii=False).encode('utf-8')
    stream.write(struct.pack('<I', len(content)))
    stream.write(content)
    stream.flush()


def launch_app():
    if getattr(sys, 'frozen', False):
        command = [str(Path(sys.executable).with_name('DDLNotes.exe'))]
    else:
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        command = [str(pythonw), str(Path(__file__).resolve().parents[1] / 'run.py')]
    subprocess.Popen(command, close_fds=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def receive_sync(payload, directory=None):
    batch = parse_sync(payload)
    directory = Path(directory) if directory else data_directory()
    path = directory / 'inbox' / f'{time.time_ns():020d}-{uuid4().hex}.json'
    atomic_write(path, json.dumps(payload, ensure_ascii=False).encode('utf-8'))
    try:
        launch_app()
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return {'ok': True, 'tasks': len(batch.tasks), 'message': '同步数据已发送到便签。'}


def host_manifest(extension_id, executable):
    if not isinstance(extension_id, str) or not re.fullmatch('[a-p]{32}', extension_id):
        raise ValueError('扩展 ID 应为 32 位 a-p 字母，请从浏览器扩展管理页复制。')
    return {'name': HOST_NAME, 'description': 'DDL Notes course sync', 'type': 'stdio',
            'path': str(Path(executable).resolve()),
            'allowed_origins': [f'chrome-extension://{extension_id}/']}


def register_host(extension_id, executable, directory=None):
    import winreg
    executable = Path(executable)
    if not executable.is_file():
        raise ValueError('缺少 DDLNotesSync.exe，请先完成打包，并将它与主程序放在同一目录。')
    manifest = host_manifest(extension_id.strip(), executable)
    directory = Path(directory) if directory else data_directory()
    path = directory / 'native-host.json'
    atomic_write(path, json.dumps(manifest, indent=2).encode('utf-8'))
    for browser_key in ('Google\\Chrome', 'Microsoft\\Edge'):
        key_path = f'Software\\{browser_key}\\NativeMessagingHosts\\{HOST_NAME}'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, '', 0, winreg.REG_SZ, str(path.resolve()))


def main():
    try:
        payload = read_message(sys.stdin.buffer)
        if payload is not None:
            write_message(sys.stdout.buffer, receive_sync(payload))
    except (OSError, ValueError, TypeError):
        logging.exception('Course sync bridge failed')
        write_message(sys.stdout.buffer, {'ok': False, 'message': '同步数据未接收，请检查连接与数据格式。'})
