'use strict';
document.getElementById('extension-id').textContent = chrome.runtime.id;
document.getElementById('helper-version').textContent = chrome.runtime.getManifest().version;
const show = text => {document.getElementById('status').textContent = text || '尚未同步';};
chrome.storage.local.get('status').then(value => show(value.status));
chrome.storage.onChanged.addListener(changes => {if (changes.status) show(changes.status.newValue);});
for (const button of document.querySelectorAll('button')) button.addEventListener('click', () => {
  chrome.runtime.sendMessage({type: 'sync', source: button.dataset.source});
});
