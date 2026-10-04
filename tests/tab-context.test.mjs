import test from 'node:test';
import assert from 'node:assert/strict';
import {tabContext} from '../extension/tab-context.js';

test('reports host-scoped tabs and last-focused normal window without selecting a tab', async () => {
  const browser = {
    tabs: {query: async filter => {
      assert.deepEqual(filter, {url: 'https://cad.onshape.com/*'});
      return [{id: 1, windowId: 10, active: true, title: 'Background window', url: 'https://cad.onshape.com/documents/one'},
              {id: 2, windowId: 20, active: true, title: 'Current', url: 'https://cad.onshape.com/documents/two'}];
    }},
    windows: {getLastFocused: async filter => {
      assert.deepEqual(filter, {windowTypes: ['normal']}); return {id: 20, focused: false};
    }},
  };
  const result = await tabContext(browser);
  assert.equal(result.last_focused_window_id, 20);
  assert.equal(result.tabs[1].window_id, 20);
  assert.equal(result.tabs[0].active, true);
  assert.equal(result.browser_window_focused, false); // Codex can have app focus.
});

test('window closing race returns unknown context, never an invented current tab', async () => {
  const result = await tabContext({tabs: {query: async () => [{id: 1}]},
    windows: {getLastFocused: async () => {throw new Error('Window closed');}}});
  assert.equal(result.last_focused_window_id, null);
});
