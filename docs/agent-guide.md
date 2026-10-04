# Local agent guide: discovery, traversal and editing

Use the `onshape_native` MCP server or its authenticated loopback HTTP API. The
companion runs on `http://127.0.0.1:8766`; the browser stays signed into Onshape.
Ordinary commands work in background tabs. The popup only connects/disconnects.

## Start and connect

From `onshape-native`, run `.venv/bin/python scripts/bridge.py` for HTTP, or register
the generated `.mcp.json` and let `scripts/serve.py` launch/reuse the companion.
See the package README for first installation. Check `bridge_status` or
`GET /health`; CAD calls require `extension_connected: true`. Discovery is offline
and works with the extension disconnected. Reload the extension after extension
code changes; restart the companion after Python route changes.

The [Codex plugin installer](codex-plugin.md) registers the MCP and modeling skill
and reuses this checkout's existing pairing. Use its own environment and
configuration, not `onshape-api`.

## Resolve a link or current window

Start with `resolve_target {"url":"USER_URL"}`, or `resolve_target {}` when the
user refers to the current model. An optional integer `tab_id` explicitly selects
a browser tab. If supplied together, URL and tab must identify the same context.
The HTTP equivalent is `POST /local/resolve_target` with the same JSON object.

`status: "resolved"` returns `url`, `target` (`did`, `wvm`, `wvmid`, `eid`,
`configuration`), optional `tab_id`, `workspace_url`, and
`native_editor_eligible`. The latter flags describe URL shape, not permissions.
Keep this target fixed for the task. A document-only link still needs element
selection through `document_tree`; use that tree to determine the element type.

Current means the active Onshape tab in the connected browser's last-focused
normal window, even while Codex itself has app focus. Multiple windows can each
have an active tab; the first one returned is not necessarily current. A
non-Onshape active tab, non-document Onshape page, old extension without window
metadata, or ambiguous selection returns `needs_selection`. Ask for a URL/tab;
never silently use a background model. Disconnection returns `unavailable`.
Explicit URL-only resolution is local and preserves configurations and `w/v/m`.
CAD reads/writes still require the extension. The browser metadata uses Chrome's
[last-focused window](https://developer.chrome.com/docs/extensions/reference/api/windows#method-getLastFocused)
and host-scoped tab access without adding the global tabs permission.

## Find the right command

Call this MCP tool with the actual task, not just an endpoint guess:

```json
{"task":"duplicate this Part Studio and put the original in a new document folder"}
```

Tool: `search_commands`. Optional arguments: `limit` (1–10, default 10),
`source` (`all`, `tool`, `rest`, `native`), `read_only` (boolean or null).
It returns up to ten positive-similarity matches, their scores, evidence and
`invoke` instructions. No matching terms means no matches; it does not pad the
list with unrelated commands. The engine is local sparse TF-IDF/cosine with CAD
aliases, not a downloaded neural embedding model. It indexes all bundled REST
operations, native candidates, and registered MCP tools in memory. No CAD content
or task text leaves the machine for search. Restart after catalog updates.

Examples: “round these edges”, “change cube height”, “how much does this part
weigh”, “create a new assembly tab”, “move a feature into a sidebar folder”. Use
`read_only: true` for measurement/inspection to exclude mutation candidates.
Scores measure text similarity; `replay_verified` measures separate live evidence.
A catalog candidate can require editor state or be a helper message, even if it
is discoverable. `available` is not certification of every payload/account.

When a match is wrong or missing, use the exhaustive procedure:

1. `browse_commands(query="folder", source="tool")`; then try `source="rest"`
   and `source="native"`. Words are case-insensitive literal AND filters, without
   vector scoring. Try broader terms such as `element`, `group`, `mate`, `mass`.
2. Follow `next_offset` with identical filters. An empty query enumerates every
   entry. Optional filters are `read_only` and HTTP `method`; `limit` is 1–100.
3. For REST, call `api_catalog(schema="EXACT_OPERATION")`, then fetch named `$ref`
   components with the same tool. Follow the actual path keys, query parameters,
   request body type, and response format. Use `api_read`, `api_write`, or
   `api_upload` as indicated. `api_request` accepts observed newer `/api/` paths.
4. For feature modeling, inspect the actual model and use `feature_template` to
   obtain live feature types, parameters and defaults. Patch existing definitions
   instead of replacing them with incomplete examples.
5. For native messages, use `native_catalog(search="EXACT_COMMAND")`,
   `native_schema(url=URL, name="EXACT_COMMAND")`, then fresh `native_state`.
   Nested native values use `$type`; REST definitions use `btType`. Replace all
   captured identities with current model identities. A constructor is not an RPC
   recipe or proof of successful execution.
6. If the command remains unknown, perform the actual action in Comet while
   inspecting DevTools **Network**, including relevant WebSocket messages. Record
   method/path/body/response or typed message and prerequisites. Do not paste
   Console tracing code or bypass browser warnings. Redact credentials. A research
   action that already completed must not be replayed as another mutation.
7. Use `ui_inspect`/`ui_action` only when no backend operation can perform the task.
   Use fresh control handles and explain why the backend is insufficient. Verify
   the resulting server state. See README for supported synthetic UI actions.

## Traverse without confusing hierarchies

The input `url` is the user-provided Onshape document/workspace or element URL:
`https://cad.onshape.com/documents/DID/w/WID/e/EID`. IDs are actual returned
identifiers. A document-only URL is allowed for `document_tree` and history.
Versions (`v`) and microversions (`m`) support reads; writes require `w`.

| Tool | What it traverses |
|---|---|
| `document_tree` | Tabs of every returned element type and nested document tab folders |
| `element_tree` on a Part Studio | Ordered features, paired feature-folder boundaries, default and auxiliary nodes, suppression and regeneration status |
| `element_tree` on an assembly | Complete REST occurrence paths and mate features, plus native instance/mate sidebar folders when the updated extension is loaded |
| `document_history` | Persisted Onshape edit history, optionally filtered by exact element state changes |

This does not confuse document tab folders with account/dashboard folders. The
latter use separate REST folder APIs discoverable through the same search tools.
History means model edit history, not browser tab visits.

Example MCP calls (shown as tool name followed by its JSON arguments):

```text
document_tree {"url":"USER_URL","limit":10}
document_tree {"url":"USER_URL","snapshot":"RETURNED.json","parent_id":"root","recursive":false,"limit":10}
element_tree {"url":"RETURNED_ELEMENT_URL","limit":10}
document_history {"url":"USER_URL","element_id":"EXACT_EID","limit":10}
```

Tree results include `snapshot`, `microversion`, `tree_kind`, `complete`, `issues`,
`data`, `total`, and `next_offset`. `snapshot` is a private JSON artifact handle,
not an Onshape ID. Reuse it for consistent local paging with `offset`; omit it for
a fresh server read. `parent_id` selects a subtree; `recursive: false` returns
immediate children. If a page requests a narrower pointer, reduce `limit` or use
`artifact_page(artifact=snapshot, pointer="/rows/INDEX")` to inspect a single row.

Use returned IDs verbatim, never names or sibling positions:

| Identity | Meaning |
|---|---|
| `root` | Document/element hierarchy root |
| `element:EID` | A document tab, not a solid body |
| `folder:NATIVE_NODE_ID` | A document tab folder |
| `feature:FEATURE_ID` | Part Studio feature |
| `feature_folder:FOLDER_ID` | Part Studio feature folder, distinct from its start/end node IDs |
| `occurrence:["INSTANCE", "CHILD"]` | Physical assembly occurrence; repeated subassemblies need full paths |
| `assembly_sidebar` | Display hierarchy root inside the assembly tree result |
| `assembly_node:[...]` | Assembly sidebar identity excluding organizational folder ancestry |

Rows include `parent_id`, `ancestors`, order/index and type. Document element rows
carry editable/reference URLs and immutable URLs. Hidden/generated tabs absent
from the server folder tree are retained as `placement: "unlisted"` with unknown
parent, rather than assigned to root. Do not move an unlisted tab by guessing.
Assembly occurrence transforms are object-to-world, with translation in meters;
reference URLs retain the exact revision and configuration. Nested instances with
the same leaf ID remain distinct. Assembly sidebar `path` describes display
placement; it is not a substitute for a physical `occurrence_path`.

Assembly results separate `occurrences_complete` and `sidebar_complete`.
An older extension omits native Map contents and cannot provide sidebar folders:
the tool reports that explicitly. Configured/immutable views also cannot supply
native sidebar membership. Incomplete structures cannot be edited by these
convenience tools; use the returned issue and correct reader/schema.

History returns `events`, `scanned`, `next_cursor`, `events_artifact`, and optional
`events_next_offset`. Consume remaining local events with `artifact_page` before
following the next history cursor. `limit` bounds scanned entries (1–50), so an
element-filtered page can be empty while `next_cursor` is present. Filtering
compares exact before/after element microversions, names, types and folder paths;
it does not infer attribution from human-readable descriptions.

## Edit document tabs and folders

Call `document_edit` with a **fresh document_tree snapshot**. Refresh after every
write, or use the returned refreshed `snapshot`. Every other collaborator's edit
can invalidate a saved revision.

```text
document_edit {"snapshot":"FRESH.json","action":"create_element","element_type":"assembly","name":"Mechanism","parent_id":"folder:EXACT_ID"}
document_edit {"snapshot":"FRESH.json","action":"duplicate_element","node_id":"element:SOURCE_EID","name":"Cube and Torus - Variant","parent_id":"root"}
document_edit {"snapshot":"FRESH.json","action":"create_folder","name":"Cube and Torus - Original","parent_id":"root"}
document_edit {"snapshot":"FRESH.json","action":"move","node_id":"element:SOURCE_EID","parent_id":"folder:RETURNED_ID"}
document_edit {"snapshot":"FRESH.json","action":"rename","node_id":"folder:EXACT_ID","name":"Original design"}
document_edit {"snapshot":"FRESH.json","action":"unpack_folder","node_id":"folder:EXACT_ID"}
document_edit {"snapshot":"FRESH.json","action":"delete_element","node_id":"element:EXACT_EID"}
document_edit {"snapshot":"FRESH.json","action":"delete_folder","node_id":"folder:EXACT_ID","delete_contents":true}
```

`element_type` supports `partstudio`, `assembly`, `featurestudio`, `variablestudio`.
Other tab types use their discovered APIs (e.g. upload/import creates blob tabs).
Create/copy support name and parent placement; `before_id` specifies an immediate
destination sibling. Copy stays inside this document/workspace. Unpack preserves
contents. Delete requires `delete_contents: true` for a nonempty folder, deletes
its tabs and nested folders in separate checked steps, and reports `completed`
if interrupted. Duplicate names are legal; IDs disambiguate them.

Check `verified: true`. A returned acknowledgement alone is insufficient. Copy,
rename, placement and cascade deletion are separate operations, not one atomic
transaction. An `outcome`, `error`, false verification, timeout or lost response
requires a fresh read before deciding whether to continue; never blindly retry.
Native document-folder edits currently need a loadable Part Studio or assembly
in the document as a connection anchor.

## Edit the feature/sidebar hierarchy

Call `sidebar_edit` with a **fresh element_tree snapshot**, not an inspect_model
snapshot. A Part Studio folder wraps a contiguous same-parent selection, or is
created empty at `parent_id`/`before_id`. Whole folders move with their descendants.

```text
sidebar_edit {"snapshot":"FRESH.json","action":"create_folder","name":"Finishing","node_ids":["feature:FILLET_ID","feature:SHELL_ID"]}
sidebar_edit {"snapshot":"FRESH.json","action":"create_folder","name":"Details","parent_id":"feature_folder:EXACT_ID"}
sidebar_edit {"snapshot":"FRESH.json","action":"move","node_ids":["feature:EXACT_ID"],"parent_id":"feature_folder:EXACT_ID"}
sidebar_edit {"snapshot":"FRESH.json","action":"edit_feature","node_ids":["feature:EXTRUDE_ID"],"parameters":{"depth":"30 mm"}}
sidebar_edit {"snapshot":"FRESH.json","action":"suppress","node_ids":["feature:EXACT_ID"]}
sidebar_edit {"snapshot":"FRESH.json","action":"unsuppress","node_ids":["feature:EXACT_ID"]}
sidebar_edit {"snapshot":"FRESH.json","action":"unpack_folder","node_ids":["feature_folder:EXACT_ID"]}
```

Parameter IDs must come from the actual definition; `depth` above is illustrative.
Strings patch expressions; objects patch `expression`, `value`, or `queries`.
`rename` accepts `name`; `delete_feature` removes the selected feature;
`create_feature` accepts a complete `definition` from live feature discovery and
adds at the current rollback position. Move it afterward for folder placement.
`delete_folder` requires `delete_contents: true` when nonempty. Defaults/reference
nodes cannot be edited through this convenience tool. A move changing feature
evaluation order requires explicit `allow_reorder: true`; dependencies may break.

Assemblies use the same `sidebar_edit` for local instance/mate folder creation,
rename, moves, unpack/delete and suppression. Use `assembly_node:...` IDs. Folder
creation requires a selection of same-parent nodes in one category. Source part
names come from metadata; this tool does not rename source parts implicitly.
Referenced subassemblies are read-only through their parent sidebar: open their
reference URL and choose the intended editable workspace deliberately. Add/edit
instances and mate definitions through discovered assembly REST operations.
Assembly sidebar convenience writes are source-derived and unit-tested; live
validation is pending the extension reload described in coverage.md.

Check `structure_verified` and, for Part Studios, `regeneration_errors`. Then use
`inspect_model`/`evaluate` for exact geometry or recheck assembly mate status,
transforms and mass. Organizing a tree should preserve the relevant geometry.

## Identical arguments over local HTTP

The eight target/discovery/structure conveniences are exposed as **POST** `/local/TOOL_NAME`, with the
same JSON argument object and decoded JSON result as MCP. They live outside
Onshape's `/api/` namespace. Required header:
`Authorization: Bearer <local token from .runtime/bridge.json>`.
Do not place the token in URLs, documentation, source control or tool output.

Use the existing CLI so credentials are never printed:

```sh
.venv/bin/python scripts/request.py GET /health
.venv/bin/python scripts/request.py POST /local/search_commands --body search.json
.venv/bin/python scripts/request.py POST /local/document_tree --body tree.json
.venv/bin/python scripts/request.py POST /local/document_edit --body edit.json
```

For example `search.json` contains
`{"task":"move the original Part Studio into a document folder","limit":10}`.
The allowed names are `resolve_target`, `search_commands`, `browse_commands`, `document_tree`,
`element_tree`, `document_history`, `document_edit`, and `sidebar_edit`.
Argument types are validated strictly: send JSON booleans, not strings.
Errors return HTTP 400 with `error`; unknown local tools return 404. HTTP 200 still
requires inspecting `verified`/`structure_verified` and any partial completion.

Raw REST remains `/api/v17/...` with official methods, path/query/body and response
status. Native envelopes remain `POST /command`; see README and the cube/torus
handoff for those schemas. `/local` results are Python convenience results, not
raw REST envelopes. Normal Onshape permissions and account capabilities apply.
