import test from 'node:test';
import assert from 'node:assert/strict';
import {createEditorTabs, editorUrl, matchesEditor} from '../extension/editor-tabs.js';

const target = {did: 'a'.repeat(24), wid: 'b'.repeat(24), eid: 'c'.repeat(24)};
const url = editorUrl(target);
function fixture() {
  let next = 1, time = 0;
  const tabs = new Map(), session = {}, settings = {}, events = [];
  let state = {connected: true};
  const browser = {
    storage: {
      session: {get: async () => structuredClone(session), set: async data => Object.assign(session, structuredClone(data))},
      local: {get: async () => settings},
    },
    tabs: {
      query: async filter => [...tabs.values()].filter(t => filter.windowId == null || t.windowId === filter.windowId),
      get: async id => {if (!tabs.has(id)) throw new Error('No tab'); return {...tabs.get(id)};},
      create: async options => {
        events.push(['create', options]);
        const tab = {id: next++, windowId: 1, status: 'complete', ...options}; tabs.set(tab.id, tab); return {...tab};
      },
      update: async (id, options) => {events.push(['update', id, options]); Object.assign(tabs.get(id), options);},
      reload: async (id, options) => {events.push(['reload', id, options]); tabs.get(id).discarded = false; state = {connected: true};},
      remove: async id => {events.push(['remove', id]); tabs.delete(id);},
    },
    windows: {create: async options => {
      events.push(['window', options]);
      const tab = {id: next++, windowId: next + 100, status: 'complete', url: options.url};
      tabs.set(tab.id, tab); return {id: tab.windowId, tabs: [{...tab}]};
    }},
  };
  const probe = async () => {events.push(['probe']); return state;};
  const manager = () => createEditorTabs(browser, probe, {now: () => time, sleep: async ms => {time += ms;}});
  return {tabs, session, settings, events, manager, setState: value => {state = value;}};
}
const open = (f, args = {}) => f.manager().open({target, ...args});
const control = (f, id, args = {}) => f.manager().control({target, tab_id: id, action: 'status', ...args});

test('default shadow creates minimized unfocused popup and disables automatic discard', async () => {
  const f = fixture(), result = await open(f);
  assert.equal(result.mode, 'shadow'); assert.equal(result.ready, true); assert.equal(result.created, true);
  assert.deepEqual(f.events[0], ['window', {url, type: 'popup', state: 'minimized', focused: false}]);
  assert.equal(f.tabs.get(result.tab_id).autoDiscardable, false);
});
test('minimal is compact and unfocused; background tab is inactive', async () => {
  const f = fixture(); await open(f, {mode: 'minimal'});
  assert.deepEqual(f.events[0][1], {url, type: 'popup', width: 960, height: 720, focused: false});
  const g = fixture(); await open(g, {mode: 'background'});
  assert.deepEqual(g.events[0], ['create', {url, active: false}]);
});
test('popup preferences apply, with per-call override and explicit reuse=false', async () => {
  const f = fixture(); f.settings.editor_mode = 'minimal'; f.settings.close_after_work = false;
  const first = await open(f); assert.equal(first.mode, 'minimal'); assert.equal(first.close_after_work, false);
  const second = await open(f, {mode: 'shadow', close_after_work: true});
  assert.equal(second.mode, 'shadow'); assert.equal(second.close_after_work, true);
  const third = await open(f, {mode: 'shadow', reuse: false}); assert.notEqual(third.tab_id, second.tab_id);
});
test('shadow does not adopt, move, or close a matching user tab', async () => {
  const f = fixture(); f.tabs.set(55, {id: 55, windowId: 1, url, status: 'complete'});
  const result = await open(f); assert.notEqual(result.tab_id, 55);
  assert.equal((await control(f, 55, {action: 'close'})).closed, false);
  assert(f.tabs.has(55));
});
test('background reuses unique user tab but cannot acquire ownership', async () => {
  const f = fixture(); f.tabs.set(55, {id: 55, windowId: 1, url, status: 'complete'});
  const result = await open(f, {mode: 'background', close_after_work: true});
  assert.equal(result.tab_id, 55); assert.equal(result.managed, false); assert.equal(result.close_after_work, false);
  assert.equal((await control(f, 55, {action: 'finish'})).closed, false);
});
test('ownership and close policy survive worker recreation; finish closes only that tab', async () => {
  const f = fixture(), result = await open(f);
  f.tabs.set(77, {id: 77, windowId: result.window_id, url: 'https://example.com'});
  assert.equal((await control(f, result.tab_id, {action: 'finish'})).closed, true);
  assert(f.tabs.has(77)); assert.deepEqual(f.session.managedEditors, {});
});
test('keep-open finish preserves tab, explicit close removes it', async () => {
  const f = fixture(), result = await open(f, {close_after_work: false});
  assert.equal((await control(f, result.tab_id, {action: 'finish'})).closed, false);
  assert.equal((await control(f, result.tab_id, {action: 'close'})).closed, true);
});
test('URL mismatch, configuration, pending navigation, and moved window prevent cleanup', async () => {
  for (const change of [{url: 'https://example.com'}, {url: url + '?configuration=x'}, {pendingUrl: 'https://example.com'}]) {
    const f = fixture(), result = await open(f); Object.assign(f.tabs.get(result.tab_id), change);
    await assert.rejects(control(f, result.tab_id, {action: 'close'}), /navigated/);
    assert(f.tabs.has(result.tab_id));
  }
  const f = fixture(), result = await open(f); f.tabs.get(result.tab_id).windowId = 999;
  assert.equal((await control(f, result.tab_id, {action: 'close'})).closed, false);
});
test('matching is exact, with no configured or foreign-origin matches', () => {
  assert(matchesEditor({url: url + '?foo=bar'}, url));
  for (const value of [url + '/other', url + '?configuration=Length%3D1', url.replace('cad.onshape.com', 'evil.example')])
    assert(!matchesEditor({url: value}, url));
});
test('ambiguous matching managed editors require ID; explicit ID disambiguates', async () => {
  const f = fixture(), a = await open(f), b = await open(f, {reuse: false});
  await assert.rejects(open(f), /Multiple/);
  assert.equal((await open(f, {tab_id: b.tab_id})).tab_id, b.tab_id);
  assert.notEqual(a.tab_id, b.tab_id);
});
test('if_stale never reloads healthy or merely loading editors', async () => {
  const f = fixture(), r = await open(f);
  assert.equal((await control(f, r.tab_id, {action: 'refresh'})).refreshed, false);
  f.tabs.get(r.tab_id).status = 'loading';
  const result = await control(f, r.tab_id, {action: 'refresh', wait_seconds: 2});
  assert.equal(result.ready, false); assert.equal(result.refreshed, false);
  assert(!f.events.some(e => e[0] === 'reload'));
});
test('stale recovery reloads disconnected/discarded editor once without sending writes', async () => {
  for (const discarded of [false, true]) {
    const f = fixture(), r = await open(f); f.setState({connected: false});
    f.tabs.get(r.tab_id).discarded = discarded;
    const result = await control(f, r.tab_id, {action: 'refresh'});
    assert.equal(result.refreshed, true); assert.equal(result.ready, true);
    assert.equal(f.events.filter(e => e[0] === 'reload').length, 1);
  }
});
test('open recovery is managed-only; explicit refresh can address a user tab', async () => {
  const f = fixture(); f.tabs.set(55, {id: 55, windowId: 1, url, status: 'complete'}); f.setState({connected: false});
  const r = await open(f, {mode: 'background', refresh: 'always'}); assert.equal(r.refreshed, false);
  assert.equal((await control(f, 55, {action: 'refresh'})).refreshed, true);
  const managed = await open(f); f.setState({connected: false});
  assert.equal((await open(f, {tab_id: managed.tab_id, refresh: 'if_stale'})).refreshed, true);
});
test('probe errors are not stale evidence; always permits explicit recovery', async () => {
  const f = fixture(), r = await open(f); f.setState({error: 'Unsupported frontend'});
  assert.equal((await control(f, r.tab_id, {action: 'refresh'})).refreshed, false);
  assert.equal((await control(f, r.tab_id, {action: 'finish'})).closed, false);
  assert.equal((await control(f, r.tab_id, {action: 'refresh', refresh: 'always'})).refreshed, true);
});
test('feature edits, pending RPCs, previews and incomplete edits block reload/close', async () => {
  for (const flag of ['editingFeatureId', 'rpc_pending', 'motion_active', 'incomplete_edit']) {
    const f = fixture(), r = await open(f); f.setState({connected: false, [flag]: true});
    await assert.rejects(control(f, r.tab_id, {action: 'refresh', refresh: 'always'}), /Finish/);
    await assert.rejects(control(f, r.tab_id, {action: 'close'}), /Finish/);
    assert(!f.events.some(e => ['reload', 'remove'].includes(e[0])));
  }
});
test('new browser session loses ownership and cannot close restored user tab', async () => {
  const f = fixture(), r = await open(f); delete f.session.managedEditors;
  assert.equal((await control(f, r.tab_id, {action: 'close'})).closed, false);
});
