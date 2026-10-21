import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ddl_notes.native_sync import read_message, write_message, receive_sync, host_manifest


PAYLOAD = {'version': 1, 'source': 'yuketang', 'tasks': [
    {'external_id': 'course1:task1', 'title': '作业', 'course': '课程',
     'deadline': '2026-10-22T20:00', 'completed': False,
     'url': 'https://changjiang.yuketang.cn/v2/web/index'}]}


class NativeSyncTests(unittest.TestCase):
    def test_native_message_roundtrip_unicode(self):
        stream = io.BytesIO()
        write_message(stream, PAYLOAD)
        stream.seek(0)
        self.assertEqual(read_message(stream), PAYLOAD)
        self.assertIsNone(read_message(stream))

    def test_reject_truncation_and_oversize(self):
        for data in (b'\x01', struct.pack('<I', 5) + b'{}', struct.pack('<I', 2_000_000)):
            with self.subTest(data=data[:5]):
                with self.assertRaises(ValueError):
                    read_message(io.BytesIO(data))

    def test_validated_batch_goes_to_inbox_and_launches_app(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            with patch('ddl_notes.native_sync.launch_app') as launch:
                response = receive_sync(PAYLOAD, directory)
            self.assertTrue(response['ok'])
            launch.assert_called_once()
            path, = (directory / 'inbox').glob('*.json')
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), PAYLOAD)

    def test_invalid_batch_does_not_write_or_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            with patch('ddl_notes.native_sync.launch_app') as launch:
                with self.assertRaises(ValueError):
                    receive_sync({'version': 1, 'source': 'unknown', 'tasks': []}, directory)
            launch.assert_not_called()
            self.assertFalse((directory / 'inbox').exists())

    def test_manifest_restricts_extension_origin(self):
        manifest = host_manifest('a'*32, Path('C:/DDL Notes/DDLNotesSync.exe'))
        self.assertEqual(manifest['allowed_origins'], ['chrome-extension://'+'a'*32+'/'])
        self.assertEqual(manifest['type'], 'stdio')
        for invalid in ('', 'a'*31, 'z'*32, 'a'*32+'/evil'):
            with self.assertRaises(ValueError):
                host_manifest(invalid, Path('C:/DDLNotesSync.exe'))
