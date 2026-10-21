const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const {collect, deadline} = require('../browser-helper/readers.js');

test('deadlines keep China time, unknown dates fail instead of becoming today', () => {
  assert.equal(deadline(1792497600), '2026-10-20T20:00');
  assert.equal(deadline(1792497600000), '2026-10-20T20:00');
  assert.equal(deadline('2026-10-20 20:00:30'), '2026-10-20T20:00');
  assert.equal(deadline(null), null);
  assert.equal(deadline(0), null);
  for (const value of ['tomorrow', '2026-10-20', '2026-02-30 20:00:00']) {
    assert.throws(() => deadline(value));
  }
});

test('Xiaoya publishes ISO timestamps with Z, fractions and explicit offsets', () => {
  for (const value of ['2026-10-26T15:59:00.000Z', '2026-10-26T23:59:00+08:00',
    '2026-10-26T23:59:00.123+0800', '2026-10-26T23:59:00.000']) {
    assert.equal(deadline(value), '2026-10-26T23:59');
  }
  assert.equal(deadline('2026-10-26T16:30:00Z'), '2026-10-27T00:30');
  for (const value of ['2026-02-30T12:00:00Z', '2026-10-26T24:00:00Z',
    '2026-10-26T23:59:00+25:00', [1792497600]]) assert.throws(() => deadline(value));
});

function transport(routes, calls) {
  return async (path, params = {}) => {
    calls.push({path, params});
    const value = routes[path];
    assert.notEqual(value, undefined, `unexpected GET ${path}`);
    return typeof value === 'function' ? value(params) : value;
  };
}

test('rain reads every course and nested assignment, ignores attendance and course end', async () => {
  const calls = [];
  const routes = {
    '/v2/api/web/courses/list': {errcode: 0, data: {list: [
      {classroom_id: 10, name: '2026秋-1班', course: {name: '数据库'}},
      {classroom_id: 20, name: '2026秋-2班', course: {name: '英语'}}]}},
    '/mooc-api/v1/lms/learn/course/chapter': ({cid}) => ({success: true, data: {course_chapter: [
      {section_leaf_list: [{id: 1, leaf_type: 8, name: '签到', score_deadline: 1792497600},
        {id: 999, leaf_type: 6, name: '未解锁', is_locked: true},
        {leaf_list: [{id: Number(cid) + 1, leaf_type: 6, name: '作业'},
          {id: Number(cid) + 2, leaf_type: 5, name: '测验'}]}]}]}}),
    '/mooc-api/v1/lms/learn/course/schedule': {success: true, data: {leaf_schedules: {'12': 100}}},
  };
  for (const cid of [10, 20]) for (const id of [cid + 1, cid + 2]) {
    routes[`/mooc-api/v1/lms/learn/leaf_info/${cid}/${id}/`] = {
      success: true, data: {score_deadline: id === 21 ? null : 1792497600000}};
  }
  for (const cid of [10, 20]) routes[`/v2/api/web/classrooms/${cid}`] = {
    errcode: 0, data: {course_sign: `sign${cid}`}};
  const result = await collect('yuketang', transport(routes, calls));
  assert.equal(result.tasks.length, 4);
  assert.equal(result.tasks[0].external_id, '10:11');
  assert.equal(result.tasks[1].completed, true);
  assert.equal(result.tasks[2].deadline, null);
  assert.ok(result.tasks.every(t => t.title !== '签到'));
  assert.deepEqual(calls[0].params, {identity: 2});
  assert.deepEqual(Object.keys(result).sort(), ['excluded_classroom_ids', 'source', 'tasks', 'version']);
  assert.deepEqual(result.excluded_classroom_ids, []);
});

test('rain student list uses classroom_id rather than the course metadata id', async () => {
  const calls = [];
  const routes = {
    '/v2/api/web/courses/list': {errcode: 0, data: {list: [
      {classroom_id: 10, name: '2026秋-1班', course: {id: 9000, name: '数据库'}},
      {classroom_id: 20, id: 9000, name: '2026秋-2班', course: {id: 9000, name: '数据库'}}]}},
    '/mooc-api/v1/lms/learn/course/chapter': ({cid, classroom_id}) => {
      assert.ok(['10', '20'].includes(cid));
      assert.equal(classroom_id, cid);
      return {success: true, data: {course_chapter: [
        {section_leaf_list: [{id: 1, leaf_type: 6, name: '第一次作业'}]}]}};
    },
    '/mooc-api/v1/lms/learn/course/schedule': {success: true, data: {leaf_schedules: []}},
  };
  for (const cid of [10, 20]) {
    routes[`/mooc-api/v1/lms/learn/leaf_info/${cid}/1/`] = {
      success: true, data: {score_deadline: 1792497600000}};
    routes[`/v2/api/web/classrooms/${cid}`] = {errcode: 0, data: {course_sign: `sign${cid}`}};
  }
  const result = await collect('yuketang', transport(routes, calls));
  assert.deepEqual(result.tasks.map(task => task.external_id), ['10:1', '20:1']);
  assert.ok(result.tasks[0].url.includes('/studentLog/10?'));
  assert.ok(result.tasks[1].url.includes('/studentLog/20?'));
  assert.equal(calls.some(call => Object.values(call.params).includes('9000')), false);
});

test('rain does not substitute a course metadata id when classroom_id is absent', async () => {
  let calls = 0;
  await assert.rejects(collect('yuketang', async path => {
    calls++;
    if (path === '/v2/api/web/courses/list') return {errcode: 0, data: {list: [
      {id: 9000, name: '2026秋-1班', course: {id: 9000, name: '数据库'}}]}};
    return {success: true, data: {course_chapter: [], leaf_schedules: []}};
  }), /course.classroom_id/);
  assert.equal(calls, 1);
});

test('rain resolves course context before content, progress and assignment requests', async () => {
  const calls = [];
  const expected = {cid: '10', classroom_id: '10', uv_id: '2651', university_id: '2651',
    platform_id: '3', sign: 'rain-sign'};
  const routes = {
    '/v2/api/web/courses/list': {errcode: 0, data: {list: [
      {classroom_id: 10, name: '2026秋-1班', course: {name: '课', university_id: 111, platform: 3}}]}},
    '/v2/api/web/classrooms/10': params => {
      assert.equal(params.role, 5);
      assert.equal(params.uv_id, '111');
      return {errcode: 0, data: {course_sign: 'rain-sign', uv_id: 2651, platform: 3}};
    },
    '/mooc-api/v1/lms/learn/course/chapter': params => {
      assert.deepEqual(params, expected);
      return {success: true, data: {course_chapter: [
        {section_leaf_list: [{id: 11, leaf_type: 6, name: '作业'}]}]}};
    },
    '/mooc-api/v1/lms/learn/course/schedule': params => {
      assert.deepEqual(params, expected);
      return {success: true, data: {leaf_schedules: {}}};
    },
    '/mooc-api/v1/lms/learn/leaf_info/10/11/': params => {
      const {cid, ...leafParams} = expected;
      assert.deepEqual(params, leafParams);
      return {success: true, data: {score_deadline: null}};
    },
  };
  assert.equal((await collect('yuketang', transport(routes, calls))).tasks.length, 1);
  assert.equal(calls[1].path, '/v2/api/web/classrooms/10');
});

test('rain does not request assignment progress for courses containing only attendance', async () => {
  const calls = [];
  const routes = {
    '/v2/api/web/courses/list': {errcode: 0, data: {list: [
      {classroom_id: 10, name: '2026秋-1班', course: {name: '无作业课程'}}]}},
    '/v2/api/web/classrooms/10': {errcode: 0, data: {course_sign: 'sign10', uv_id: 2651, platform: 3}},
    '/mooc-api/v1/lms/learn/course/chapter': {success: true, data: {course_chapter: [
      {section_leaf_list: [{id: 1, leaf_type: 8, name: '签到'}]}]}},
  };
  assert.deepEqual((await collect('yuketang', transport(routes, calls))).tasks, []);
  assert.equal(calls.length, 3);
});

test('rain filters to explicitly labelled 2026 autumn classes before reading any course', async () => {
  const calls = [];
  const routes = {
    '/v2/api/web/courses/list': {errcode: 0, data: {list: [
      {classroom_id: 10, name: '2026秋-2026', course: {name: '数据库'}},
      {classroom_id: 20, name: '2026年 秋学期-2班', course: {name: '网络'}},
      {classroom_id: 30, name: '2025秋-2025', course: {name: '旧课程'}},
      {classroom_id: 40, name: '2026春-0999', course: {name: '春季课'}},
      {classroom_id: 50, name: '2024秋-1111', course: {name: '2026秋专题'}},
      {classroom_id: 60, name: '1班', course: {name: '无学期标记'}},
    ]}},
    '/mooc-api/v1/lms/learn/course/chapter': {success: true, data: {course_chapter: [
      {section_leaf_list: [{id: 1, leaf_type: 6, name: '作业'}]}]}},
    '/mooc-api/v1/lms/learn/course/schedule': {success: true, data: {leaf_schedules: {}}},
  };
  for (const cid of [10, 20]) {
    routes[`/v2/api/web/classrooms/${cid}`] = {errcode: 0, data: {course_sign: `sign${cid}`}};
    routes[`/mooc-api/v1/lms/learn/leaf_info/${cid}/1/`] = {
      success: true, data: {score_deadline: '2027-01-20T23:59:00+08:00'}};
  }
  const result = await collect('yuketang', transport(routes, calls));
  assert.deepEqual(result.tasks.map(task => task.external_id), ['10:1', '20:1']);
  assert.equal(result.tasks[0].deadline, '2027-01-20T23:59');
  assert.equal(calls.some(call => ['30', '40', '50', '60'].includes(call.params.classroom_id)), false);
  assert.deepEqual(result.excluded_classroom_ids, ['30', '40', '50']);
});

test('rain schema/auth failure aborts whole batch, never silently reports zero', async () => {
  for (const response of [{errcode: 401, data: {}}, {success: true, data: {}}]) {
    await assert.rejects(collect('yuketang', async () => response));
  }
  await assert.rejects(collect('yuketang', transport({
    '/v2/api/web/courses/list': {errcode: 0, data: {list: [
      {classroom_id: 1, name: '2026秋-1班', course: {name: '课'}}]}},
    '/v2/api/web/classrooms/1': {errcode: 0, data: {}},
    '/mooc-api/v1/lms/learn/course/chapter': {success: false},
  }, [])));
});

test('xiaoya traverses courses and resource folders with stable task IDs', async () => {
  const routes = {
    '/api/jx-iresource/group/student/groups': {code: 0, data: [{id: 7, name: '编译原理'}]},
    '/api/jx-iresource/resource/queryCourseResources/v2': {code: 0, data: [
      {children: [{id: 8, task_id: 9, task_type: 2, name: '第一次作业', end_time: 1792497600},
        {id: 10, task_id: 11, task_type: 1, name: '视频'}]}]},
    '/api/jx-iresource/resource/task/studentFinishInfo/v2': {code: 0, data: {finished: false}},
  };
  const calls = [];
  const result = await collect('xiaoya', transport(routes, calls));
  assert.equal(result.tasks.length, 1);
  assert.equal(result.tasks[0].external_id, '7:9');
  assert.equal(result.tasks[0].course, '编译原理');
  assert.equal(result.tasks[0].deadline, '2026-10-20T20:00');
  assert.deepEqual(calls.at(-1).params, {group_id: '7', node_id: '8', task_id: '9'});
});

test('xiaoya rejects missing completion data and non-array course lists', async () => {
  await assert.rejects(collect('xiaoya', async () => ({code: 0, data: {}})));
  const routes = {
    '/api/jx-iresource/group/student/groups': {code: 0, data: [{id: 7, name: '课'}]},
    '/api/jx-iresource/resource/queryCourseResources/v2': {code: 0, data: [
      {id: 8, task_id: 9, task_type: 2, name: '作业'}]},
    '/api/jx-iresource/resource/task/studentFinishInfo/v2': {code: 0, data: {}},
  };
  await assert.rejects(collect('xiaoya', transport(routes, [])));
});

test('valid empty course list succeeds, unknown platform fails', async () => {
  const result = await collect('yuketang', async () => ({errcode: 0, data: {list: []}}));
  assert.deepEqual(result.tasks, []);
  await assert.rejects(collect('unknown', async () => {}));
});

test('rain supports empty chapters and empty progress arrays used by its frontend', async () => {
  const routes = {
    '/v2/api/web/courses/list': {errcode: 0, data: {list: [
      {classroom_id: 10, name: '2026秋-1班', course: {name: '课'}}]}},
    '/v2/api/web/classrooms/10': {errcode: 0, data: {}},
    '/mooc-api/v1/lms/learn/course/chapter': {success: true, data: {}},
    '/mooc-api/v1/lms/learn/course/schedule': {success: true, data: {leaf_schedules: []}},
  };
  assert.deepEqual((await collect('yuketang', transport(routes, []))).tasks, []);
  routes['/mooc-api/v1/lms/learn/course/chapter'].data.course_chapter = [
    {section_leaf_list: [{id: 11, name: '作业', leaf_type: 6}]}];
  routes['/mooc-api/v1/lms/learn/leaf_info/10/11/'] = {success: true, data: {score_deadline: null}};
  assert.equal((await collect('yuketang', transport(routes, []))).tasks[0].completed, false);
  routes['/mooc-api/v1/lms/learn/course/schedule'].data.leaf_schedules = [100];
  await assert.rejects(collect('yuketang', transport(routes, [])));
});

test('schema errors identify endpoint and field without dumping response secrets', async () => {
  try {
    await collect('yuketang', async () => ({errcode: 0, data: {list: {token: 'secret-value'}}}));
    assert.fail('must reject malformed list');
  } catch (error) {
    assert.match(error.message, /courses\/list/);
    assert.match(error.message, /data.list/);
    assert.doesNotMatch(error.message, /secret-value/);
  }
});

test('content script uses login only for same-origin GET, returns metadata only', async () => {
  const requests = [];
  const context = vm.createContext({
    document: {cookie: 'nku-access-token=test-secret'},
    location: {origin: 'https://nankai.ai-augmented.com', hostname: 'nankai.ai-augmented.com'},
    chrome: {runtime: {onMessage: {addListener() {}}, sendMessage: async () => {}}},
    DDLReaders: {collect}, URL, URLSearchParams, AbortSignal,
    fetch: async (url, options) => {
      requests.push({url: String(url), options});
      return {ok: true, headers: new Headers({'content-type': 'application/json'}),
        json: async () => ({code: 0, data: []})};
    },
  });
  vm.runInContext(fs.readFileSync('browser-helper/content.js', 'utf8'), context);
  const result = await context.readPlatform('xiaoya');
  assert.equal(requests[0].options.method, 'GET');
  assert.equal(requests[0].options.credentials, 'include');
  assert.equal(requests[0].options.headers.Authorization, 'Bearer test-secret');
  assert.equal(new URL(requests[0].url).origin, 'https://nankai.ai-augmented.com');
  assert.equal(JSON.stringify(result).includes('test-secret'), false);
  await assert.rejects(context.readPlatform('yuketang'));
});

test('rain transport uses course headers and distinguishes 400 from login expiry without leaking credentials', async () => {
  for (const status of [400, 401]) {
    let request;
    const context = vm.createContext({
      document: {cookie: 'sessionid=local-secret; csrftoken=csrf-secret; university_id=999; platform_id=3'},
      location: {origin: 'https://changjiang.yuketang.cn', hostname: 'changjiang.yuketang.cn'},
      chrome: {runtime: {onMessage: {addListener() {}}, sendMessage: async () => {}}},
      DDLReaders: {collect: async (source, get) => get('/mooc-api/v1/lms/learn/course/schedule',
        {uv_id: '2651', university_id: '2651', classroom_id: '10', platform_id: '3', sign: 'rain-sign'})},
      URL, URLSearchParams, AbortSignal,
      fetch: async (url, options) => {
        request = {url, options};
        return {ok: false, status, headers: new Headers({'content-type': 'application/json'}),
          json: async () => ({code: 123, msg: 'sign required; sessionid=local-secret; Bearer other-secret',
            access_token: 'never-read-this-secret'})};
      },
    });
    vm.runInContext(fs.readFileSync('browser-helper/content.js', 'utf8'), context);
    await assert.rejects(context.readPlatform('yuketang'), error => {
      assert.match(error.message, status === 400 ? /参数/ : /登录/);
      assert.match(error.message, /123/);
      assert.match(error.message, /sign required/);
      assert.doesNotMatch(error.message, /local-secret|csrf-secret|other-secret|never-read-this-secret/);
      if (status === 400) assert.doesNotMatch(error.message, /请确认已登录|重新登录/);
      return true;
    });
    assert.equal(request.options.headers['university-id'], '2651');
    assert.equal(request.options.headers['uv-id'], '2651');
    assert.equal(request.options.headers['classroom-id'], '10');
    assert.equal(request.options.headers['X-CSRFToken'], 'csrf-secret');
  }
});
