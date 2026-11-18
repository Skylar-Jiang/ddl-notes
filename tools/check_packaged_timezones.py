"""Verify legacy Beijing deadlines in the packaged app with isolated data."""
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddl_notes.model import Task, Settings
from ddl_notes.storage import Store


def main():
    with tempfile.TemporaryDirectory(prefix='DDLNotes-timezones-') as temporary:
        path = Path(temporary) / 'data.json'
        due = datetime.now(timezone.utc) + timedelta(minutes=30)
        tasks = [Task.create('隔离手动作业', due),
                 Task.create('隔离导入作业', due, source_key='xiaoya:test')]
        Store(path).save(tasks, Settings())
        payload = json.loads(path.read_bytes())
        for task in payload['tasks']:
            task.pop('deadline_timezone')
            task['reminder']['seen'] = ['upcoming', 'deadline']
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        process = subprocess.Popen([str(ROOT / 'dist' / 'DDLNotes.exe'), '--data-dir', temporary],
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(60):
                saved = json.loads(path.read_bytes())['tasks']
                if all(t.get('deadline_timezone') == 'Asia/Shanghai' and
                       t['reminder']['seen'] == ['upcoming'] for t in saved):
                    break
                time.sleep(.5)
            else:
                raise AssertionError('Packaged app did not migrate and remind at the correct instant')
            assert [t['deadline'] for t in saved] == [t.deadline for t in tasks]
            assert [t['id'] for t in saved] == [t.id for t in tasks]
            for task in saved:
                assert datetime.fromisoformat(task['reminder']['last_notified']).tzinfo is not None
            print('PASS: packaged app migrates manual/imported Beijing deadlines and sends upcoming, not overdue, reminders')
        finally:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            process.wait(timeout=10)
            time.sleep(.5)


if __name__ == '__main__':
    main()
