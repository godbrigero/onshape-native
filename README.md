# Onshape Native — an Onshape API replacement for AI-assisted CAD

**An Onshape API replacement built for AI agents to create, edit and verify CAD
models directly in Onshape—without Onshape API keys.**

Give your agent an Onshape link and describe what you want to build or change.
Onshape Native replaces the API-key-based integration with a local MCP server
and HTTP API, using your signed-in browser session to execute Onshape REST calls
and native editor commands. It preserves familiar REST methods, paths and payload
formats while exposing editor workflows such as document and feature folders.

**[Get started with Codex](docs/codex-plugin.md)** ·
**[Local setup](#setup)** · **[Agent guide](docs/agent-guide.md)**

An agent can:

- Start from a document URL or the current Onshape tab and resolve the intended
  Part Studio or assembly.
- Discover relevant commands through local vector search and exact schema lookup.
- Create and modify editable sketches, extrusions, revolves and other features;
  inspect advanced feature parameters, materials, mass and assembly relationships.
- Traverse, create, duplicate, rename, move and delete document tabs and folders,
  and explore or edit feature/sidebar organization.
- Verify regeneration, dimensions, volume, contact and hierarchy after changes.

Use backend commands for modeling and UI actions only when an operation requires
them. The browser stays open and signed in, while commands can run in background
tabs. In Codex, the MCP launcher automatically starts or reuses the local bridge.
The extension popup stays minimal: connection status and one Connect/Disconnect
button.

Example request:

> Use Onshape Native on this URL. Create a cube with a torus on top, duplicate the
> Part Studio as a larger variant, put the original in a document folder, and
> verify the geometry and folder placement.

This workflow has been completed headlessly with editable native features.
See the [modeling skill](skills/onshape-native-modeling/SKILL.md),
[agent guide](docs/agent-guide.md) and [Codex installation](docs/codex-plugin.md).
Coverage is documented per operation and workflow in
[coverage and limits](docs/coverage.md); this is not a claim that every Onshape
operation or native command has been live-tested. Normal account permissions
and plan capabilities apply.

## Setup

Requirements: Python 3.11+, `uv`, Comet or another Chromium browser (Chrome 120+),
and an Onshape account signed in at `https://cad.onshape.com`.

From this directory:

```sh
uv sync --frozen
.venv/bin/python scripts/configure.py
.venv/bin/python scripts/install_local.py
```

1. In Comet, open `chrome://extensions`, enable Developer mode and use **Load
   unpacked** to select this directory's `extension` folder. Review its Onshape
   and loopback access. `webRequest` is used only to obtain the Location header of
   export redirects initiated by the extension; cookies are never exported.
2. The installer registers `onshape-native@personal` in Codex with the
   `onshape_native` MCP server and `onshape-native-modeling` skill. Start a new
   Codex task to load them. For another MCP client, use the generated `.mcp.json`.
   The launcher starts the local HTTP server automatically, or reuses one with
   the same token. See [Codex installation](docs/codex-plugin.md) for details.
3. In the extension popup, press **Connect**. Open the exact workspace element
   before using native editor commands; `open_document` can do this without clicks.
4. Run `bridge_status`, then `resolve_target(url="ONSHAPE_LINK")` or
   `resolve_target()` for the current Onshape tab. Use the resolved URL for the
   task; the skill handles command discovery and verification. Use `tab_id` if
   the same element is open in multiple tabs.

For HTTP without MCP, run this in a terminal:

```sh
.venv/bin/python scripts/bridge.py
```

The API listens on `http://127.0.0.1:8766`. It is unavailable when the companion
process is stopped. A normal Chromium extension cannot itself bind an HTTP server
socket; the companion is part of this package. The browser must stay running and
signed in, but commands can operate in background tabs.

Pairing material is generated in `.runtime/bridge.json` and
`extension/local-config.js`. Keep both local, exclude them from distribution, and
rerun configuration and installation after moving this directory. Keep
`ONSHAPE_NATIVE_RUNTIME` pointed at the existing pairing when moving it.
Independent runtimes must not compete for the same port; the installed plugin
and source checkout intentionally reuse the same paired companion.

## HTTP API

The REST route retains Onshape methods, paths, query parameters, JSON request and
response shapes, and HTTP status codes. Replace the Onshape origin with the local
origin; authenticate locally with `Authorization: Bearer <local bridge token>`.
The token is read from `.runtime/bridge.json`; it is never an Onshape credential.
Requests with a browser Origin header or a different Host are refused.

```text
GET    /health
GET    /api/v17/partstudios/d/{did}/w/{wid}/e/{eid}/features
POST   /api/v17/partstudios/d/{did}/w/{wid}/e/{eid}/features
POST   /api/v17/blobelements/d/{did}/w/{wid}       (multipart/form-data)
POST   /command                                  (native/editor control)
POST   /local/resolve_target                     (link or current Onshape tab)
POST   /local/search_commands                    (local vector discovery)
POST   /local/document_tree                      (tabs/folders)
POST   /local/element_tree                       (features/assemblies)
POST   /local/document_edit                      (verified structure edits)
```

The CLI reads the local token without printing it:

```sh
.venv/bin/python scripts/request.py GET /health
.venv/bin/python scripts/request.py POST /command --body request.json
```

Example `request.json` (replace all IDs):

```json
{
  "kind": "state",
  "target": {
    "did": "DOCUMENT_ID_24_HEX_CHARS",
    "wid": "WORKSPACE_ID_24_HEX_CHARS",
    "eid": "ELEMENT_ID_24_HEX_CHARS"
  }
}
```

A native write uses `kind: "native"`, `command`, `body`, the same `target`, and
`expected_microversion` from a fresh state. Nested native objects carry `$type`.
Use `native_catalog` for observed examples and `native_schema` for current shapes;
research document IDs in examples must be replaced with IDs from your model.

Raw HTTP uploads preserve multipart boundaries. Responses preserve JSON, binary
bytes, ETag, content disposition/range, Retry-After and rate-limit headers. Only
If-None-Match and Range are accepted as custom upstream request headers. Redirected
exports are downloaded by the companion without cookies, API keys or the bridge
token; their signed storage URLs are not exposed to callers.

## MCP tools

The 30 tools use progressive discovery and private, paginated artifacts rather
than registering hundreds of large endpoint schemas.

| Purpose | Tools |
|---|---|
| Local vector/manual discovery | `search_commands`, `browse_commands` |
| Tabs, folders, features, assemblies and history | `document_tree`, `element_tree`, `document_history` |
| Verified structure edits | `document_edit`, `sidebar_edit` |
| REST discovery and execution | `api_catalog`, `api_read`, `api_write`, `api_request`, `api_upload` |
| Exact modeling | `inspect_model`, `evaluate`, `feature_template`, `feature`, `render_views` |
| Native editor messages | `native_catalog`, `native_schema`, `native_state`, `native_read`, `native_write` |
| Connection, task target and navigation | `resolve_target`, `bridge_status`, `open_document` |
| Local artifact paging | `artifact_page` |
| Sidebar baselines | `sidebar_prepare`, `sidebar_verify` |
| Explicit UI fallback | `ui_inspect`, `ui_action` |

`feature_template` reads live parameter specifications, including extrusion end
conditions, second directions, draft, offsets, boolean scopes, pattern options
and other advanced feature settings. This avoids restricting a feature to a
handwritten subset of its parameters. Discover the desired type, resolve geometry
queries, update its defaults and call `feature(action="add")`. Editing an existing
feature preserves unspecified parameters. Arbitrary full definitions remain
available through `api_write` and `api_request`.

For other API operations, discover their exact operation ID and schema first.
Use `api_upload` for the six multipart operations (imports, blobs, attachments and
material libraries). `api_request` accepts newer or DevTools-observed `/api/`
endpoints not in the bundled catalog. `api_read` saves binary exports to a local
artifact rather than including binary data in model context.

Start with `search_commands(task)` for ten ranked matches from the complete
bundled REST/native/tool inventory. Search uses offline TF-IDF vectors, cosine
similarity and CAD aliases; it needs no model download, remote service or API
key. `browse_commands` provides exhaustive filtered pagination when ranking misses.

Use `document_tree` for tabs and document folders, `element_tree` for Part Studio
feature folders and assembly occurrence/sidebar trees, and `document_history`
for revision history with exact element filtering. `document_edit` and
`sidebar_edit` accept fresh tree snapshots, preserve stable identities and verify
the resulting hierarchy. Document-folder and Part Studio folder operations have
live validation. New assembly-sidebar helpers require the updated extension's
Map reader and still await live validation after reload. Occurrence traversal
uses the separately verified REST definition. See the full
[agent guide](docs/agent-guide.md) for arguments, JSON formats and HTTP examples.

The eight target/discovery/tree/edit helpers also accept the same JSON arguments at `POST /local/<name>`.
They retain the existing bearer authentication. These convenience routes are
separate from the upstream-compatible `/api/` paths. The inherited
`sidebar_prepare`/`sidebar_verify` helpers remain optional baseline utilities.
UI actions require fresh control
handles, a revision and an explanation of why backend commands cannot do the
job. Supported actions are click, double-click, context-menu, fill and select.
Synthetic events are not guaranteed to be accepted by every Onshape control.

## Modeling and verification

Read [agent instructions](docs/agent-guide.md), [workflow recipes](docs/workflows.md),
[structure protocol evidence](docs/structure-research.md), and [coverage](docs/coverage.md).

- Resolve a model snapshot and fresh geometry IDs before an edit. Queries describe
  selection intent; transient entity IDs are tied to a microversion/configuration.
- Prefer REST/native commands. Extrusions, materials and mates do not need dialog
  clicks. Sketch interaction uses native commands or complete sketch definitions.
- Native commands use a revision preflight, which is **not atomic** against other
  collaborators. REST feature writes use server-enforced revision checks.
- Multi-command editor sessions and feature batches are not atomic transactions.
  Keep begin/edit/commit sequences together; inspect if interrupted. Requests are
  never automatically retried after an ambiguous mutation outcome.
- A server acknowledgement is not geometric success. Check regeneration and exact
  dimensions, volume, mass or assembly occurrence transforms after editing.
- An `observed` payload is not a reusable universal template. Optional native
  fields sometimes require explicit `null`; constructor defaults can be invalid.
- Normal Onshape permissions, account capabilities and service limits still apply.
  Native commands are build-dependent; incompatible runtime shapes fail with a
  diagnostic rather than replaying recorded bytes.

## Checks

```sh
uv sync --frozen --group dev
.venv/bin/python -m pytest tests -q
node --test tests/adapter.test.mjs
.venv/bin/python scripts/smoke.py
.venv/bin/python scripts/smoke.py --url 'https://cad.onshape.com/documents/DID/w/WID/e/EID'
```

The smoke script performs a real stdio MCP handshake and optional read-only
geometry verification. It never creates or edits documents. Live writes used a
separately approved public research document; no test suite silently publishes a
new document.

## Icon assets

The extension, Codex plugin and skill share an original cube-and-ring icon.
Its editable source is [assets/onshape-native.svg](assets/onshape-native.svg).
`scripts/build_icons.py` regenerates the bundled PNG sizes with `rsvg-convert`
(librsvg); the renderer is not needed to run or install the integration.
