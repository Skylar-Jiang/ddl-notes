"""Dedicated Edge sessions; only task metadata is sent to the desktop inbox."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .auto_sync import NAMES
from .course_sync import parse_sync
from .session_store import seal, unseal
from .storage import atomic_write


HOMES = {'xiaoya': 'https://nankai.ai-augmented.com/app/jx-web/mycourse',
         'yuketang': 'https://changjiang.yuketang.cn/v2/web/index'}


def execute_reader(page, source, *, probe=False):
    directory = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])) / 'browser-helper'
    return page.evaluate('''async ({source, probe, readers, client}) => {
      const expected = source === 'xiaoya' ? 'nankai.ai-augmented.com' : 'changjiang.yuketang.cn';
      if (location.hostname !== expected) return {ok:false, needs_login:true, message:'请重新登录平台。'};
      const chrome = {runtime:{onMessage:{addListener(){}},sendMessage:async()=>{}}};
      try {
        const api = new Function('chrome', readers + '\\n' + client +
          '\\nreturn {readPlatform, platformClient};')(chrome);
        if (probe) {
          const response = await api.platformClient(source)(source === 'xiaoya' ?
            '/api/jx-iresource/group/student/groups' : '/v2/api/web/courses/list',
            source === 'xiaoya' ? {time_flag:1} : {identity:2});
          const ok = response.success !== false && !response.errcode &&
            (response.code === undefined || [0,200,'0','200'].includes(response.code)) &&
            (source === 'xiaoya' ? Array.isArray(response.data) : Array.isArray(response.data?.list));
          return {ok, needs_login:!ok, message:ok ? '登录已验证' : '请重新登录平台。'};
        }
        return {ok:true,payload:await api.readPlatform(source)};
      } catch (error) {
        return {ok:false,needs_login:/登录|未授权|login/i.test(error.message),message:error.message.slice(0,1000)};
      }
    }''', {'source': source, 'probe': probe,
           'readers': (directory / 'readers.js').read_text(encoding='utf-8'),
           'client': (directory / 'content.js').read_text(encoding='utf-8')})


def load_session(path):
    try:
        return json.loads(unseal(path.read_bytes()))
    except (OSError, ValueError):
        return None


def save_session(context, path):
    state = json.dumps(context.storage_state(), ensure_ascii=False).encode('utf-8')
    atomic_write(path, seal(state))


def queue_payload(directory, payload):
    parse_sync(payload)
    path = directory / 'inbox' / f'{time.time_ns():020d}-{uuid4().hex}.json'
    atomic_write(path, json.dumps(payload, ensure_ascii=False).encode('utf-8'))


def run_job(directory, job, action, sources):
    from playwright.sync_api import sync_playwright
    directory, job = Path(directory), Path(job)
    job.mkdir(parents=True, exist_ok=True)
    results = []

    def report(**changes):
        state = {'stage': 'running', 'results': results, **changes}
        atomic_write(job / 'status.json', json.dumps(state, ensure_ascii=False).encode('utf-8'))

    def cancelled():
        return (job / 'cancel').exists()

    for source in sources:
        if cancelled():
            break
        session = directory / 'auto-sync-auth' / f'{source}.bin'
        report(message=f'{NAMES[source]}：' + ('请在独立窗口登录，成功后自动关闭。' if action == 'login' else '正在后台读取…'))
        try:
            state = load_session(session)
            if action == 'sync' and state is None:
                results.append({'source': source, 'ok': False, 'needs_login': True, 'message': '请先在自动同步设置中登录。'})
                continue
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='msedge', headless=action != 'login')
                try:
                    context = browser.new_context(storage_state=state, viewport=None)
                    page = context.new_page()
                    page.goto(HOMES[source], wait_until='domcontentloaded', timeout=30000)
                    if action == 'login':
                        end = time.monotonic() + 900
                        result = {'ok': False, 'message': '登录未完成，请重试。', 'needs_login': True}
                        while time.monotonic() < end and not cancelled():
                            if page.is_closed():
                                break
                            try:
                                result = execute_reader(page, source, probe=True)
                                if result['ok']:
                                    save_session(context, session)
                                    result['message'] = '登录已保存，可以关闭日常浏览器并后台同步。'
                                    break
                            except Exception:
                                # Navigation during interactive login is expected.
                                pass
                            for _ in range(5):
                                if cancelled() or page.is_closed():
                                    break
                                page.wait_for_timeout(1000)
                    else:
                        result = execute_reader(page, source)
                        if result['ok'] and not cancelled():
                            payload = result.pop('payload')
                            queue_payload(directory, payload)
                            save_session(context, session)
                            result['message'] = f'已发送 {len(payload["tasks"])} 条任务到便签。'
                    results.append({'source': source, **result})
                finally:
                    browser.close()
        except Exception:
            # Never persist a browser traceback, cookies, credentials or storage state.
            results.append({'source': source, 'ok': False,
                            'message': '后台操作未完成，请检查网络、Edge 安装或重新登录。'})
    report(stage='done', results=results, finished_at=datetime.now(timezone.utc).isoformat())
