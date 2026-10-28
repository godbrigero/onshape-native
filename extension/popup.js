import {editorDefaults} from "./editor-tabs.js";
const status = document.getElementById("status"), dot = document.getElementById("dot"), toggle = document.getElementById("toggle");
async function refresh() {
  const {enabled} = await chrome.storage.local.get("enabled");
  const {connected} = await chrome.runtime.sendMessage({type: "status"});
  status.textContent = connected ? "Connected · :8766" : enabled ? "Waiting for local API" : "Disconnected";
  dot.classList.toggle("on", connected); toggle.textContent = enabled ? "Disconnect" : "Connect";
}
toggle.onclick = async () => {
  const {enabled} = await chrome.storage.local.get("enabled");
  await chrome.storage.local.set({enabled: !enabled});
  await chrome.runtime.sendMessage({type: enabled ? "disconnect" : "connect"}); await refresh();
};
await refresh();
setInterval(refresh, 1000);

const mode = document.getElementById("editor-mode"), cleanup = document.getElementById("close-after-work");
const preferences = {...editorDefaults, ...await chrome.storage.local.get(Object.keys(editorDefaults))};
mode.value = preferences.editor_mode;
cleanup.checked = preferences.close_after_work;
mode.onchange = () => chrome.storage.local.set({editor_mode: mode.value});
cleanup.onchange = () => chrome.storage.local.set({close_after_work: cleanup.checked});
