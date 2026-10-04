"""Snapshot-based traversal and verified document/sidebar mutations."""
from __future__ import annotations

import asyncio
import copy
import re

from .client import OnshapeError
from .structures import (target_from_url, element_url, document_rows, feature_rows,
                         assembly_rows, assembly_sidebar_rows, page_tree, pointer_get, document_native)

# Observed serializer field IDs; see docs/structure-research.md. These are not
# positions in an array. A wrong value can produce a successful no-op response.
GROUP_CHILDREN_FIELD = 5971970
GROUP_NAME_FIELD = 5971969
MODEL_CHILDREN_FIELD = 577538
FEATURE_FOLDER_NAME_FIELD = 13139968


class Structures:
    def __init__(self, service):
        self.s = service

    async def microversion(self, target):
        if target["wvm"] == "m": return target["wvmid"]
        result = await self.s.call("getCurrentMicroversion", {"did": target["did"], "wv": target["wvm"], "wvid": target["wvmid"]})
        micro = result.get("microversion")
        if not isinstance(micro, str) or not re.fullmatch(r"[a-f0-9]{24}", micro): raise OnshapeError("Server returned no valid document microversion.")
        return micro

    def load(self, snapshot, kind=None):
        data = self.s.store.read(snapshot)
        if data.get("kind") != "onshape-structure" or (kind and data.get("tree_kind") != kind):
            raise OnshapeError("Use a matching snapshot from document_tree or element_tree.")
        return data

    async def capture_document(self, url):
        target = target_from_url(url)
        micro = await self.microversion(target)
        content = await self.s.call("getDocumentContents", {"did": target["did"], "wvm": "m", "wvmid": micro})
        rows, issues = document_rows(content, target, micro)
        return {"kind": "onshape-structure", "tree_kind": "document", "url": url, "target": target,
                "microversion": micro, "contents": content, "rows": rows, "issues": issues, "complete": not issues}

    async def document_tree(self, url, snapshot="", parent_id="", recursive=True, offset=0, limit=20):
        data = self.load(snapshot, "document") if snapshot else await self.capture_document(url)
        if target_from_url(url) != data["target"]: raise OnshapeError("Snapshot and URL differ.")
        snapshot = snapshot or self.s.store.put(data)["artifact"]
        return page_tree(self.s.store, data, snapshot, parent_id, recursive, offset, limit)

    async def ready_state(self, target):
        if target["wvm"] != "w" or target.get("configuration") or not target.get("eid"):
            raise OnshapeError("Native sidebar editing requires an unconfigured workspace element URL.")
        native = {"did": target["did"], "wid": target["wvmid"], "eid": target["eid"]}
        opened = await self.s.client.command({"kind": "open", "target": native})
        for attempt in range(5):
            try:
                return await self.s.client.command({"kind": "state", "target": native, "tab_id": opened.get("tab_id")})
            except OnshapeError:
                if attempt == 4: raise
                await asyncio.sleep(.25 * (attempt+1))

    async def capture_element(self, url):
        target = target_from_url(url)
        if not target["eid"]: raise OnshapeError("element_tree needs an /e/EID URL.")
        document = await self.capture_document(url)
        element = next((e for e in document["contents"]["elements"] if e["id"] == target["eid"]), None)
        if element is None: raise OnshapeError("Element is absent at this revision.")
        kind = element["elementType"]
        data = {"kind": "onshape-structure", "url": url, "target": target, "microversion": document["microversion"], "element": element}
        pinned = {"did": target["did"], "wvm": "m", "wvmid": data["microversion"], "eid": target["eid"]}
        if kind == "ASSEMBLY":
            definition = await self.s.call("getAssemblyDefinition", pinned, {"configuration": target["configuration"], "includeMateFeatures": True, "includeMateConnectors": True, "includeNonSolids": True, "excludeSuppressed": False})
            rows, issues = assembly_rows(definition)
            occurrences_complete = not issues
            if target["wvm"] == "w" and not target["configuration"]:
                native = await self.ready_state(target)
                if native["microversion"] != data["microversion"]:
                    raise OnshapeError("Document changed during assembly sidebar snapshot. Refresh element_tree.")
                sidebar, sidebar_issues = assembly_sidebar_rows(native)
                data["native"] = native
            else:
                sidebar, sidebar_issues = [], ["Assembly sidebar folders require an unconfigured workspace URL; REST occurrence hierarchy is reported separately."]
            data.update(tree_kind="assembly", definition=definition, rows=rows+sidebar, issues=issues+sidebar_issues,
                        occurrences_complete=occurrences_complete, sidebar_complete=not sidebar_issues, complete=not (issues+sidebar_issues))
        elif kind == "PARTSTUDIO":
            features = await self.s.call("getPartStudioFeatures", pinned, {"configuration": target["configuration"], "noSketchGeometry": True})
            if target["wvm"] == "w" and not target["configuration"]:
                native = await self.ready_state(target)
                if native["microversion"] != data["microversion"]:
                    raise OnshapeError("Document changed during sidebar snapshot. Read element_tree again.")
                rows, issues = feature_rows(native, features)
                data.update(native=native)
            else:
                rows = [{"id": "root", "kind": "feature_root", "parent_id": None, "ancestors": [], "name": "Features"}]
                rows += [{"id": "feature:"+f["featureId"], "kind": "feature", "feature_id": f["featureId"], "name": f.get("name"),
                          "parent_id": None, "ancestors": [], "index": i, "placement": "folder_membership_unavailable"} for i, f in enumerate(features["features"])]
                issues = ["Native folder membership is unavailable for configured or immutable URLs; flat REST features are reported without guessed parents."]
            data.update(tree_kind="partstudio", features=features, rows=rows, issues=issues, complete=not issues, rollback_index=features.get("rollbackIndex"))
        else:
            data.update(tree_kind="element", rows=[{"id": "root", "kind": "element", "name": element["name"], "parent_id": None, "ancestors": []}],
                        issues=["Use discovered APIs for this element type; no invented feature hierarchy."], complete=False)
        return data

    async def element_tree(self, url, snapshot="", parent_id="", recursive=True, offset=0, limit=20):
        data = self.load(snapshot) if snapshot else await self.capture_element(url)
        if data["tree_kind"] == "document" or target_from_url(url) != data["target"]: raise OnshapeError("Snapshot and element URL differ.")
        snapshot = snapshot or self.s.store.put(data)["artifact"]
        return page_tree(self.s.store, data, snapshot, parent_id, recursive, offset, limit)

    async def history(self, url, element_id="", cursor="", limit=20):
        if not 1 <= limit <= 50: raise OnshapeError("History limit must be 1–50 scanned entries.")
        target = target_from_url(url)
        if element_id and not re.fullmatch(r"[a-f0-9]{24}", element_id): raise OnshapeError("Invalid element ID.")
        if cursor and not re.fullmatch(r"[a-f0-9]{24}", cursor): raise OnshapeError("Use next_cursor returned by document_history.")
        start = cursor or await self.microversion(target)
        raw = await self.s.call("getDocumentHistory", {"did": target["did"], "wm": "m", "wmid": start})
        if not isinstance(raw, list): raise OnshapeError("Unexpected history response; inspect the raw API schema.")
        cache = {}
        async def signature(mid):
            if not mid: return None
            if mid not in cache:
                cache[mid] = await self.s.call("getDocumentContents", {"did": target["did"], "wvm": "m", "wvmid": mid})
            content = cache[mid]
            element = next((e for e in content["elements"] if e["id"] == element_id), None)
            if element is None: return None
            rows, _ = document_rows(content, target, mid)
            row = next(r for r in rows if r.get("element_id") == element_id)
            by_id = {r["id"]: r for r in rows}
            return {"name": element["name"], "microversion": element.get("microversionId"), "element_type": element.get("elementType"),
                    "folders": [{"id": rid, "name": by_id[rid]["name"]} for rid in row["ancestors"]]}
        events = []
        scanned = raw[:limit]
        for record in scanned:
            event = dict(record)
            if element_id:
                after, before = await signature(record["microversionId"]), await signature(record.get("nextMicroversionId"))
                if before == after: continue
                event.update(element_id=element_id, before=before, after=after, attribution="compared element state and folder membership across these exact revisions")
            events.append(event)
        next_cursor = scanned[-1].get("nextMicroversionId") if scanned else None
        if next_cursor == start: raise OnshapeError("History cursor did not advance; refusing a pagination loop.")
        event_artifact = self.s.store.put(events)["artifact"]
        page = self.s.store.page(events, limit=limit)
        while page.get("needs_narrower_pointer") and limit > 1:
            limit = max(1, limit//2); page = self.s.store.page(events, limit=limit)
        return {"head_microversion": start, "events": page.get("data", []), "event_count": len(events),
                "events_artifact": event_artifact, "events_next_offset": page.get("next_offset"),
                "events_need_artifact": bool(page.get("needs_narrower_pointer")),
                "scanned": len(scanned), "next_cursor": next_cursor,
                "raw_artifact": self.s.store.put(raw)["artifact"], "element_filter": element_id or None,
                "scope": "Onshape model edit history, not browser tab visit history. Element filtering compares pinned states, never parses description/name text."}

    async def fresh(self, data):
        target = data["target"]
        if target["wvm"] != "w": raise OnshapeError("Mutation requires a workspace snapshot.")
        if not data["complete"]: raise OnshapeError("Incomplete hierarchy; resolve snapshot issues before editing structure.")
        if await self.microversion(target) != data["microversion"]: raise OnshapeError("Stale structure snapshot. Read a fresh tree before editing.")

    async def native(self, target, micro, command, body):
        state = await self.ready_state(target)
        if state.get("editingFeatureId"): raise OnshapeError("A feature edit is already open; resolve it before organizing the tree.")
        if state["microversion"] != micro: raise OnshapeError("Native revision differs from snapshot; refresh before writing.")
        return await self.s.client.command({"kind": "native", "target": {"did": target["did"], "wid": target["wvmid"], "eid": target["eid"]},
                                            "command": command, "body": body, "expected_microversion": micro})

    @staticmethod
    def selected(data, node_id):
        matches = [r for r in data["rows"] if r["id"] == node_id]
        if len(matches) != 1: raise OnshapeError("Select an exact node ID from the tree snapshot.")
        return matches[0]

    async def folder_change(self, data, edits):
        target = dict(data["target"])
        available = [e["id"] for e in data["contents"]["elements"] if e["elementType"] in ("PARTSTUDIO", "ASSEMBLY")]
        if target.get("eid") not in available: target["eid"] = available[0] if available else None
        if not target["eid"]: raise OnshapeError("A loaded Part Studio or assembly is needed as a native document-command anchor.")
        return await self.native(target, data["microversion"], "ui.document.GBTUiEditElementGroups", {
            "editDescription": "Organize document tabs and folders", "groupChanges": {"$type": "diff.GBTTreeEditList", "edits": edits}})

    async def document_edit(self, snapshot, action, node_id="", name="", element_type="partstudio", parent_id="root", before_id="", delete_contents=False):
        data = self.load(snapshot, "document")
        allowed = {"create_element", "duplicate_element", "rename", "delete_element", "create_folder", "move", "delete_folder", "unpack_folder"}
        if action not in allowed: raise OnshapeError("Unsupported document action: " + action)
        if action in {"create_element", "create_folder", "rename"} and (not name.strip() or len(name)>256): raise OnshapeError("Provide a name of 1–256 characters.")
        await self.fresh(data)
        target = data["target"]; dw = {"did": target["did"], "wid": target["wvmid"]}
        result = {}; expected = {}; completed = []; expected_structure = None
        node = self.selected(data, node_id) if node_id else None
        if action in {"create_element", "duplicate_element"}:
            parent = self.selected(data, parent_id)
            if parent["kind"] not in {"document_root", "document_folder"}: raise OnshapeError("Destination must be a document folder/root.")
            if before_id and self.selected(data, before_id)["parent_id"] != parent_id:
                raise OnshapeError("before_id must be an immediate child of the destination.")
            if name and (not name.strip() or len(name)>256): raise OnshapeError("Provide a name of 1–256 characters.")
        if action == "delete_folder" and node and node["kind"] == "document_folder" and delete_contents:
            descendants = [r for r in data["rows"] if node_id in r["ancestors"]]
            if descendants:
                # Delete tabs through the documented endpoint first. Removing a
                # folder reference alone is not proof its tabs were deleted.
                plan = [r for r in descendants if r["kind"] == "element"]
                plan += sorted([r for r in descendants if r["kind"] == "document_folder"], key=lambda r: -len(r["ancestors"]))
                plan.append(node)
                current = snapshot
                for row in plan:
                    step = "delete_element" if row["kind"] == "element" else "delete_folder"
                    try:
                        result = await self.document_edit(current, step, node_id=row["id"])
                    except OnshapeError as error:
                        return {"action": action, "verified": False, "completed": completed, "snapshot": current,
                                "error": str(error), "outcome": "Cascade stopped; inspect before continuing. Completed deletions remain."}
                    current = result.get("snapshot", current)
                    if not result["verified"]:
                        return {**result, "action": action, "completed": completed, "outcome": "Cascade stopped after an unverified step; inspect."}
                    completed.append({"action": step, "id": row["id"]})
                return {**result, "action": action, "completed": completed,
                        "expected": {"absent": node_id, "deleted_ids": [r["id"] for r in plan]}}
        if action == "create_element":
            ops = {"partstudio": "createPartStudio", "assembly": "createAssembly", "featurestudio": "createFeatureStudio", "variablestudio": "createVariableStudio"}
            if element_type not in ops or ops[element_type] not in self.s.catalog.ops: raise OnshapeError("Supported types: partstudio, assembly, featurestudio, variablestudio when cataloged.")
            result = await self.s.call(ops[element_type], dw, body={"name": name})
            expected = {"id": "element:"+result["id"], "name": name}
        elif action in {"duplicate_element", "delete_element"} or (action == "rename" and node and node["kind"] == "element"):
            if not node or node["kind"] != "element": raise OnshapeError("Select an element node.")
            eid = node["element_id"]
            if action == "duplicate_element":
                result = await self.s.call("copyElementFromSourceDocument", dw, body={"documentIdSource": dw["did"], "workspaceIdSource": dw["wid"], "elementIdSource": eid})
                expected = {"id": "element:"+result["id"]}
            elif action == "delete_element":
                result = await self.s.call("deleteElement", {**dw, "eid": eid}); expected = {"absent": node_id}
            else:
                path = {"did": dw["did"], "wvm": "w", "wvmid": dw["wid"], "eid": eid}
                meta = await self.s.call("getWMVEMetadata", path)
                fields = [p for p in meta.get("properties", []) if p.get("name") == "Name" and p.get("editable")]
                if len(fields) != 1: raise OnshapeError("Cannot uniquely resolve the writable Name property.")
                await self.fresh(data)
                result = await self.s.call("updateWVEMetadata", path, body={"properties": [{"propertyId": fields[0]["propertyId"], "value": name}]})
                expected = {"id": node_id, "name": name}
        else:
            root = copy.deepcopy(data["contents"]["folders"])
            wrapper = {"contents": {"folders": root}}
            parent = self.selected(data, parent_id)
            if parent["kind"] not in {"document_root", "document_folder"}: raise OnshapeError("Destination must be a document folder/root.")
            destination = pointer_get(wrapper, parent["raw_pointer"])
            if before_id:
                before = self.selected(data, before_id)
                if before["parent_id"] != parent_id or before_id == node_id: raise OnshapeError("before_id must be an unselected child of destination.")
            if action == "create_folder":
                # Native schema generates a fresh node identity without inventing its encoding.
                anchor = dict(target)
                anchors = [e["id"] for e in data["contents"]["elements"] if e["elementType"] in {"PARTSTUDIO", "ASSEMBLY"}]
                if anchor.get("eid") not in anchors: anchor["eid"] = anchors[0] if anchors else None
                await self.ready_state(anchor)
                schema = await self.s.client.command({"kind": "schema", "target": {"did": anchor["did"], "wid": anchor["wvmid"], "eid": anchor["eid"]}, "name": "document.GBTElementGroup"})
                fresh_id = schema["defaults"]["nodeId"]
                child = {"btType": "BTElementGroup-1458", "nodeId": fresh_id, "groupId": "", "groupName": name, "groups": []}
                expected = {"id": "folder:"+fresh_id, "name": name, "parent_id": parent_id}
            else:
                if not node or node["kind"] == "document_root" or not node.get("raw_pointer"): raise OnshapeError("Select a listed non-root node.")
                child = pointer_get(wrapper, node["raw_pointer"])
                source_parent = self.selected(data, node["parent_id"])
                siblings = pointer_get(wrapper, source_parent["raw_pointer"])["groups"]
                if action == "rename":
                    if node["kind"] != "document_folder": raise OnshapeError("Select a document folder.")
                    child["groupName"] = name; expected = {"id": node_id, "name": name}
                elif action == "move":
                    if parent_id == node_id or node_id in parent["ancestors"]: raise OnshapeError("Cannot move a folder into itself or its descendants.")
                    siblings.remove(child); expected = {"id": node_id, "parent_id": parent_id}
                elif action in {"delete_folder", "unpack_folder"}:
                    if node["kind"] != "document_folder": raise OnshapeError("Select a document folder.")
                    if action == "delete_folder" and child["groups"]:
                        raise OnshapeError("Folder is nonempty. Use unpack_folder to preserve contents, or explicitly set delete_contents=true.")
                    at = siblings.index(child); siblings[at:at+1] = child["groups"] if action == "unpack_folder" else []
                    expected = {"absent": node_id}
            if action in {"create_folder", "move"}:
                dest = destination["groups"]
                anchor_node_id = self.selected(data, before_id)["node_id"] if before_id else None
                at = next((i for i, x in enumerate(dest) if x["nodeId"] == anchor_node_id), len(dest))
                dest.insert(at, child)
            ref = lambda nid: {"$type": "tree.GBTNodeReference", "nodeId": nid}
            if action in {"create_folder", "move"}:
                others = [x for x in destination["groups"] if x["nodeId"] != child["nodeId"]]
                if before_id:
                    loc = {"$type": "tree.GBTInsertionLocation", "nodeId": self.selected(data, before_id)["node_id"], "before": True, "childFieldIndex": -1}
                elif others:
                    loc = {"$type": "tree.GBTInsertionLocation", "nodeId": others[-1]["nodeId"], "before": False, "childFieldIndex": -1}
                else:
                    loc = {"$type": "tree.GBTInsertionLocation", "nodeId": parent["node_id"], "before": False, "childFieldIndex": GROUP_CHILDREN_FIELD}
                edits = [{"$type": "diff.GBTTreeEditInsertion", "location": loc, "newNode": document_native(child)}] if action == "create_folder" else [{"$type": "diff.GBTTreeEditMove", "source": ref(child["nodeId"]), "destination": loc}]
            elif action == "rename":
                edits = [{"$type": "diff.GBTTreeEditChangeField", "node": ref(node["node_id"]), "fieldIndex": GROUP_NAME_FIELD,
                          "newValue": {"$type": "tree.GBTFieldValueString", "value": name}}]
            else:
                edits = []
                if action == "unpack_folder":
                    loc = {"$type": "tree.GBTInsertionLocation", "nodeId": node["node_id"], "before": True, "childFieldIndex": -1}
                    edits += [{"$type": "diff.GBTTreeEditMove", "source": ref(c["nodeId"]), "destination": loc} for c in child["groups"]]
                edits.append({"$type": "diff.GBTTreeEditDeletion", "node": ref(node["node_id"])})
            expected_structure = document_rows({**data["contents"], "folders": root}, target, data["microversion"])[0]
            await self.fresh(data)
            result = await self.folder_change(data, edits)
        result_artifact = self.s.store.put(result)["artifact"]
        try: after = await self.capture_document(data["url"])
        except OnshapeError as error:
            return {"action": action, "verified": False, "expected": expected, "result_artifact": result_artifact,
                    "error": str(error), "outcome": "Write returned but verification failed. Read a fresh document tree before any retry."}
        after_id = self.s.store.put(after)["artifact"]
        found = next((r for r in after["rows"] if r["id"] == expected.get("id")), None)
        verified = (not any(r["id"] == expected["absent"] for r in after["rows"])) if "absent" in expected else bool(found and all(found.get(k)==v for k,v in expected.items()))
        verified &= after["complete"]
        if expected_structure is not None:
            signature = lambda rows: [(r["id"], r["parent_id"], r["name"]) for r in rows]
            verified &= signature(after["rows"]) == signature(expected_structure)
        # Copy/create, rename and placement are separate, verified steps.
        if action in {"create_element", "duplicate_element"} and verified:
            completed.append({"action": action, "id": expected["id"]})
            steps = []
            if action == "duplicate_element" and name: steps.append(("rename", {"name": name}))
            if parent_id != "root" or before_id or found["parent_id"] != parent_id:
                steps.append(("move", {"parent_id": parent_id, "before_id": before_id}))
            for step, args in steps:
                try: follow = await self.document_edit(after_id, step, expected["id"], **args)
                except OnshapeError as error:
                    return {"action": action, "completed": completed, "verified": False, "snapshot": after_id,
                            "expected": expected, "error": str(error), "outcome": "Tab exists; inspect before retrying the next step."}
                if not follow["verified"]: return {**follow, "action": action, "completed": completed}
                after_id = follow["snapshot"]
                completed.append({"action": step, "id": expected["id"]})
            if steps:
                return {**follow, "action": action, "completed": completed, "expected": {"id": expected["id"], "parent_id": parent_id, **({"name": name} if name else {})}}
        return {"action": action, "verified": verified, "expected": expected, "snapshot": after_id,
                "result_artifact": result_artifact, "microversion": after["microversion"],
                "revision_check": "preflight, not an atomic lock; inspect after uncertain outcomes"}

    async def sidebar_edit(self, snapshot, action, node_ids=None, name="", parent_id="root", before_id="",
                           parameters=None, definition=None, allow_reorder=False, delete_contents=False):
        data = self.load(snapshot)
        if data["tree_kind"] == "assembly":
            from .assembly_sidebar import edit_assembly_sidebar
            return await edit_assembly_sidebar(self, data, action, node_ids or [], name, parent_id, before_id, delete_contents, parameters, definition)
        if data["tree_kind"] != "partstudio": raise OnshapeError("Use an element_tree snapshot for sidebar edits.")
        actions = {"create_folder", "rename", "move", "delete_folder", "unpack_folder", "create_feature", "edit_feature", "delete_feature", "suppress", "unsuppress"}
        if action not in actions: raise OnshapeError("Unsupported sidebar action.")
        node_ids = node_ids or []
        if len(node_ids)>100 or len(set(node_ids)) != len(node_ids): raise OnshapeError("Select at most 100 distinct node IDs.")
        if action in {"rename", "create_folder"} and (not name.strip() or len(name)>256): raise OnshapeError("Provide a name of 1–256 characters.")
        if action not in {"move", "create_folder", "create_feature"} and len(node_ids) != 1: raise OnshapeError("This action requires exactly one node ID.")
        if action == "create_feature" and (node_ids or parent_id != "root" or before_id):
            raise OnshapeError("create_feature adds at the current rollback position. Use move afterward to place it in a folder.")
        if action == "edit_feature" and not parameters: raise OnshapeError("Provide the parameter patches to apply.")
        await self.fresh(data)
        target = data["target"]
        selected = [self.selected(data, n) for n in node_ids]
        if any(n["kind"] not in {"feature", "feature_folder"} for n in selected): raise OnshapeError("Default/reference/auxiliary nodes cannot be edited by this tool.")
        node = selected[0] if len(selected) == 1 else None
        parent = self.selected(data, parent_id)
        if parent["kind"] not in {"feature_folder", "feature_root"}: raise OnshapeError("Destination must be a feature folder or root.")
        children = data["native"]["tree"]["children"]
        existing_order = [n.get("featureId") for n in children if n.get("featureId")]
        desired_order = list(existing_order)
        result = {}; expected = {}; command = None; body = None

        def indices(row):
            return list(range(row["start_index"], row["end_index"]+1)) if row["kind"] == "feature_folder" else [row["index"]]

        def location():
            if before_id:
                before = self.selected(data, before_id)
                if before["kind"] not in {"feature", "feature_folder"} or before["parent_id"] != parent_id or before_id in node_ids:
                    raise OnshapeError("before_id must be an unselected immediate feature/folder child of the destination.")
                return {"$type": "tree.GBTInsertionLocation", "nodeId": before["node_id"], "before": True, "childFieldIndex": -1}
            if parent["kind"] == "feature_folder":
                return {"$type": "tree.GBTInsertionLocation", "nodeId": parent["end_node_id"], "before": True, "childFieldIndex": -1}
            rollback = next((n for n in children if n.get("$type") == "bsedit.GBTMRollback"), None)
            if rollback:
                return {"$type": "tree.GBTInsertionLocation", "nodeId": rollback["nodeId"], "before": True, "childFieldIndex": -1}
            if children:
                return {"$type": "tree.GBTInsertionLocation", "nodeId": children[-1]["nodeId"], "before": False, "childFieldIndex": -1}
            return {"$type": "tree.GBTInsertionLocation", "nodeId": data["native"]["tree"]["nodeId"], "before": False, "childFieldIndex": MODEL_CHILDREN_FIELD}

        if action == "create_folder":
            if selected:
                if before_id or (parent_id != "root" and parent_id != selected[0]["parent_id"]):
                    raise OnshapeError("Folder creation wraps selection in place. Use move afterward for another destination.")
                flat = [i for row in selected for i in indices(row)]
                if len(flat) != len(set(flat)) or sorted(flat) != list(range(min(flat), max(flat)+1)):
                    raise OnshapeError("Folder creation needs a contiguous selection with no overlapping folders or partial folder boundaries.")
                if any(r["parent_id"] != selected[0]["parent_id"] for r in selected): raise OnshapeError("Selected nodes must share an immediate parent.")
                begin = {"$type": "tree.GBTInsertionLocation", "nodeId": children[min(flat)]["nodeId"], "before": True, "childFieldIndex": -1}
                end = {"$type": "tree.GBTInsertionLocation", "nodeId": children[max(flat)]["nodeId"], "before": False, "childFieldIndex": -1}
                expected = {"new_folder_name": name, "parent_id": selected[0]["parent_id"], "children": node_ids}
            else:
                # The current backend drops empty/null-end folder definitions
                # during regeneration. Equal explicit boundaries persist.
                begin = location(); end = dict(begin)
                expected = {"new_folder_name": name, "parent_id": parent_id, "children": []}
            command = "partstudiofolders.GBTUiCreateFolder"
            body = {"folderName": name, "begin": begin, "end": end, "editDescription": "Create feature folder"}
        elif action == "rename" and node["kind"] == "feature_folder":
            command = "ui.GBTUiRenameFeature"
            body = {"featureId": node["node_id"], "featureChange": {"$type": "diff.GBTTreeEditChangeField", "node": {"$type": "tree.GBTNodeReference", "nodeId": node["node_id"]}, "fieldIndex": FEATURE_FOLDER_NAME_FIELD, "newValue": {"$type": "tree.GBTFieldValueString", "value": name}},
                    "isDefaultFeature": False, "isAuxiliaryDataFeature": False, "editDescription": "Rename feature folder"}
            expected = {"id": node["id"], "name": name}
        elif action in {"delete_folder", "unpack_folder"}:
            if node["kind"] != "feature_folder": raise OnshapeError("Select a feature folder.")
            contained = children[node["start_index"]+1:node["end_index"]]
            if action == "delete_folder" and contained and not delete_contents: raise OnshapeError("Nonempty folder: use unpack_folder, or explicitly set delete_contents=true.")
            keep = action == "unpack_folder"
            command = "partstudiofolders.GBTUiDeleteFolder"
            body = {"folderNode": {"$type": "tree.GBTNodeReference", "nodeId": node["node_id"]}, "keepContents": keep, "editDescription": "Unpack feature folder" if keep else "Delete feature folder"}
            expected = {"absent": node["id"]}
            if not keep:
                removed = {n.get("featureId") for n in contained}; desired_order = [f for f in existing_order if f not in removed]
        elif action == "move":
            if not selected: raise OnshapeError("Select features or folders to move.")
            if any(r["id"] == parent_id or r["id"] in parent["ancestors"] for r in selected): raise OnshapeError("Cannot move a folder into itself or its descendants.")
            flat = [i for r in selected for i in indices(r)]
            if len(flat) != len(set(flat)): raise OnshapeError("Do not select a folder together with its descendants.")
            moving = [children[i] for i in sorted(flat)]
            dest = location()
            moving_ids = {c["nodeId"] for c in moving}
            if dest["nodeId"] in moving_ids:
                # End-of-root insertion needs an unselected anchor, not a node being moved.
                remaining = [c for c in children if c["nodeId"] not in moving_ids]
                if parent_id == "root" and not before_id and remaining:
                    dest = {"$type": "tree.GBTInsertionLocation", "nodeId": remaining[-1]["nodeId"], "before": False, "childFieldIndex": -1}
                else: raise OnshapeError("Destination anchor is part of the moving range; choose an unselected destination.")
            remaining = [c for c in children if c["nodeId"] not in moving_ids]
            at = next((i for i,c in enumerate(remaining) if c["nodeId"] == dest["nodeId"]), len(remaining))
            if not dest["before"]: at += 1
            reordered = remaining[:at]+moving+remaining[at:]
            desired_order = [c["featureId"] for c in reordered if c.get("featureId")]
            if desired_order != existing_order and not allow_reorder: raise OnshapeError("This move changes feature evaluation order. Set allow_reorder=true only when that is intended.")
            # A fixed 'after' anchor requires reverse dispatch to retain selected order.
            ordered = moving if dest["before"] else list(reversed(moving))
            edits = [{"$type": "diff.GBTTreeEditMove", "source": {"$type": "tree.GBTNodeReference", "nodeId": c["nodeId"]}, "destination": dest} for c in ordered]
            command = "ui.GBTUiReorderFeatures"; body = {"featureReorder": {"$type": "diff.GBTTreeEditList", "edits": edits}, "isRollback": False, "editDescription": "Move sidebar nodes"}
            expected = {"moved_ids": node_ids, "parent_id": parent_id}
        else:
            if action != "create_feature" and (not node or node["kind"] != "feature"): raise OnshapeError("Select a feature node.")
            model = await self.s.inspect(data["url"], geometry=False)
            if model["microversion"] != data["microversion"]: raise OnshapeError("Model changed before feature edit.")
            if action == "create_feature":
                if not definition: raise OnshapeError("Supply a complete definition from the live feature specification.")
                result = await self.s.feature(model["snapshot"], "add", [definition])
                expected = {"added": [r["id"] for r in result.get("completed", [])]}
            elif action == "delete_feature":
                await self.fresh(data)
                result = await self.s.call("deletePartStudioFeature", {"did": target["did"], "wid": target["wvmid"], "eid": target["eid"], "fid": node["feature_id"]})
                expected = {"absent": node["id"]}; desired_order = [f for f in existing_order if f != node["feature_id"]]
            else:
                change = {"id": node["feature_id"]}
                if action == "rename": change["name"] = name
                elif action in {"suppress", "unsuppress"}: change["suppressed"] = action == "suppress"
                elif action == "edit_feature": change["parameters"] = parameters or {}
                result = await self.s.feature(model["snapshot"], "edit", [change])
                expected = {"id": node["id"]}
                if "name" in change: expected["name"] = change["name"]
                if "suppressed" in change: expected["suppressed"] = change["suppressed"]
        if command: result = await self.native(target, data["microversion"], command, body)
        result_artifact = self.s.store.put(result)["artifact"]
        try: after = await self.capture_element(data["url"])
        except OnshapeError as error:
            return {"action": action, "structure_verified": False, "expected": expected, "result_artifact": result_artifact,
                    "error": str(error), "outcome": "Write returned but verification failed; read a fresh element tree before retrying."}
        after_id = self.s.store.put(after)["artifact"]
        rows = {r["id"]: r for r in after["rows"]}
        verified = after["complete"] and not result.get("stopped", False)
        if "absent" in expected: verified &= expected["absent"] not in rows
        elif "id" in expected: verified &= expected["id"] in rows and all(rows[expected["id"]].get(k)==v for k,v in expected.items())
        elif "moved_ids" in expected: verified &= all(rows.get(n, {}).get("parent_id")==expected["parent_id"] for n in expected["moved_ids"])
        elif "new_folder_name" in expected:
            old_ids = {r["id"] for r in data["rows"]}
            new = [r for r in after["rows"] if r["id"] not in old_ids and r["kind"] == "feature_folder" and r["name"] == name and r["parent_id"] == expected["parent_id"]]
            verified &= len(new) == 1
            if len(new)==1:
                expected["created_id"] = new[0]["id"]
                verified &= all(rows.get(n, {}).get("parent_id") == new[0]["id"] for n in expected["children"])
        elif "added" in expected: verified &= bool(expected["added"]) and all("feature:"+fid in rows for fid in expected["added"])
        if action == "edit_feature":
            feature = next((f for f in after["features"]["features"] if f["featureId"] == node["feature_id"]), {})
            actual = {p["parameterId"]: p for p in feature.get("parameters", [])}
            for pid, patch in parameters.items():
                patch = {"expression": patch} if isinstance(patch, str) else patch
                verified &= all(actual.get(pid, {}).get(k) == v for k, v in patch.items())
        if action in {"move", "create_folder", "unpack_folder", "delete_folder", "delete_feature"}:
            verified &= [r["feature_id"] for r in after["rows"] if r["kind"] == "feature"] == desired_order
        if action == "move":
            moved = [r["id"] for r in sorted(selected, key=lambda r:r.get("start_index", r.get("index", -1)))]
            siblings = [r["id"] for r in after["rows"] if r["parent_id"] == parent_id and r["kind"] in {"feature", "feature_folder"}]
            end = siblings.index(before_id) if before_id in siblings else len(siblings)
            verified &= siblings[max(0,end-len(moved)):end] == moved
        if action == "unpack_folder":
            preserved = [r for r in data["rows"] if r["parent_id"] == node["id"]]
            verified &= all(rows.get(r["id"], {}).get("parent_id") == node["parent_id"] for r in preserved)
        removed_folders = {r["id"] for r in data["rows"] if action == "delete_folder" and node and (r["id"] == node["id"] or node["id"] in r["ancestors"])}
        if action == "unpack_folder": removed_folders.add(node["id"])
        verified &= all(r["id"] in rows for r in data["rows"] if r["kind"] == "feature_folder" and r["id"] not in removed_folders)
        errors = [r for r in after["rows"] if r["kind"] == "feature" and r.get("status") not in {"OK", "SUPPRESSED"}]
        return {"action": action, "structure_verified": bool(verified), "expected": expected, "snapshot": after_id,
                "microversion": after["microversion"], "regeneration_errors": errors,
                "result_artifact": result_artifact,
                "next": "Read the returned tree snapshot; use inspect_model/evaluate to verify resulting geometry. Never replay an unverified mutation without inspecting."}
