# Coverage and current limits

This is an implemented bridge with live modeling validation, not a certified
replacement for every Onshape feature. An endpoint being routable does not prove
that every payload, file size, account capability or editor workflow works.

## Official REST surface

The schema retrieved from Onshape on **2026-10-03**, version
`1.221.89963-13d10d36cb23`, describes **302 operations across 248 paths**.
All 302 are discoverable/resolvable. **301 pass the native REST route validator**;
the `session` login operation is browser-owned and deliberately refused. Account
and session-information reads remain schema-discoverable.

`api_read`, `api_write` and `api_upload` cover the methods and JSON/multipart
transports in that schema. `api_request` and the raw local `/api/` route cover
observed/new API paths beyond the schema. This includes parts, assemblies,
configurations, drawings, Feature Studios, variables, materials/metadata,
translations, versions/workspaces and other published groups. Entitlements still
apply. No claim is made that paid capabilities become available on a free plan.

The six multipart operations are `uploadFileCreateElement`,
`uploadFileUpdateElement`, `uploadBlobSubelement`, `addAttachment`, `updateLibrary`
and `createTranslation`. A real STL upload/import was run; the others have route
and encoding tests, not individual live tests.

See [machine-readable operation inventory](evidence/api-coverage.json). Regenerate
it with `scripts/coverage.py`; the script never calls a write endpoint.

## Live workflow evidence

| Workflow | Evidence |
|---|---|
| Public document creation | Browser workflow and REST Network trace; public creation explicitly authorized |
| Sketch rectangle, circle and 40 mm dimension | Executed in UI; typed native requests captured |
| Symmetric extrusion | Created in UI; native begin/specify/commit changed 12 mm to 16 mm and persisted |
| Fillet | 1 mm feature created through browser-session API; regeneration and exact geometry verified |
| Shell | 0.5 mm shell created through live feature defaults; geometry verified |
| Linear pattern | Three parts at 35 mm spacing; repaired a removed-face direction reference; all features OK |
| Material and mass | Native custom density 1200 kg/m³; mass equals measured volume × density |
| Assembly creation/insertion/mates | Two instances, fixed occurrence, two mate connectors and a fastened mate captured from UI |
| Assembly headless insertion/transform | Third instance inserted through native command with drag disabled, then moved 60 mm through REST; transform verified |
| Assembly fixed status | Native command replayed and assembly definition checked |
| Assembly mate editing | Native offset changed 20 mm to 25 mm; persisted occurrence translation verified at 0.025 m |
| Assembly mass | REST mass read: 0.00600139228 kg for three hollow instances after native insertion |
| Multipart CAD import | Generated 5 mm STL cube uploaded; translation returned DONE with result element |
| UI fallback | A control-handle click opened the editor's tool search; result inspected |
| Document tab hierarchy and edits | Pinned nested traversal; create/copy/rename/move Part Studios and assemblies; create/unpack/delete folders; cascade deletion verified |
| Additional tab types | Feature Studio and Variable Studio creation, placement and deletion verified |
| Part Studio folders/features | Create selected/empty/nested folders, rename, move, unpack/delete (including contents); feature add/delete/rename, suppression and parameter edits verified; geometry preserved by organization |
| Model history | Microversion pagination and exact element-state/folder comparison verified |
| Assembly occurrence traversal | Full REST instance paths, mates and transforms verified; repeated nested references covered by tests |
| Assembly sidebar | Complete 172-row native sidebar read, including 30 inherited connectors, live-verified; folder mutation helpers remain source-derived/unit-tested |
| Display and motion | 25-row visibility batch/readback/restore; lidar revolute prepare/step/play/stop/restore; camera fit/zoom/restore and current viewport capture live-verified; see [display research](display-research.md) |
| Command discovery | Local TF-IDF/cosine top ten plus exhaustive manual catalog pagination; MCP and HTTP routes implemented |
| Native insertables discovery | Observed in UI; replay failed with backend support error; use REST getInsertables |
| Export redirects | Implemented and mock-tested; live validation awaits approval to reload with webRequest permission |
| MCP protocol and Codex plugin | Installed/enabled `onshape-native@personal` 0.2.0; real stdio initialize/list/call with 30 annotated tools; URL resolution, ranked search, document tree and live geometry inspection passed ([evidence](evidence/plugin-validation.json)) |
| Current-window targeting | Multi-window selection and fail-closed behavior tested; the currently loaded older extension requires reload for window metadata |

The fixture is intentionally small, public sample geometry, with an unconstrained
second sketch dimension. It demonstrates a multi-feature, multipart and assembly
workflow; it is not a demonstration of every advanced CAD feature.

## Native message catalog

The captured client schema contains **484 native message types/candidates**.
Merging separately observed commands produces **487 searchable native entries**.
Some are helper types or stateful requests, not independently callable RPCs.
The runtime serializer registry also supplies nested types needed by materials
and assembly references. The catalog separates `client-schema`, `observed` and
`replay_verified` evidence. Do not equate 484 entries with 484 verified commands.

Native RPCs are tied to frontend build `1.221.89963.13d10d36cb23`. They use the
running serializer and connection, not replayed WebSocket byte packets. They may
need an editor transaction, subscription or explicit null defaults. Frontend
updates can require fresh Network research and adapter changes.

## Remaining boundaries

- Native editor commands require an **unconfigured workspace** URL. Versions,
  microversions and configurations use the REST path. Native editing in those
  modes has not been implemented/verified.
- Physical assembly occurrences and organizational sidebar folders are separate
  hierarchies. Missing native sidebar maps/lazy children produce explicit
  incompleteness, never an invented folder tree. Referenced subassemblies must be
  opened in their own editable workspace for mutation. Assembly sidebar helper
  writes currently cover local instance/mate categories, not auxiliary
  simulation/generative trees. Use discovery for the underlying native/REST APIs.
- Native document-folder edits need a loadable Part Studio or assembly connection
  anchor. Document and sidebar mutations use snapshot checks and post-write
  verification; multi-step copies and recursive deletion report partial completion.
- Binary transfer is buffered and bounded at **64 MiB** (96 MiB serialized bridge
  envelope); large streaming imports/exports are not supported.
- Signed export downloads allow HTTPS Onshape/Amazon storage hosts, send no
  credentials, and reject unexpected hosts. Export changes may require updating
  this observed-host policy after validation.
- The local API preserves supported data/status/conditional and download headers,
  not every possible HTTP header. Authentication headers/cookies are browser-owned.
- Native revision preflight is non-atomic. Multistep native transactions can be
  interrupted or race other collaborators; inspect before any retry.
- UI fallback dispatches synthetic events to fresh visible controls. It has no
  trusted keyboard/mouse driver, canvas drag automation or arbitrary-code tool.
- Sheets, surfacing, complex sweeps/lofts, custom FeatureScript persistence,
  configuration editing, drawings, advanced mates, mass overrides, every export
  format and every free-plan feature have **not** been individually live-tested.
  Their official API routes are present where published; that is not a guarantee
  of complete end-to-end coverage.

The official-key package's existing transport remains independent. During this
session a modeling-service request using the account's keys returned HTTP 402;
browser workflows continued normally. That is an observed account/service
response, not evidence of bypassing account limits.
