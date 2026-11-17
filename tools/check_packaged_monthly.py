"""Verify monthly rollover in the packaged app with isolated task data."""
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddl_notes.model import Task, Settings
from ddl_notes.storage import Store


def main():
    with tempfile.TemporaryDirectory(prefix='DDLNotes-monthly-') as temporary:
        directory = Path(temporary)
        store = Store(directory / 'data.json')
        task = Task.create('隔离每月续费', datetime(2000, 1, 1, 9), monthly_day=1)
        task.reminder.seen = ['upcoming', 'deadline']
        store.save([task], Settings())
        process = subprocess.Popen([str(ROOT / 'dist' / 'DDLNotes.exe'), '--data-dir', temporary],
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            now = datetime.now()
            expected = now.replace(day=1, hour=9, minute=0, second=0, microsecond=0).isoformat()
            for _ in range(60):
                saved = Store.decode(store.path.read_bytes())[0][0]
                if saved.deadline == expected and 'deadline' in saved.reminder.seen:
                    break
                time.sleep(.5)
            else:
                raise AssertionError('Packaged app did not advance and remind the monthly task')
            assert saved.id == task.id and saved.monthly_day == 1 and not saved.completed
            notified = saved.reminder.last_notified
            time.sleep(2)
            assert Store.decode(store.path.read_bytes())[0][0].reminder.last_notified == notified
            print('PASS: packaged app loads monthly rule, rolls missed months, saves and reminds once')
        finally:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            process.wait(timeout=10)
            time.sleep(.5)


if __name__ == '__main__':
    main()
