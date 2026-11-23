import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from ddl_notes.background_browser import HOMES, execute_reader, save_session, load_session, queue_payload


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'Optional desktop sync dependency')
class BackgroundBrowserTests(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.p = sync_playwright().start()
        self.browser = self.p.chromium.launch(channel='msedge', headless=True)
        self.addCleanup(self.close)

    def close(self):
        self.browser.close()
        self.p.stop()

    def fixture(self, context, *, broken=False):
        def handle(route):
            path = urlsplit(route.request.url).path
            routes = {
                '/api/jx-iresource/group/student/groups': {'code': 0, 'data': [{'id': 7, 'name': '隔离课程'}]},
                '/api/jx-iresource/resource/queryCourseResources/v2': {'code': 0, 'data': [
                    {'id': 8, 'task_id': 9, 'task_type': 2, 'name': '隔离作业', 'end_time': '2030-01-01T20:00:00+08:00'}]},
                '/api/jx-iresource/resource/task/studentFinishInfo/v2': {'code': 0, 'data': {'finished': False}},
                '/v2/api/web/courses/list': {'errcode': 0, 'data': {'list': []}},
            }
            if path in routes:
                route.fulfill(content_type='application/json', body=json.dumps(
                    {'code': 401} if broken else routes[path]))
            else:
                route.fulfill(content_type='text/html', body='<title>Isolated platform fixture</title>')
        context.route('https://**/*', handle)

    def test_existing_reader_runs_in_headless_edge_and_emits_metadata_only(self):
        context = self.browser.new_context()
        context.add_cookies([{'name': 'nku-access-token', 'value': 'fake-test-secret',
                              'url': 'https://nankai.ai-augmented.com'}])
        self.fixture(context)
        page = context.new_page()
        page.goto(HOMES['xiaoya'])
        self.assertTrue(execute_reader(page, 'xiaoya', probe=True)['ok'])
        result = execute_reader(page, 'xiaoya')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['payload']['tasks'][0]['external_id'], '7:9')
        self.assertNotIn('fake-test-secret', json.dumps(result))
        directory = Path(self.temp.name)
        queue_payload(directory, result['payload'])
        self.assertEqual(len(list((directory/'inbox').glob('*.json'))), 1)

    def test_session_only_cookie_restored_after_browser_is_closed(self):
        context = self.browser.new_context()
        context.add_cookies([{'name': 'nku-access-token', 'value': 'fake-session-only',
                              'url': 'https://nankai.ai-augmented.com'}])
        target = Path(self.temp.name)/'xiaoya.bin'
        save_session(context, target)
        self.assertNotIn(b'fake-session-only', target.read_bytes())
        self.browser.close()
        self.browser = self.p.chromium.launch(channel='msedge', headless=True)
        context = self.browser.new_context(storage_state=load_session(target))
        self.fixture(context)
        page = context.new_page()
        page.goto(HOMES['xiaoya'])
        self.assertTrue(execute_reader(page, 'xiaoya')['ok'])

    def test_expired_login_does_not_queue_empty_batch(self):
        context = self.browser.new_context()
        self.fixture(context)
        page = context.new_page()
        page.goto(HOMES['xiaoya'])
        result = execute_reader(page, 'xiaoya')
        self.assertFalse(result['ok'])
        self.assertTrue(result['needs_login'])
        self.assertNotIn('payload', result)

    def test_rain_probe_and_schema_failure(self):
        context = self.browser.new_context()
        self.fixture(context)
        page = context.new_page()
        page.goto(HOMES['yuketang'])
        self.assertTrue(execute_reader(page, 'yuketang', probe=True)['ok'])
        self.assertEqual(execute_reader(page, 'yuketang')['payload']['tasks'], [])
        self.fixture(context, broken=True)
        self.assertFalse(execute_reader(page, 'yuketang')['ok'])

    def test_invalid_payload_never_enters_inbox(self):
        directory = Path(self.temp.name)
        with self.assertRaises(ValueError):
            queue_payload(directory, {'version': 1, 'source': 'unknown', 'tasks': []})
        self.assertFalse((directory/'inbox').exists())
