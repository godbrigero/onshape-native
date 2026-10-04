"""Observed assembly folder commands, guarded by complete sidebar snapshots.

Only the current assembly's local nodes are edited. A nested subassembly is a
reference: open its reference_url to edit its own definition deliberately.
"""
from .client import OnshapeError


async def edit_assembly_sidebar(a, data, action, node_ids, name, parent_id, before_id,
                                delete_contents, parameters, definition):
    supported = {"create_folder", "rename", "move", "delete_folder", "unpack_folder", "delete_feature", "suppress", "unsuppress"}
    if action not in supported or parameters or definition:
        raise OnshapeError("Assembly sidebar supports folders, rename, move, delete and suppression. Discover REST assembly feature/instance APIs for definitions and parameters.")
    if not node_ids or len(node_ids)>100 or len(set(node_ids)) != len(node_ids):
        raise OnshapeError("Select 1–100 distinct assembly sidebar node IDs. Creating an assembly folder requires a selection.")
    if action not in {"create_folder", "move", "suppress", "unsuppress"} and len(node_ids) != 1:
        raise OnshapeError("This assembly action requires exactly one selected node.")
    if action in {"create_folder", "rename"} and (not name.strip() or len(name)>256):
        raise OnshapeError("Provide a name of 1–256 characters.")
    await a.fresh(data)
    selected = [a.selected(data, n) for n in node_ids]
    if any(r.get("read_only", True) or r["kind"] not in {"assembly_folder", "assembly_instance", "assembly_sidebar_feature"} for r in selected):
        raise OnshapeError("Select local assembly sidebar nodes. Open a referenced subassembly's URL to edit its definition.")
    if any(x["id"] in y["ancestors"] for x in selected for y in selected):
        raise OnshapeError("Do not select folders with their descendants.")
    category = selected[0]["category"]
    if category not in {"instances", "mates"} or any(r["category"] != category for r in selected):
        raise OnshapeError("Select one category: instances or mates. Discover native APIs for auxiliary trees.")
    node = selected[0]
    occurrence = lambda row: {"$type":"assembly.GBTOccurrence", "path":[row["node_id"]] if row["node_id"] else []}
    feature = lambda row: {"$type":"assembly.GBTFeatureReference", "featureId":row["node_id"],
                           "occurrence":{"$type":"assembly.GBTOccurrence", "path":[]}}
    expected = {}; body = {}; command = ""
    if action == "create_folder":
        if len({r["parent_id"] for r in selected}) != 1:
            raise OnshapeError("Folder selection must share a parent. Move nodes first.")
        if before_id or (parent_id not in {"root", node["parent_id"]}):
            raise OnshapeError("Folder creation wraps selection in place; use move afterward for a different destination.")
        command = "ui.assembly.GBTUiCreateAssemblyFolder"
        body = {"includedNodeIds":[r["node_id"] for r in selected], "userDefinedName":name, "occurrencePath":""}
        expected = {"new_folder_name":name, "parent_id":node["parent_id"], "children":node_ids}
    elif action == "rename":
        if node["kind"] == "assembly_instance":
            raise OnshapeError("Instance names derive from part/tab metadata. Discover metadata APIs rather than renaming its source implicitly.")
        field = 14856192 if node["kind"] == "assembly_folder" and category == "instances" else 548866
        command = "ui.GBTUiRenameFeature"
        body = {"featureId":node["node_id"], "isDefaultFeature":False, "isAuxiliaryDataFeature":False,
                "featureChange":{"$type":"diff.GBTTreeEditChangeField", "node":{"$type":"tree.GBTNodeReference", "nodeId":node["node_id"]},
                                 "fieldIndex":field, "newValue":{"$type":"tree.GBTFieldValueString", "value":name}}}
        expected = {"id":node["id"], "name":name}
    elif action in {"delete_folder", "unpack_folder"}:
        if node["kind"] != "assembly_folder": raise OnshapeError("Select an assembly folder.")
        descendants = [r["id"] for r in data["rows"] if node["id"] in r.get("ancestors", [])]
        if action == "delete_folder" and descendants and not delete_contents:
            raise OnshapeError("Nonempty folder: use unpack_folder or explicitly set delete_contents=true.")
        command = "partstudiofolders.GBTUiDeleteFolder"
        body = {"folderNode":{"$type":"tree.GBTNodeReference", "nodeId":node["node_id"]}, "keepContents":action=="unpack_folder"}
        expected = {"absent":[node["id"]] + (descendants if action=="delete_folder" else []),
                    "preserved":descendants if action=="unpack_folder" else []}
    elif action == "move":
        if parent_id == "root":
            parent_id = "assembly_sidebar" if category == "instances" else next((r["id"] for r in data["rows"] if r.get("path") == "mateList"), "")
        parent = a.selected(data, parent_id)
        if parent["kind"] not in {"assembly_folder", "assembly_sidebar_root", "assembly_system_folder"} or parent.get("owner_occurrence_path"):
            raise OnshapeError("Destination must be a local assembly folder/root.")
        if parent["category"] != category: raise OnshapeError("Cannot mix instance and mate folders.")
        if any(r["id"] == parent_id or r["id"] in parent["ancestors"] for r in selected):
            raise OnshapeError("Cannot move a folder into its own subtree.")
        target = a.selected(data, before_id) if before_id else parent
        if before_id and (target["parent_id"] != parent_id or target["id"] in node_ids or target["category"] != category or target.get("read_only", True)):
            raise OnshapeError("before_id must be an unselected immediate child of the destination.")
        if category == "instances":
            command = "ui.assembly.GBTUiAssemblyRestructure"
            body = {"sourceOccurrences":[occurrence(r) for r in selected], "targetOccurrence":occurrence(target), "targetOption":1 if before_id else 2,
                    "reorderEditDescription":"Move assembly sidebar nodes"}
        else:
            command = "ui.assembly.GBTUiAssemblyReorderMates"
            body = {"sourceFeatures":[feature(r) for r in selected], "targetFeature":feature(target), "targetOption":1 if before_id else 2}
        expected = {"moved_ids":node_ids, "parent_id":parent_id}
    elif action in {"suppress", "unsuppress"}:
        command = "ui.GBTUiFeatureSuppressionStatus"
        body = {"nodeIds":[r["node_id"] for r in selected], "auxiliaryNodeIds":[], "suppress":action=="suppress"}
        expected = {"ids":node_ids, "suppressed":action=="suppress"}
    else:
        if node["kind"] == "assembly_folder": raise OnshapeError("Use delete_folder for folders.")
        command = "ui.GBTUiDeleteFeature"
        body = {"featureDeletion":{"$type":"diff.GBTTreeEditList", "edits":[{"$type":"diff.GBTTreeEditDeletion", "node":{"$type":"tree.GBTNodeReference", "nodeId":node["node_id"]}}]},
                "auxiliaryDeletion":{"$type":"diff.GBTTreeEditList", "edits":[]}}
        expected = {"absent":[node["id"]]}
    body["editDescription"] = "Organize assembly sidebar: " + action
    result = await a.native(data["target"], data["microversion"], command, body)
    result_artifact = a.s.store.put(result)["artifact"]
    try: after = await a.capture_element(data["url"])
    except OnshapeError as error:
        return {"action":action, "structure_verified":False, "result_artifact":result_artifact,
                "error":str(error), "outcome":"Write returned; refresh element_tree before any retry."}
    rows = {r["id"]:r for r in after["rows"]}; verified = after["complete"]
    if "new_folder_name" in expected:
        old = {r["id"] for r in data["rows"]}
        created = [r for r in after["rows"] if r["kind"]=="assembly_folder" and r["id"] not in old and r["name"]==name and r["parent_id"]==expected["parent_id"]]
        verified &= len(created)==1
        if len(created)==1:
            expected["created_id"]=created[0]["id"]
            verified &= all(rows.get(n, {}).get("parent_id")==created[0]["id"] for n in node_ids)
    elif "id" in expected: verified &= all(rows.get(expected["id"], {}).get(k)==v for k,v in expected.items())
    elif "absent" in expected: verified &= all(n not in rows for n in expected["absent"]) and all(n in rows for n in expected.get("preserved", []))
    elif "moved_ids" in expected: verified &= all(rows.get(n, {}).get("parent_id")==parent_id for n in node_ids)
    elif "ids" in expected: verified &= all(rows.get(n, {}).get("suppressed")==expected["suppressed"] for n in node_ids)
    if action == "move" and before_id and verified:
        siblings = [r["id"] for r in after["rows"] if r["parent_id"]==parent_id]
        at = siblings.index(before_id); verified &= siblings[max(0,at-len(node_ids)):at]==node_ids
    # Organization must not add/remove physical occurrences. Folder paths are a
    # separate display hierarchy and never substitute for occurrence identities.
    if action in {"create_folder", "rename", "move", "unpack_folder"}:
        signature = lambda d: [(r["id"],r.get("transform")) for r in d["rows"] if r["kind"]=="occurrence"]
        verified &= sorted(signature(data)) == sorted(signature(after))
    return {"action":action, "structure_verified":bool(verified), "expected":expected,
            "snapshot":a.s.store.put(after)["artifact"], "microversion":after["microversion"], "result_artifact":result_artifact,
            "next":"Inspect the returned hierarchy, mate status and occurrence transforms. Never replay an unverified write."}
