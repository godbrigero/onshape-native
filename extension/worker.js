import {pageCommand} from "./page-adapter.js";
import {restGet} from "./rest-get.js";
import {tabContext} from "./tab-context.js";
import {BRIDGE_TOKEN} from "./local-config.js";

let socket = null;
let heartbeat = null;
let inFlight = false;
const BASE = "ws://127.0.0.1:8766/extension";

async function settings() { return chrome.storage.local.get(["enabled"]); }

async function resolveTab(job) {
  const tabs = await chrome.tabs.query({url: "https://cad.onshape.com/*"});
  if (job.target) {
    const {did, wid, eid} = job.target;
    const pathname = `/documents/${did}/w/${wid}/e/${eid}`;
    const matches = tabs.filter(t => new URL(t.url).pathname === pathname);
    if (matches.length === 1) return matches[0];
    const selected = matches.find(t => t.id === job.tab_id);
    if (selected) return selected;
    throw new Error(matches.length ? "Multiple matching tabs; provide tab_id from bridge_status." : "Open the exact target workspace/element in Comet.");
  }
  const selected = job.tab_id ? tabs.find(t => t.id === job.tab_id) : tabs.find(t => t.active) || tabs[0];
  if (!selected) throw new Error("Open an Onshape tab in Comet.");
  return selected;
}

async function execute(job) {
  if (job.kind === "rest" && job.method === "GET") return restGet(job);
  if (job.kind === "open") {
    const {did,wid,eid} = job.target;
    const url = `https://cad.onshape.com/documents/${did}/w/${wid}/e/${eid}`;
    const matches = await chrome.tabs.query({url: url + "*"});
    const tab = matches.find(t => new URL(t.url).pathname === new URL(url).pathname) || await chrome.tabs.create({url, active:false});
    return {tab_id:tab.id, url, status:tab.status, next:"Wait for native_state to succeed; opening a tab does not mean the editor is ready."};
  }
  if (job.kind === "tabs") {
    return tabContext(chrome);
  }
  const tab = await resolveTab(job);
  const results = await chrome.scripting.executeScript({target: {tabId: tab.id}, world: "MAIN",
    func: pageCommand, args: [job]});
  if (results.length !== 1 || results[0].result === undefined) throw new Error("Page command failed or tab navigated; inspect state before retrying.");
  return results[0].result;
}

async function connect() {
  const config = await settings();
  if (!config.enabled || !BRIDGE_TOKEN || socket?.readyState === WebSocket.OPEN || socket?.readyState === WebSocket.CONNECTING) return;
  const current = new WebSocket(BASE);
  socket = current;
  current.onopen = () => current.send(JSON.stringify({type: "hello", token: BRIDGE_TOKEN}));
  current.onmessage = async event => {
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (message.type === "ready") {
      chrome.action.setBadgeText({text: "ON"});
      clearInterval(heartbeat);
      heartbeat = setInterval(() => { if (current.readyState === WebSocket.OPEN) current.send(JSON.stringify({type: "ping"})); }, 20000);
      return;
    }
    if (message.type !== "command") return;
    let result;
    if (inFlight) result = {error: "Previous command still running; inspect state before continuing."};
    else {
      inFlight = true;
      try {
        result = await execute(message.job);
        if (JSON.stringify(result).length > 96 * 1024 * 1024 - 1024) result = {error: "Result too large; inspect state and narrow the query."};
      } catch (error) {
        // No request headers, cookies, or stack dumps in bridge errors.
        result = {error: String(error.message || "Page execution failed").slice(0, 500)};
      } finally { inFlight = false; }
    }
    if (current.readyState === WebSocket.OPEN) current.send(JSON.stringify({type: "result", id: message.id, result}));
  };
  current.onclose = () => {
    if (socket !== current) return;
    socket = null; clearInterval(heartbeat); chrome.action.setBadgeText({text: "OFF"});
  };
  current.onerror = () => current.close();
}

chrome.alarms.create("native-reconnect", {periodInMinutes: .5});
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === "native-reconnect") connect(); });
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  // Only this extension's popup can manage its connection; no page messaging.
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL("popup.html")) return;
  if (message.type === "connect") {
    if (socket) socket.close(); socket = null;
    connect().then(() => reply({ok: true})); return true;
  }
  if (message.type === "status") reply({connected: socket?.readyState === WebSocket.OPEN});
  if (message.type === "disconnect") {
    if (socket) socket.close(); socket = null; clearInterval(heartbeat); reply({ok: true});
  }
});
connect();
