import os
import subprocess
import sys
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from ddl_notes.windows import Startup, InstanceGuard, startup_command


@unittest.skipUnless(os.name == 'nt', 'Windows integration')
class WindowsTests(unittest.TestCase):
    def test_source_startup_command_uses_absolute_pythonw(self):
        command = startup_command()
        self.assertIn('pythonw.exe', command)
        self.assertIn(str(Path(__file__).resolve().parents[1] / 'run.py'), command)
        self.assertIn('--startup', command)

    def test_packaged_startup_command_uses_executable_not_unpack_directory(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', r'C:\Program Files\DDL Notes\DDLNotes.exe'):
            self.assertEqual(startup_command(), '"C:\\Program Files\\DDL Notes\\DDLNotes.exe" --startup')

    def test_user_registry_enable_disable(self):
        startup = Startup(name='DDLNotes-Test-' + str(uuid4()))
        self.addCleanup(startup.disable)
        self.assertFalse(startup.enabled())
        startup.enable()
        self.assertTrue(startup.enabled())
        startup.enable()
        self.assertEqual(startup.command(), startup_command())
        startup.disable()
        self.assertFalse(startup.enabled())

    def test_single_instance_signal_and_release(self):
        name = 'DDLNotes-Test-' + str(uuid4())
        first = InstanceGuard(name)
        self.addCleanup(first.close)
        self.assertTrue(first.acquire())
        child = subprocess.run([sys.executable, '-c',
            'from ddl_notes.windows import InstanceGuard; '
            f'g=InstanceGuard({name!r}); print(g.acquire()); g.close()'],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertIn('False', child.stdout)
        self.assertTrue(first.show_requested())
        self.assertFalse(first.show_requested())
        first.close()
        next_instance = InstanceGuard(name)
        self.addCleanup(next_instance.close)
        self.assertTrue(next_instance.acquire())
