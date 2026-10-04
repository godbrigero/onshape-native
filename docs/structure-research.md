# Structure protocol evidence, 2026-10-03

The document-tab folder workflow was inspected through Comet's Network panel.
Typed native examples from the existing workflow capture were combined with
read-only inspection of the publicly served frontend serializer and controllers:

- `https://cad.onshape.com/js/serialize.a3cb1865c227bc4826fd.js`
- `https://cad.onshape.com/js/woolsthorpe.228719a426d7e696de38.js`
- Client build: `1.221.89963.13d10d36cb23`.

These sources are evidence about this build, not a stable vendor contract. Large
vendor bundles and private runtime artifacts are not distributed with this code.
The extension resolves constructors in the current runtime and rejects unknown
fields/types. Verified helpers also inspect resulting persisted structure.
The [validation record](evidence/structure-validation.json) includes source
hashes, checked mutation results, protocol/HTTP checks and measured geometry deltas.

## Document tabs

`getDocumentContents` at a pinned microversion returns `elements` plus `folders`,
a `BTElementGroup-1458` tree containing `BTDocumentElementReference-2484` leaves.
Generated BOM tabs can appear in elements but be absent from this hierarchy.

The native write is `ui.document.GBTUiEditElementGroups`, with a
`diff.GBTTreeEditList` in `groupChanges`. Supported primitives are insertion,
deletion, move and field change. Do not replace the entire root: a whole-root
rewrite failed live. Insertion uses a fresh constructor-generated node ID.

| Serialized field | Exact value |
|---|---:|
| `document.GBTElementGroup.groups` | 5971970 |
| `document.GBTElementGroup.groupName` | 5971969 |
| Relative insertion before/after a node | `childFieldIndex: -1` |

Passing a positional array index in place of the encoded field ID can acknowledge
a no-op. The document editor therefore verifies the entire ordered hierarchy
after a folder operation. Cascade deletion explicitly deletes descendant tabs
through REST before deleting the emptied folders; it reports partial completion.

Live verified: empty/nested folder creation; tab and folder naming; move into an
empty folder; same-document Part Studio and assembly copy with metadata rename;
assembly, Feature Studio and Variable Studio creation; unpack preserving tabs;
recursive deletion of a test subtree. Original sample elements were preserved.

## Part Studio sidebar

The native model stores feature folders as paired `bsedit.GBTMFolder` delimiters
in a flat `children` sequence. Match `folderId` and `isStartFolder`; do not infer
membership from names or assume the REST features endpoint contains folders.
Cross-check feature inventory/order against the pinned REST feature list.

- Create: `partstudiofolders.GBTUiCreateFolder`, explicit begin/end insertion
  locations. Equal begin/end locations create an empty folder in this build.
  The null-end form did not persist the expected hierarchy in live validation;
  it is not used by the helper.
- Move: `ui.GBTUiReorderFeatures` with `diff.GBTTreeEditMove` entries; move both
  folder delimiters and all contents. Preserve feature evaluation order unless
  the caller explicitly opts into reordering.
- Rename: `ui.GBTUiRenameFeature` with `GBTTreeEditChangeField`, name field
  **13139968** and a `GBTFieldValueString`.
- Unpack/delete: `partstudiofolders.GBTUiDeleteFolder`, `keepContents` true/false.
- Model children field, when needed: **577538**.

Live verified on a disposable copy: selected-feature and empty/nested folders,
rename, feature move into/out of nested folders, unpack, empty-folder deletion,
feature add/delete, deletion of a populated folder, rename,
suppression/unsuppression, and pattern count edits 3→4→3. A
before/after organization check retained three solids, all bounds and topology
counts; volumes agreed within 1e-8 mm³.

## Assembly sidebar

REST assembly definitions provide physical occurrence paths, referenced
subassemblies, mate features and transforms, but not the organizational sidebar.
The processed native sidebar uses a JavaScript `Map` in
`assemblyTree.pathToNodes`; enumerating its object properties loses every entry.
The updated extension serializes maps as `{"$map":[[key,value],...]}` and reports
`assemblyTreeValid`. Missing maps/children are explicit incompleteness.

The frontend source identifies `GBTUiCreateAssemblyFolder`, instance restructure,
mate reorder, shared `GBTUiRenameFeature`, `GBTUiFeatureSuppressionStatus`,
`GBTUiDeleteFeature` and `GBTUiDeleteFolder` workflows. Instance-folder name field
is **14856192**; assembly-feature folder name uses the base feature name field
**548866**. Restructure options are AFTER=0, BEFORE=1, INTO=2. Only local instance
and mate categories are accepted by the helper; referenced subassemblies require
editing their own document/element.

Assembly sidebar map handling and command verification have automated tests.
Live validation of these new assembly sidebar helpers is pending permission to
reload the extension; the loaded version omits Map entries. Existing physical
assembly occurrence traversal is live-verified through REST.
