'use strict';
const homes = {
  xiaoya: 'https://nankai.ai-augmented.com/app/jx-web/mycourse',
  yuketang: 'https://changjiang.yuketang.cn/v2/web/index',
};
let busy = false;
const status = text => chrome.storage.local.set({status: text});
async function readyTab(source) {
  const home = homes[source];
  if (!home) throw new Error('未知平台。');
  const tabs = await chrome.tabs.query({url: `${new URL(home).origin}/*`});
  const tab = tabs.find(item => item.status === 'complete') || tabs[0] ||
    await chrome.tabs.create({url: home, active: false});
  if (tab.status !== 'complete') await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {chrome.tabs.onUpdated.removeListener(listener); reject(new Error('请等待平台页面加载完成后重试。'));}, 30000);
    function listener(tabId, change) {
      if (tabId === tab.id && change.status === 'complete') {
        clearTimeout(timer); chrome.tabs.onUpdated.removeListener(listener); resolve();
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.get(tab.id).then(current => {
      if (current.status === 'complete') listener(tab.id, {status: 'complete'});
    });
  });
  return tab.id;
}
async function sync(source) {
  if (busy) return;
  busy = true;
  await status('正在读取课程，请稍候… 可关闭此面板。');
  try {
    const tabId = await readyTab(source);
    let result;
    try { result = await chrome.tabs.sendMessage(tabId, {type: 'collect', source}); }
    catch { throw new Error('助手尚未连接平台页，请刷新已登录的平台标签页后重试。'); }
    if (!result?.ok) throw new Error(result?.message || '读取未完成。');
    let reply;
    try { reply = await chrome.runtime.sendNativeMessage('com.ddlnotes.sync', result.payload); }
    catch { throw new Error('本地便签未连接：请在 DDL Notes → … → 连接课程作业中填写扩展 ID。'); }
    if (!reply?.ok) throw new Error(reply?.message || '便签未接收同步数据。');
    await status(`已读取 ${reply.tasks} 条作业并发送到便签；保存结果请看便签同步状态。`);
  } catch (error) {
    await status(`同步未完成：${error.message}`);
  } finally { busy = false; }
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id) return;
  if (message.type === 'progress' && sender.tab && busy) { status(message.text); return; }
  if (message.type === 'sync' && !sender.tab) {
    sync(message.source); respond({started: true});
  }
});
