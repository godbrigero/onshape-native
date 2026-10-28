# Managed editor tabs

Onshape Native can open an editor from its exact workspace-element URL even
when no document tab is open. The browser must still be running, connected to
the bridge, and signed into Onshape. No API keys or headless browser are used.

The extension popup sets the default view and whether to close managed editors
when the agent finishes. These preferences apply to subsequent opens.

| Mode | Behavior |
|---|---|
| `shadow` | Minimized, unfocused popup window outside the main tab strip (default). |
| `minimal` | Unfocused 960 × 720 popup with minimal browser chrome. |
| `background` | Inactive tab in a normal browser window; can reuse a user tab. |

Shadow windows are real browser windows and remain visible to the operating
system. Chromium may throttle background rendering/timers. Motion playback and
viewport capture may need a visible editor; use minimal mode when appropriate.
The supported browser APIs are [windows.create](https://developer.chrome.com/docs/extensions/reference/api/windows#method-create)
and [tabs](https://developer.chrome.com/docs/extensions/reference/api/tabs).

## Open, use, finish

```python
opened = open_document(url=URL, mode="shadow", close_after_work=True)
# Keep opened.tab_id. Wait for ready=true; then inspect native_state.
# Perform edits with the exact URL/tab_id and verify persisted results.
editor_tab(url=URL, tab_id=TAB_ID, action="finish")
```

`finish` honors the saved close preference. `close_after_work=False` keeps the
editor open; `editor_tab(action="close")` explicitly closes a managed editor
later. Cleanup happens when the agent calls finish after verification, not on
an idle timeout, disconnect, or after each individual command. It does not
prove that a model change saved; verify that separately. Active feature edits,
known pending display RPCs, incomplete edits, and motion previews block cleanup.

Shadow/minimal modes reuse only a managed editor in the same mode. An explicit
`tab_id` selects an existing exact editor; `reuse=False` creates a separate one.
Multiple matching candidates require an ID. Existing tabs are never adopted or
moved, and neither close nor finish closes user-owned tabs. Navigation to a
different element/configuration prevents cleanup. Moving a managed tab to
another window also relinquishes cleanup ownership. Only the tab is removed,
never other tabs added to its window.

Ownership is in `chrome.storage.session`, surviving service-worker restarts
but deliberately not browser restarts or extension reloads. After a restart,
restored tabs are treated as user-owned. `bridge_status` lists managed tabs,
modes, discarded status, and close preferences for recovery after a lost response.

## Readiness and stale recovery

`open_document` and `editor_tab` accept `wait_seconds` from 0 to 30 (default 15).
They return connection readiness separately from creation/reload success. Login
redirects, loading errors, and unsupported frontend builds do not count as ready.

```python
editor_tab(url=URL, tab_id=TAB_ID, action="status", wait_seconds=15)
editor_tab(url=URL, tab_id=TAB_ID, action="refresh")  # only if discarded/disconnected
editor_tab(url=URL, tab_id=TAB_ID, action="refresh", refresh="always")
```

`if_stale` uses observed discard/disconnection, not tab age or a generic command
error. An unsupported frontend/probe failure does not trigger repeated reloads.
`always` explicitly reloads an exact tab for other confirmed stale/loading
failures. An explicit refresh can address a user-owned tab; implicit recovery
through `open_document(refresh="if_stale")` only refreshes managed editors.
A healthy editor is not reloaded under `if_stale`. Each call reloads at most once.

No refresh replays a native or REST write. After an uncertain write, inspect
persisted state before recovery. Refresh loses transient UI state and invalidates
editor snapshots, camera handles, and previews; reacquire fresh state/revisions.

## Update and HTTP access

Reload the unpacked Onshape Native extension after updating and restart the MCP
client/server to load the new tool schemas. `bridge_status` must advertise
`editor_tabs_v1` (extension 0.4.1). Older workers reject lifecycle requests rather
than silently ignoring their options. Existing simple raw `kind="open"` requests
remain accepted; the updated worker applies popup defaults without a readiness wait.

The same typed helpers are available at authenticated
`POST /local/open_document` and `POST /local/editor_tab`. Low-level bridge jobs
use `kind="open"` or `kind="editor_tab"` with exact `target: {did,wid,eid}`.
No new browser permissions are needed.
