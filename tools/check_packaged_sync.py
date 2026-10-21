"""Exercise the packaged native bridge and app using an isolated LOCALAPPDATA."""
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from datetime import datetime, timedelta


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddl_notes.model import Task, Settings
from ddl_notes.storage import Store


def processes(name):
    command = (f"Get-CimInstance Win32_Process -Filter \"Name='{name}'\" | "
               'Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress')
    output = subprocess.check_output(['powershell', '-NoProfile', '-Command', command], text=True).strip()
    if not output:
        return []
    value = json.loads(output)
    return value if isinstance(value, list) else [value]


def main():
    payload = {'version': 1, 'source': 'yuketang', 'excluded_classroom_ids': ['10'], 'tasks': [
        {'external_id': 'smoke:1', 'title': '打包同步验证', 'course': '隔离测试',
         'deadline': '2030-01-01T20:00', 'completed': False}]}
    payload['tasks'].append({'external_id': 'smoke:expired', 'title': '不应导入的旧作业',
                             'deadline': '2000-01-01T20:00'})
    content = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    bridge = ROOT / 'dist' / 'DDLNotesSync.exe'
    owned_apps = []
    with tempfile.TemporaryDirectory(prefix='DDLNotes-packaged-sync-') as temporary:
        environment = dict(os.environ, LOCALAPPDATA=temporary)
        target = Path(temporary) / 'DDLNotes' / 'data.json'
        manual = Task.create('隔离手动旧任务', datetime.now()-timedelta(days=3))
        imported = Task.create('隔离旧导入', datetime.now()-timedelta(days=3), source_key='xiaoya:expired')
        manual.completed = imported.completed = True
        old_semester = Task.create('隔离旧学期无截止', source_key='yuketang:10:1')
        current = Task.create('隔离本学期无截止', source_key='yuketang:20:1')
        current.completed = True
        Store(target).save([manual, imported, old_semester, current], Settings())
        process = subprocess.Popen([str(bridge)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=environment,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            # PyInstaller onefile uses a bootloader and a child process.
            time.sleep(2)
            bridge_ids = {process.pid}
            bridge_ids.update(p['ProcessId'] for p in processes('DDLNotesSync.exe')
                              if p['ParentProcessId'] == process.pid)
            output, errors = process.communicate(struct.pack('<I', len(content)) + content, timeout=30)
            size, = struct.unpack('<I', output[:4])
            assert len(output) == size + 4, 'Malformed native response'
            reply = json.loads(output[4:])
            assert reply['ok'] is True and reply['tasks'] == 2, reply
            for _ in range(30):
                owned_apps = [p['ProcessId'] for p in processes('DDLNotes.exe')
                              if p['ParentProcessId'] in bridge_ids]
                if target.exists():
                    tasks = json.loads(target.read_text(encoding='utf-8'))['tasks']
                    if any(t['source_key'] == 'yuketang:smoke:1' for t in tasks):
                        break
                time.sleep(.5)
            else:
                raise AssertionError(f'Packaged app did not save sync data: {errors!r}')
            assert len(tasks) == 3 and {t['source_key'] for t in tasks} == {
                None, 'yuketang:20:1', 'yuketang:smoke:1'}, tasks
            assert next(t for t in tasks if t['source_key'] == 'yuketang:smoke:1')['title'] == '隔离测试 · 打包同步验证'
            backup, = target.parent.glob('before-sync-cleanup-*.json')
            assert [t.id for t in Store(backup).load()[0]] == [manual.id, imported.id, old_semester.id, current.id]
            assert not list((target.parent / 'inbox').glob('*.json'))
            print('PASS: packaged native -> GUI -> save; expired/old-semester imports cleaned, manual/current tasks kept, recovery backup saved')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            for pid in owned_apps:
                subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)
            time.sleep(.5)


if __name__ == '__main__':
    main()
