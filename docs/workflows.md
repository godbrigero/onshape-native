# Backend-first modeling workflows

Start with `search_commands(task)` and the [local agent guide](agent-guide.md).
Use `browse_commands` for exhaustive manual discovery when the ten ranked matches
are insufficient. The guide documents all seven `/local/` convenience routes.

## Create and edit

1. `api_catalog(schema="createDocument")`, then `api_write` with a name and explicit
   privacy. A public-only account cannot silently turn a private request public.
2. Read `document_tree` for tabs and their document-folder ancestry. Use
   `document_edit` to create/copy/name/place a Part Studio or assembly. Preserve IDs.
3. `open_document(url)`, then `native_state(url)` until the exact editor is ready.
4. Either add a complete sketch definition through the feature API, or use the
   observed native sketch lifecycle: update rollback/edit state, add sketch,
   rectangle/circle/line commands, constraints/dimensions, then commit. Inspect
   `native_catalog` examples and current schema; use fresh node IDs throughout.
5. For solid features, `inspect_model`, `feature_template`, resolve semantic
   queries with `evaluate`, and `feature`. Extrusion includes the full live
   parameter set, not merely depth. Native begin/specify/commit editing is also
   available and was tested by changing an extrusion from 12 mm to 16 mm.
6. Inspect the resulting model and numeric invariants. Continue with fillets,
   shelling, patterns, boolean operations or other discovered feature types.

The live fixture exercised rectangle/circle geometry, a 40 mm dimension, a
symmetric extrusion, 1 mm fillets, a 0.5 mm shell and a three-part pattern at
35 mm spacing. Its second sketch dimension is unconstrained, so it is a transport
and regeneration fixture, not a finished manufacturing design.

A shell can remove the cap face used as a downstream pattern direction. The live
fixture exposed this; replacing the direction query with the stable Top plane
repaired the pattern. Validate query cardinality at the state where the feature
will regenerate, not only before earlier topology-changing features.

## Material, mass and weight

Native assignment uses `ui.GBTUiBatchPartPropertyChange` containing typed
`ui.GBTUiPartProperty` entries. The captured material includes a name/library
reference and physical properties; density is `DENS`, with units `kg/m^3`.
A custom material was tested with density 1200 and no library reference. Do not
blindly copy the example's transient part query or unrelated property defaults.

Native `ui.GBTUiMassPropCall` and official mass-property operations return mass,
volume, centroid and inertia. The first value in tolerance triplets is the
calculated value; following values are bounds. Mass is in kg and volume in m³.
Weight is a force derived from mass and chosen gravitational acceleration, not a
synonym for the material's density. Mass overrides, where needed, use the
schema-discovered metadata/mass-property operations and their documented options.
Overrides have not yet been live-tested here.

## Assemblies

The DevTools trace records insertion, fixed occurrences, origin mate connectors,
a fastened mate and its offset. Use current insertables/part identities and
occurrence paths; nested assemblies require the full path, not just a leaf ID.

- Read assemblies with `element_tree` or `getAssemblyDefinition`, including
  mates/connectors. Distinguish physical occurrence paths from sidebar folders;
  inspect the separately reported completeness of each hierarchy.
- Insert via the discovered assembly instance operation or the observed native
  `ui.assembly.GBTUiAssemblyInsertOccurrence` payload. For headless insertion,
  interactive drag behavior should be disabled after checking its current schema.
- Fix/unfix with `ui.assembly.GBTUiChangeOccurrenceFixedStatus` or documented REST
  assembly modification. Fixed status was replay-verified.
- Create/edit mate features using assembly feature definitions or observed native
  editing messages. The trace's fastened mate started with a 20 mm Z offset; headless editing
  then changed it to 25 mm, verified in the occurrence transform.
- Verify occurrence transforms, mate status and assembly mass afterward. The initial
  two-instance assembly had mass 0.00400092818 kg after shelling and density change.
  A third instance was subsequently inserted headlessly (`startDrag: false`) and
  translated 60 mm along X through REST; total mass became 0.00600139228 kg.

Onshape occurrence transforms are absolute object-to-world 4×4 matrices; translation
entries use meters. See the [official assembly guide](https://onshape-public.github.io/docs/api-adv/assemblies/).

The captured `GBTUiQueryInsertables` replay returned an Onshape support error in
this build. Use the official `getInsertables` endpoint until that native payload's
session requirements are understood; the catalog does not label it verified.

## Configurations, custom features, imports and exports

All current configuration, Feature Studio, assembly, drawing, metadata, translation,
version and other official operations are available through the REST catalog,
subject to the coverage limits. Configured Part Studio snapshots propagate the
configuration into geometry and feature calls. Native editor RPCs currently
require an unconfigured workspace URL.

Custom FeatureScript evaluation is read-only in a temporary context. Persistent
custom modeling requires a Feature Studio definition and instantiated feature,
using the corresponding REST operations. Do not report evaluated geometry as a
saved model edit.

For imports use `api_upload` with the exact multipart schema. Poll asynchronous
translation IDs with read operations; do not replay the creation request. For
exports use the documented synchronous endpoint or create a translation, poll
until complete, and download the returned result. Binary output becomes a private
local artifact. The HTTP route returns actual bytes.

See the [official translation guide](https://onshape-public.github.io/docs/api-adv/translation/)
and [FeatureScript query documentation](https://cad.onshape.com/FsDoc/library.html#qCapEntity-Id-CapType-EntityType)
for formats and semantic selections.
