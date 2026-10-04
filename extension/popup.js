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
