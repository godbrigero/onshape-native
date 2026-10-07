# Compact responses and on-demand details

Onshape Native keeps its existing 35 MCP tools. **`artifact_page` is the single tool for expanding any saved response.** It reads local data and never repeats a CAD action.

Common tools now default to `detail="summary"`. The complete original result is saved before projection. A response returns an `artifact` or `snapshot` handle, plus pointers to omitted details. `detail="full"` opts into full fields on the original call; large results remain paginated.

## Agent workflow

1. Use the summary's IDs, status, revision and completeness information.
2. When more detail is needed, call `artifact_page` with the returned handle. Use `pointer=""` to explore the original report, or a supplied pointer to retrieve a specific section.
3. Follow `next_offset` for remaining entries. If `needs_narrower_pointer` is true, fetch the listed child pointers; those children may themselves be paginated.
4. To verify current CAD state after an edit, make a fresh read. An artifact is an immutable historical result, not a live view.

Example MCP arguments (replace placeholders with actual returned values):

```json
{"artifact":"<returned artifact>","pointer":"/feature","offset":0,"limit":20}
```

This expands a feature-write acknowledgement into the original definition, including parameters and queries. **Never repeat a write just to obtain its full response.**

The same tool retrieves every other detail:

| Summary | Handle | Useful pointer |
|---|---|---|
| Successful feature write | `artifact` | `/feature` |
| Operation schema | `artifact` | `/description`, `/responses` |
| Search/browse commands | `artifact` | `""` (entire report) |
| Document/element hierarchy | `snapshot` | Returned row `detail_pointer` |
| Display state | `snapshot` | `/camera`, `/rows` |
| Camera acknowledgement | `artifact` | `/camera` |
| General API read | `artifact` | Returned child pointer or `""` |

The authenticated local HTTP equivalent is `POST /local/artifact_page`, with the same JSON arguments and existing bridge Bearer authentication. No extra retrieval routes/tools are required.

## What changes by default

- Successful feature writes retain feature ID/type/name and response-level status/revision/skew fields, while deferring echoed feature parameters. Non-OK or skewed results use normal detailed paging.
- Operation schemas defer response schemas and top-level operation prose (`description_pointer`). Read that prose when deciding operation-specific behavior, especially before writes. Request parameter descriptions, required flags, units, constraints and references remain in the initial paged schema.
- Search/browse responses defer repeated manual instructions, index metadata and matching-term bookkeeping and REST method/path metadata (available in the operation schema). Invocation routes and evidence remain visible.
- Hierarchy summaries encode rows as a table: `columns` lists field names once and each `data` row contains the corresponding values. Zip them together to read IDs, parents, names, kinds, ordering and visibility/status fields. Null cells mean absent or null in the summary; false, zero and empty strings retain their values. `detail="full"` returns object rows. Full original rows remain in the snapshot. `query` filters names case-insensitively; `node_id` selects an exact row or element ID. Reuse `snapshot` to filter locally.
- Display summaries defer camera matrices and ancillary row data. Camera-changing operations retain their acknowledgement and restoration ID; camera reads still return camera data.
- Default root API reads fit an exact prefix into a 2,500-character data budget. Explicit pointers, `detail="full"`, and `artifact_page` retain the 7,000-character budget, with continuation offsets. Oversized values expose child pointers. Binary export behavior is unchanged.

These are character/field reductions, **not a hard token limit**. Metadata adds overhead; very small results may not get smaller. All original values remain accessible while their cache artifacts exist. All CAD operations and existing safeguards remain available.

## Why these defaults

The [frequency audit](token-audit/usage/README.md) measured 665 Native calls in two supplied threads. `api_write`, `api_catalog` and `api_read` accounted for 59.3% of recorded response tokens. The defaults target repeated payloads in these workflows rather than removing rarely used capabilities. The audit's earlier projected savings are estimates, not measured savings for this implementation; expansion calls add cost when agents need full details.

## Table example

```json
{"snapshot":"<handle>","format":"table","columns":["id","name","parent_id","detail_pointer"],"data":[["feature:f1","Extrude","root","/rows/3"]],"total":1,"next_offset":null}
```

`artifact_page(artifact="<handle>", pointer="/rows/3")` returns the complete original object row. No extra MCP tool is needed.
