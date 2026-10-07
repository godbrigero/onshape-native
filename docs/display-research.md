# Display adapter research and evidence

Research date: 2026-10-07. Native methods were traced in Onshape's shipped client
bundles and exercised through the authenticated extension. Comet DevTools Network
was used for connection diagnosis; no Console code was pasted. The initial
unresponsive native request came from a disconnected Onshape editor despite a
healthy extension WebSocket. The editor was reloaded and its state re-read before
any further write. This led to separate extension/editor connection checks.

Client sources:

- `https://cad.onshape.com/js/serialize.a3cb1865c227bc4826fd.js`
- `https://cad.onshape.com/js/woolsthorpe.228719a426d7e696de38.js`
- `https://cad.onshape.com/js/webgl.6b68c9d5a74e3d657ab3.js`

Runtime module IDs remain build-dependent and fail explicitly if unavailable.
The adapter accepts typed operations only, not caller-supplied JavaScript.

## Visibility and hierarchy

`assemblyTree.pathToNodes` is a native Map. Its nodes include inherited Part
Studio connectors even when the sidebar is collapsed or filtered. Serialized
node IDs are not always feature IDs: `GBTAssemblyTreeFeature.featureId` can carry
a full derived FeatureScript path. The corresponding sidebar model's
`getOccurrence()` and `getFeatureId()` provide the command reference.

`GBTUiBatchVisibilityChange` contains `occurrenceVisibilityCalls` and
`featureOccurrenceVisibilityCalls`. The former uses
`GBTUiChangeOccurrenceVisibility {occurrences:[GBTOccurrence], hidden:bool}`;
the latter uses `GBTUiSetFeatureOccurrenceVisibility
{features:[GBTFeatureReference], visibility:1|2, handleFeatureForGroup:true}`.
Each feature reference contains `featureId` and `occurrence:{path:[...]}`.

Observed enum: `UNSET=0`, `HIDDEN=1`, `VISIBLE=2`, `UNKNOWN=3`.
Effective sidebar visibility combines the model's visibility, `isParentHidden`,
and node suppression flags. It is not a pixel-occlusion test. Counts and missing
sidebar models are checked explicitly; incomplete data is never labeled complete.

## Motion

Module 29199 (Onshape's animate-mate controller) constructs
`assembly.GBTUiAssemblyAnimateMateRequest`. A revolute query uses
`mate.featureId`, `mate.path`, `mate.queryData:"Rz"`; quantity fields carry frame
count and start/end degrees. The native response supplies `frames`, each with
`mateDofValue` in radians and `changedOccurrences`/native transform matrices.

The same `modelViewManager.batchUpdateOccurrenceTransforms` operation used by
Onshape updates the renderer, then restores the model's internal saved transform
records. Therefore `modelViewManager.getOccurrenceTransform` is **not** a valid
preview readback. Verification reads `viewer.getOccurrenceDataManager()` using
the occurrence graphics ID, with numeric tolerance 1e-6. Baseline rendered
transforms are captured before the first frame and restored on request. No
assembly-position REST write is used.

## Camera/capture

The primary view controller maps front/back/left/right/top/bottom to
`XZ/XZback/YZback/YZ/XY/XYback`, and uses its own `Isometric` frame. Fit and zoom
use `getZoomFitTargetCamera`, unioning `getOccurrenceBounds` for selection zoom.
Save/restore uses a native camera clone and verifies observed frame/extents in
live tests. Capture calls `viewer.draw()` and reads `getGlContext().canvas` in
the same JavaScript task, before WebGL drawing-buffer discard. This preserves
current markers and view-cube geometry without browser screenshot permissions.

## Live validation scope

The open drone assembly contained 172 sidebar rows, 30 inherited connectors,
seven revolute mates and 108 top-level instances. Combined `element_tree` returned
312 occurrence/sidebar rows with no completeness issues. A 25-row mixed batch
(six rotor joints and 19 inherited motor/lidar connector rows) was inverted,
read back, restored and read back again. Both checks returned verified true.

The lidar revolute mate produced five frames across 0–90 degrees. Frame 2 reported
45.00000125223908 degrees, with renderer transform verification. Start, status,
stop and restore completed; restored pose verification passed. The model revision
remained unchanged throughout motion and camera operations.

Front view/fit, zoom to the lidar-head occurrence, capture and camera restoration
were exercised. Camera frame/extents restored within 1e-10. A PNG viewport artifact
was inspected visually. These results verify the tested build and assembly;
they do not certify every mate kind, display mode or future Onshape build.

A separate real MCP session verified all 35 tool schemas, occurrence hide/restore,
camera orientation/fit and inline image content. Authenticated local HTTP calls
also returned complete display snapshots and PNG artifact metadata. The final
read matched the original visibility for all 171 addressable sidebar references;
the motion session was restored. The original camera frame was reapplied within
2e-16, with orthographic extents adjusted by Onshape to the current viewport aspect
ratio. No geometry or saved assembly pose was changed by these preview tests.

See [sanitized validation record](evidence/display-validation.json) for counts,
readback errors and source hashes. Private document IDs, pairing data and images
are excluded from that distributable record.
