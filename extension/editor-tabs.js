// Managed browser editors. Ownership survives worker suspension, not browser restart.
// Never adopt, move, or close a user-owned tab merely because its URL matches.
const KEY = 'managedEditors';
export const editorDefaults = {editor_mode: 'shadow', close_after_work: true};

export function editorUrl(target) {
  if (!target || !['did', 'wid', 'eid'].every(k => /^[a-f0-9]{24}$/.test(target[k])))
    throw new Error('An exact workspace element is required.');
  return `https://cad.onshape.com/documents/${target.did}/w/${target.wid}/e/${target.eid}`;
}

export function matchesEditor(tab, url) {
  try {
    const actual = new URL(tab.pendingUrl || tab.url);
    return actual.origin === 'https://cad.onshape.com' && actual.pathname === new URL(url).pathname &&
      !actual.searchParams.get('configuration');
  } catch { return false; }
}

export function createEditorTabs(browser, probe, {sleep = ms => new Promise(r => setTimeout(r, ms)), now = Date.now} = {}) {
  const read = async () => (await browser.storage.session.get(KEY))[KEY] || {};
  let storageQueue = Promise.resolve();
  function change(update) {
    const task = storageQueue.then(async () => {
      const records = await read(); update(records);
      await browser.storage.session.set({[KEY]: records});
    });
    storageQueue = task.catch(() => {});
    return task;
  }
  async function forget(id) {
    await change(records => { delete records[id]; });
  }
  async function owned(tab, url) {
    const record = (await read())[tab.id];
    return record && record.url === url && record.window_id === tab.windowId && matchesEditor(tab, url) ? record : null;
  }
  async function exact(job) {
    const tab = await browser.tabs.get(job.tab_id);
    if (!matchesEditor(tab, editorUrl(job.target))) throw new Error('Tab navigated away from the exact unconfigured workspace element.');
    return tab;
  }
  async function health(tab, target) {
    if (tab.discarded) return {ready: false, stale: true, reason: 'discarded'};
    if (tab.status !== 'complete') return {ready: false, stale: false, reason: 'loading'};
    try {
      const state = await probe(tab.id, target);
      if (state?.error) return {ready: false, stale: false, reason: state.error};
      return {ready: state?.connected === true, stale: state?.connected === false,
        reason: state?.connected === true ? 'connected' : state?.connected === false ? 'disconnected' : 'connection_unknown',
        busy: !!(state?.editingFeatureId || state?.rpc_pending || state?.motion_active || state?.incomplete_edit),
        microversion: state?.microversion, element_microversion: state?.element_microversion};
    } catch {
      return {ready: false, stale: false, reason: 'Editor probe unavailable; inspect the tab or explicitly refresh it.'};
    }
  }
  async function wait(job, tab, seconds) {
    const deadline = now() + seconds * 1000;
    let state;
    do {
      tab = await exact({...job, tab_id: tab.id});
      state = await health(tab, job.target);
      if (state.ready || now() >= deadline) break;
      await sleep(Math.min(500, Math.max(0, deadline - now())));
    } while (now() < deadline);
    return {tab, state};
  }
  function result(tab, record, state, extra = {}) {
    return {tab_id: tab.id, window_id: tab.windowId, url: tab.url, managed: !!record,
      mode: record?.mode || 'existing', close_after_work: record?.close_after_work ?? false,
      ...state, ...extra,
      next: state.ready ? 'Use this exact tab_id for native tools. Verify saved work, restore previews, then call editor_tab(action="finish").' :
        'Editor is not ready. Inspect status/sign-in; refresh if stale. Never replay a write with an unknown outcome.'};
  }
  async function refresh(job, tab, state, policy) {
    if (policy === 'never' || (policy === 'if_stale' && !state.stale)) return false;
    if (state.busy) throw new Error('Finish the active feature edit, pending RPC, or motion preview before refreshing.');
    await exact({...job, tab_id: tab.id});
    await browser.tabs.reload(tab.id, {bypassCache: false});
    return true;
  }
  async function open(job) {
    const url = editorUrl(job.target);
    const settings = {...editorDefaults, ...await browser.storage.local.get(Object.keys(editorDefaults))};
    const mode = !job.mode || job.mode === 'default' ? settings.editor_mode : job.mode;
    if (!['background', 'shadow', 'minimal'].includes(mode)) throw new Error('Unknown editor mode.');
    const records = await read();
    const tabs = (await browser.tabs.query({url: 'https://cad.onshape.com/*'})).filter(t => matchesEditor(t, url));
    let tab;
    if (job.tab_id != null) tab = await exact(job);
    else if (job.reuse !== false) {
      const candidates = mode === 'background' ? tabs : tabs.filter(t => records[t.id]?.mode === mode && records[t.id]?.url === url && records[t.id]?.window_id === t.windowId);
      if (candidates.length > 1) throw new Error('Multiple matching editor tabs; provide tab_id or reuse=false.');
      tab = candidates[0];
    }
    const created = !tab;
    if (!tab) {
      if (mode === 'background') tab = await browser.tabs.create({url, active: false});
      else {
        const window = await browser.windows.create(mode === 'shadow'
          ? {url, type: 'popup', state: 'minimized', focused: false}
          : {url, type: 'popup', width: 960, height: 720, focused: false});
        tab = window.tabs?.[0];
        if (!tab) tab = (await browser.tabs.query({windowId: window.id}))[0];
        if (!tab) throw new Error('Window opened but no editor tab was returned; inspect browser windows.');
      }
      await change(current => { current[tab.id] = {url, window_id: tab.windowId, mode,
        close_after_work: job.close_after_work ?? settings.close_after_work}; });
      // Keep long-running native sessions eligible for execution in the background.
      try { await browser.tabs.update(tab.id, {autoDiscardable: false}); } catch { /* optional browser support */ }
    }
    const record = await owned(tab, url);
    if (record && job.close_after_work != null) {
      record.close_after_work = job.close_after_work;
      await change(current => { current[tab.id] = record; });
    }
    let state = await health(tab, job.target);
    const policy = job.refresh || 'never';
    // Implicit open recovery may only refresh an owned editor. Explicit refresh
    // below can address an existing user tab with an exact URL and ID.
    const refreshed = !created && record ? await refresh(job, tab, state, policy) : false;
    ({tab, state} = await wait(job, tab, job.wait_seconds ?? 0));
    return result(tab, record, state, {created, refreshed});
  }
  async function control(job) {
    let tab = await exact(job);
    const record = await owned(tab, editorUrl(job.target));
    let state = await health(tab, job.target);
    if (job.action === 'status') {
      ({tab, state} = await wait(job, tab, job.wait_seconds ?? 0));
      return result(tab, record, state);
    }
    if (job.action === 'refresh') {
      const refreshed = await refresh(job, tab, state, job.refresh || 'if_stale');
      ({tab, state} = await wait(job, tab, job.wait_seconds ?? 0));
      return result(tab, record, state, {refreshed});
    }
    if (!['finish', 'close'].includes(job.action)) throw new Error('Unknown editor tab action.');
    if (!record || (job.action === 'finish' && !record.close_after_work))
      return result(tab, record, state, {closed: false, reason: !record ? 'User-owned tabs are never closed.' : 'Keep-open preference.'});
    if (state.busy) throw new Error('Finish the active feature edit, pending RPC, or motion preview before closing.');
    if (job.action === 'finish' && !state.ready)
      return result(tab, record, state, {closed: false, reason: 'Cannot verify editor readiness; inspect saved work before explicit close.'});
    await exact(job);
    await browser.tabs.remove(tab.id); // Never remove a window that could contain other tabs.
    await forget(tab.id);
    return {tab_id: tab.id, url: record.url, managed: true, closed: true};
  }
  return {open, control, forget};
}
