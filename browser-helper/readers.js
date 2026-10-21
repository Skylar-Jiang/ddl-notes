/* Read-only platform adapters. No credentials are included in returned metadata. */
(() => {
  'use strict';
  function requireValue(condition, message = '平台返回格式已变化，请暂停同步并反馈。') {
    if (!condition) throw new Error(message);
  }
  function shape(value) {
    if (value === null) return 'null';
    if (Array.isArray(value)) return `array(${value.length})`;
    if (typeof value === 'object') return `object{${Object.keys(value)
      .filter(key => /^[A-Za-z_][A-Za-z0-9_]{0,40}$/.test(key)).slice(0, 12).join(',')}}`;
    return typeof value;
  }
  function id(value, field = 'id') {
    requireValue((typeof value === 'string' || typeof value === 'number') && /^[\w-]+$/.test(String(value)),
      `${field} 无效，实际 ${shape(value)}。`);
    requireValue(typeof value !== 'number' || (Number.isSafeInteger(value) && value > 0),
      '平台 ID 超出精确范围，停止读取以避免导入错误课程。');
    return String(value);
  }
  function title(value, field = 'name') {
    requireValue(typeof value === 'string' && !!value.trim(), `${field} 缺失或无效，实际 ${shape(value)}。`);
    return value.trim().replace(/[\x00-\x1f]/g, ' ');
  }
  function array(value, field) {
    requireValue(Array.isArray(value), `${field} 应为列表，实际 ${shape(value)}。`);
    return value;
  }
  function data(response) {
    requireValue(response && typeof response === 'object');
    requireValue(response.success !== false && !response.errcode &&
      (response.code === undefined || [0, 200, '0', '200'].includes(response.code)),
    '平台未授权或读取失败，请先在当前浏览器登录。');
    requireValue(response.data !== undefined);
    return response.data;
  }
  function deadline(value, field = '截止时间') {
    if (value === null || value === undefined || value === '' || value === 0 || value === '0') return null;
    let date;
    if (typeof value === 'number' || (typeof value === 'string' && /^\d{10,13}$/.test(value))) {
      const numeric = Number(value);
      requireValue(Number.isFinite(numeric) && numeric > 0, '平台截止时间无法识别。');
      date = new Date(numeric < 1e12 ? numeric * 1000 : numeric);
    } else {
      const match = typeof value === 'string' && value.match(
        /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?(Z|[+-]\d{2}:?\d{2})?$/i);
      requireValue(match, `${field} 无法识别，实际 ${shape(value)}，未猜测日期。`);
      const [year, month, day, hour, minute] = match.slice(1, 6).map(Number);
      const second = Number(match[6] || 0), zone = match[8];
      const wall = Date.UTC(year, month - 1, day, hour, minute, second);
      const check = new Date(wall);
      requireValue(check.getUTCFullYear() === year && check.getUTCMonth() === month - 1 &&
        check.getUTCDate() === day && hour < 24 && minute < 60 && second < 60, `${field} 日期无效。`);
      let offset = 480;
      if (zone?.toUpperCase() === 'Z') offset = 0;
      else if (zone) {
        const digits = zone.slice(1).replace(':', '');
        const hours = Number(digits.slice(0, 2)), minutes = Number(digits.slice(2));
        requireValue(hours < 24 && minutes < 60, `${field} 时区无效。`);
        offset = (hours * 60 + minutes) * (zone[0] === '-' ? -1 : 1);
      }
      date = new Date(wall - offset * 60000);
    }
    requireValue(Number.isFinite(date.getTime()), '平台日期无效。');
    // Both platforms use China time. Emit explicit China wall-clock minutes.
    return new Date(date.getTime() + 8 * 3600000).toISOString().slice(0, 16);
  }
  async function rain(get, progress) {
    const listed = array(data(await get('/v2/api/web/courses/list', {identity: 2})).list, 'data.list');
    const courses = listed.filter(course => /^2026年?秋/.test(
      title(course.name, 'course.name（班级学期标签）').replace(/\s+/g, '')));
    const excludedClassroomIds = [...new Set(listed.filter(course =>
      /^(?!2026年?秋)\d{4}年?[春夏秋冬]/.test(course.name.replace(/\s+/g, '')))
      .map(course => id(course.classroom_id, 'course.classroom_id')))];
    progress(`雨课堂 · 仅2026年秋：匹配 ${courses.length}/${listed.length} 门课程`);
    const tasks = [];
    for (const [index, course] of courses.entries()) {
      const cid = id(course.classroom_id, 'course.classroom_id');
      const name = title(course.course?.name || course.name, 'course.name');
      progress(`雨课堂2026秋 ${index + 1}/${courses.length} · ${name}`);
      const context = {classroom_id: cid, platform_id: '3'};
      const applyContext = info => {
        const university = info.uv_id || info.university_id;
        if (university) context.uv_id = context.university_id = id(university, 'classroom.university_id');
        const platform = info.platform || info.platform_id;
        if (platform) context.platform_id = id(platform, 'classroom.platform_id');
      };
      applyContext(course.course || {});
      const classroom = data(await get(`/v2/api/web/classrooms/${cid}`, {...context, role: 5}));
      applyContext(classroom);
      if (classroom.course_sign) context.sign = id(classroom.course_sign, 'classroom.course_sign');
      const params = {cid, ...context};
      const tree = data(await get('/mooc-api/v1/lms/learn/course/chapter', params));
      const leaves = [];
      for (const chapter of array(tree.course_chapter ?? [], 'data.course_chapter')) {
        for (const section of array(chapter.section_leaf_list || [], 'chapter.section_leaf_list')) {
          leaves.push(...(section.leaf_list === undefined ? [section] : array(section.leaf_list, 'section.leaf_list')));
        }
      }
      const assignments = leaves.filter(leaf => !leaf.is_locked && [5, 6].includes(Number(leaf.leaf_type)));
      if (!assignments.length) continue;
      const schedules = data(await get('/mooc-api/v1/lms/learn/course/schedule', params)).leaf_schedules;
      requireValue(schedules && typeof schedules === 'object' &&
        (!Array.isArray(schedules) || schedules.length === 0),
      `data.leaf_schedules 应为进度映射或空列表，实际 ${shape(schedules)}。`);
      for (const leaf of assignments) {
        const lid = id(leaf.id);
        const info = data(await get(`/mooc-api/v1/lms/learn/leaf_info/${cid}/${lid}/`, context));
        requireValue(Object.hasOwn(info, 'score_deadline'), 'data.score_deadline 字段缺失。');
        tasks.push({external_id: `${cid}:${lid}`, title: title(leaf.name), course: name,
          deadline: deadline(info.score_deadline, 'data.score_deadline'), completed: Number(schedules[lid] || 0) >= 100,
          url: `https://changjiang.yuketang.cn/v2/web/studentLog/${cid}?${new URLSearchParams({
            classroom_id: cid, ...(context.university_id ? {university_id: context.university_id} : {}),
            platform_id: context.platform_id, tab: 'content'})}`});
      }
    }
    return {tasks, excluded_classroom_ids: excludedClassroomIds};
  }
  async function xiaoya(get, progress) {
    const groups = array(data(await get('/api/jx-iresource/group/student/groups', {time_flag: 1})), 'data.groups');
    const tasks = [];
    for (const [index, group] of groups.entries()) {
      const gid = id(group.id || group.group_id), name = title(group.name || group.group_name);
      progress(`小雅 ${index + 1}/${groups.length} · ${name}`);
      const resources = array(data(await get('/api/jx-iresource/resource/queryCourseResources/v2', {group_id: gid})), 'data.resources');
      const pending = [...resources];
      while (pending.length) {
        const resource = pending.shift();
        if (resource.children !== undefined) pending.push(...array(resource.children, 'resource.children'));
        if (!resource.task_id || ![2, 3, 4].includes(Number(resource.task_type))) continue;
        const tid = id(resource.task_id), nid = id(resource.id);
        const status = data(await get('/api/jx-iresource/resource/task/studentFinishInfo/v2',
          {group_id: gid, node_id: nid, task_id: tid}));
        requireValue(typeof status.finished === 'boolean', `data.finished 应为布尔值，实际 ${shape(status.finished)}。`);
        tasks.push({external_id: `${gid}:${tid}`, title: title(resource.name), course: name,
          deadline: deadline(resource.end_time, 'resource.end_time'), completed: status.finished,
          url: 'https://nankai.ai-augmented.com/app/jx-web/mycourse'});
      }
    }
    return {tasks};
  }
  async function collect(source, get, progress = () => {}) {
    requireValue(['xiaoya', 'yuketang'].includes(source), '未知平台。');
    let endpoint = '';
    let stage = '';
    const trackedGet = async (path, params) => {
      endpoint = path.replace(/\/\d+(?=\/|$)/g, '/:id');
      return get(path, params);
    };
    let collected;
    try {
      collected = await (source === 'xiaoya' ? xiaoya : rain)(trackedGet, text => {
        stage = text;
        progress(text);
      });
    } catch (error) {
      throw new Error(`${error.message} [${source}${stage ? `，${stage}` : ''}，最后读取 ${endpoint}]`);
    }
    requireValue(collected.tasks.length <= 10000, '任务过多，请分批处理。');
    return {version: 1, source, ...collected};
  }
  const api = {collect, deadline};
  if (typeof module !== 'undefined') module.exports = api;
  else globalThis.DDLReaders = api;
})();
