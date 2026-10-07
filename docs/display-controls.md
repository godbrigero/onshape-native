# Assembly display, motion and viewport controls

Requires extension **0.4.0**, companion/MCP **0.4.0**, and an open, connected
Onshape workspace editor. No API keys, Console code, button automation, debugger
permission or screen-sharing permission is needed for these operations.

`bridge_status` must show `extension.version: "0.4.0"` (or newer) and capability
`display_v1`. Extension connectivity and Onshape editor connectivity differ:
`display_state.connected` must be true for a fresh live model. A disconnected
editor can still return its cached display tree/image; it cannot accept writes.
Reconnect/reload that exact saved editor, then read again. Do not blindly replay
a command that timed out.

## Inspect the whole assembly sidebar

Resolve the supplied URL/current tab, retain its exact `tab_id`, then:

```json
{"url":"ASSEMBLY_URL","tab_id":123,"limit":10}
```

Call `display_state` with those arguments. It returns `snapshot`, `microversion`,
`tab_id`, `connected`, `complete`, `issues`, `camera`, `motion`, `rpc_pending`,
and paginated `data`. Reuse `snapshot` and `next_offset` for local pagination;
omit the snapshot for fresh verification. `element_tree` also exposes these
references and visibility on its assembly sidebar rows, plus `display_snapshot`
and `visibility_complete`. Its REST occurrence hierarchy remains separate.

Each hideable row has an exact `reference`, a name, sidebar path, native type,
raw visibility enum, inherited-connector flag, parent hiding/suppression and
`effective_visible`. Non-hideable rows report `null` and a reason. Effective
visibility comes from Onshape's sidebar model and ancestor suppression/hiding;
it does not mean a marker occupies visible pixels. Camera occlusion, isolation,
section cuts and temporary edit highlights can affect the image separately.

**Copy references verbatim.** Inherited connector feature IDs can contain dots,
slashes, `*derived` and long FeatureScript paths. They are not occurrence paths.
Do not split a feature ID or infer it from the display name. Multiple instances
of the same Part Studio can share a feature ID but have different occurrence paths.

## Batch visibility

Call `set_visibility` against the fresh display snapshot:

```json
{
  "snapshot":"DISPLAY_SNAPSHOT.json",
  "changes":[
    {"reference":{"kind":"feature","occurrence_path":[],"feature_id":"MATE_ID"},"visible":true},
    {"reference":{"kind":"feature","occurrence_path":["INSTANCE_ID"],"feature_id":"FULL_CONNECTOR_FEATURE_ID"},"visible":false},
    {"reference":{"kind":"occurrence","occurrence_path":["SUBASSEMBLY_ID","PART_INSTANCE_ID"]},"visible":true}
  ]
}
```

Select the six motor mate rows and relevant inherited connector rows from the
snapshot and put all changes in one call (up to 100). The adapter sends one native
batch, grouping show/hide and occurrence/feature changes internally. Onshape's
feature visibility enum is `UNSET=0`, `HIDDEN=1`, `VISIBLE=2`; agents use booleans.
The wrapper preserves the nested `GBTFeatureReference` / `GBTOccurrence` types.

The response includes `verified`, a new snapshot and paginated `checks` artifact.
Each check contains the requested value and observed effective visibility. A
shown connector under a hidden/suppressed parent can legitimately return
`verified:false`. Inspect the parent rather than repeatedly sending “show”.
Capture the current viewport if the question is whether a marker is actually
visible on screen. Restore any active motion preview before visibility writes.

Both geometry revision and observed display values are compared before sending.
This is a preflight, not an atomic lock. `rpc_pending` identifies an RPC whose
outcome is still unknown after a timeout; writes are blocked until it settles or
the saved editor is reloaded. No automatic write replay occurs.

## Revolute mate preview

Read `display_state`, select an unsuppressed `mate_type: "REVOLUTE"` row, then
call `mate_animation`:

```json
{"url":"ASSEMBLY_URL","tab_id":123,"action":"prepare","expected_microversion":"CURRENT_MICROVERSION","mate":{"kind":"feature","occurrence_path":[],"feature_id":"MATE_ID"},"start_degrees":0,"end_degrees":90,"frames":5}
```

Keep the returned `session_id` and exact tab ID. The solver produces five frames
including both endpoints; no frames are applied by `prepare`.

```json
{"url":"ASSEMBLY_URL","tab_id":123,"action":"step","session_id":"SESSION_ID","frame":2}
```

`step` is zero-based. It returns the solver's `mateDofValue` in radians and degrees
and verifies that the renderer's transforms match the frame. The saved assembly
pose is unchanged. Before any step, or after restoration, the angle is `null`;
this tool does not invent a baseline angle. If rendered transforms no longer
match, angle is also `null` and `pose_verified` is false.

Other actions, using the same URL/tab/session:

- `start`, with `fps` from 1–60: plays forward once from the next frame.
- `status`: reads frame, solved angle, playback state and current transform verification.
- `stop`: stops playback at the current preview pose.
- `restore`: stops and restores the original rendered occurrence transforms;
  require `state: "restored"` and `pose_verified: true` before finishing.

Always restore in cleanup, including after failures. `display_state.motion`
recovers the session ID if a caller lost the prepare response. One session is
allowed per editor. Navigation/reload discards it; a geometry revision change or
disconnection invalidates it. Reload the element's current saved pose instead of
writing stale baseline transforms over newer work. Background browsers may
throttle playback; explicit stepping remains deterministic. Currently this
wrapper supports revolute mates, not every possible mate DOF.

## Camera and viewport

`view_control` supports `read`, `save`, `restore`, `standard`, `orientation`,
`fit`, and `zoom`. Except `read`, supply a fresh `expected_microversion`.
`save` returns `camera_id`; `restore` uses it in the same exact tab and restores
orientation, position and zoom. Saving again replaces the previous handle.

```json
{"url":"ELEMENT_URL","tab_id":123,"action":"standard","view":"isometric","fit":true,"expected_microversion":"CURRENT_MICROVERSION"}
```

Standard views: `front`, `back`, `left`, `right`, `top`, `bottom`, `isometric`.
`fit` fits the complete displayed model. `zoom` takes `occurrence_paths`, an array
of complete physical assembly paths. It unions their actual viewer bounds.
`orientation` takes `frame`: 16 finite numbers, column-major, with right/up/back
axes in columns 0–2 and camera eye in meters in column 3. Axes must be orthonormal
and right handed. This is a camera frame, not the returned `view_matrix`.
`fit:false` preserves scale when applying orientation. For orthographic cameras,
optional `extents` accepts the six-number extents returned by camera readback
with `action:"orientation", fit:false`, to reapply a saved scale after reload.
Onshape adjusts those extents to the current viewport aspect ratio. These camera operations
work in both Part Studios and assemblies.

Call `capture_viewport`:

```json
{"url":"ELEMENT_URL","tab_id":123,"max_size":1600}
```

It returns PNG artifact metadata and an inline MCP image, including camera,
revision, capture time, dimensions, exact tab and editor connectivity. It reads
the actual WebGL viewport immediately after rendering, including model markers
and the nearest solid CSS background. HTML sidebar/dialog overlays and CSS
background images are excluded. It does not switch tabs or request screen sharing.
`max_size` is 256–4096; images are never upscaled. Blank/invalid image readback
fails without producing an artifact. `render_views` remains a separate tool for
server-generated geometry images.

## Equivalent authenticated local HTTP

All five tools are also `POST /local/TOOL_NAME` with identical JSON arguments:
`display_state`, `set_visibility`, `mate_animation`, `view_control`,
`capture_viewport`. Load the existing bearer token from the configured private
runtime; never paste it into instructions or logs. Example (shell uses the
existing `$ONSHAPE_NATIVE_TOKEN` environment variable):

```sh
curl --fail-with-body http://127.0.0.1:8766/local/display_state \
  -H "Authorization: Bearer $ONSHAPE_NATIVE_TOKEN" \
  -H 'Content-Type: application/json' --data-binary @display-request.json
```

HTTP viewport capture returns the local PNG artifact/path metadata; MCP also
includes image content. Direct `/command` has a typed `kind:"display"` contract,
exact `{did,wid,eid}` target, exact `tab_id`, `operation` and `args`, but the
high-level `/local` routes handle snapshots and artifact storage for agents.

See [installation](installation.md) to update both client packages and reload the
extension, and [research evidence](display-research.md) for native formats and
live-validation scope.
