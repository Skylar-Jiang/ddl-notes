'use strict';
// Authentication is used only inside the platform tab; never sent to the native host.
function cookieEntries() {
  return document.cookie.split(';').filter(Boolean).map(item => {
    const split = item.indexOf('=');
    return [decodeURIComponent(item.slice(0, split).trim()), decodeURIComponent(item.slice(split + 1))];
  });
}
async function platformHttpError(response, cookies) {
  let message;
  if (response.status === 400) message = '平台拒绝请求（400）：需核对该课程的接口参数。';
  else if (response.status === 401) message = '平台未授权（401），登录可能失效，请在当前浏览器重新登录。';
  else if (response.status === 403) message = '平台拒绝访问（403），当前账号可能没有该课程的读取权限。';
  else message = `平台读取失败（${response.status}）。`;
  try {
    if (response.headers.get('content-type')?.includes('json')) {
      const body = await response.json();
      const code = body.code ?? body.errcode;
      if (/^-?\d{1,12}$/.test(String(code))) message += ` 错误码：${code}。`;
      let detail = body.msg || body.message || body.detail;
      if (typeof detail === 'string') {
        for (const [key, value] of cookies) {
          if (value && /session|token|auth|ticket|jwt|sid/i.test(key)) detail = detail.split(value).join('[凭证已隐藏]');
        }
        detail = detail.replace(/Bearer\s+[^\s;,]+/gi, '[凭证已隐藏]')
          .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, '[凭证已隐藏]');
        message += ` 平台说明：${detail.replace(/[\x00-\x1f]/g, ' ').slice(0, 300)}`;
      }
    }
  } catch { /* Keep the HTTP status when an error body is not valid JSON. */ }
  return new Error(message);
}
async function readPlatform(source) {
  const expected = source === 'xiaoya' ? 'nankai.ai-augmented.com' : 'changjiang.yuketang.cn';
  if (location.hostname !== expected) throw new Error('平台标签页不匹配。');
  const cookies = cookieEntries();
  const cookie = name => cookies.find(([key]) => key === name)?.[1];
  let headers = {};
  const context = {};
  if (source === 'xiaoya') {
    const tokens = cookies.filter(([key]) => /(^|[-_])access[-_]token$/i.test(key));
    if (tokens.length !== 1) throw new Error('未识别到小雅登录状态，请在此浏览器重新登录小雅。');
    headers.Authorization = `Bearer ${tokens[0][1]}`;
  } else {
    const university = cookie('university_id') || cookie('university-id') || cookie('uv_id');
    const platform = cookie('platform_id');
    if (university) {
      headers['university-id'] = university;
      headers['uv-id'] = university;
      context.uv_id = university;
    }
    if (platform) context.platform_id = platform;
    headers.xtbz = 'ykt';
    if (cookie('csrftoken')) headers['X-CSRFToken'] = cookie('csrftoken');
  }
  let requests = 0;
  const started = Date.now();
  const get = async (path, params = {}) => {
    if (++requests > 1200 || Date.now() - started > 240000) throw new Error('本次读取量过大或耗时过长，尚未导入。');
    // Keep the MV3 worker alive while a large course is being read with the popup closed.
    chrome.runtime.sendMessage({type: 'heartbeat'}).catch(() => {});
    const url = new URL(path, location.origin);
    if (url.origin !== location.origin || !path.startsWith('/')) throw new Error('拒绝跨站读取。');
    url.search = new URLSearchParams({...context, ...params}).toString();
    const requestHeaders = {...headers};
    if (source === 'yuketang') {
      const university = params.uv_id || params.university_id;
      if (university) requestHeaders['university-id'] = requestHeaders['uv-id'] = university;
      if (params.classroom_id) requestHeaders['classroom-id'] = params.classroom_id;
    }
    let response;
    try {
      response = await fetch(url, {method: 'GET', credentials: 'include', headers: requestHeaders,
        redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(20000)});
    } catch {
      throw new Error('平台读取超时或网络异常，本次数据未导入。');
    }
    if (!response.ok) throw await platformHttpError(response, cookies);
    if (!response.headers.get('content-type')?.includes('json')) throw new Error('平台返回了登录页，请先登录。');
    return response.json();
  };
  return DDLReaders.collect(source, get, text => {
    chrome.runtime.sendMessage({type: 'progress', text}).catch(() => {});
  });
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || message.type !== 'collect') return;
  readPlatform(message.source).then(payload => respond({ok: true, payload}),
    error => respond({ok: false, message: error.message}));
  return true;
});
