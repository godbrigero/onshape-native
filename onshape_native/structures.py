"""Lossless identities and explicit completeness for the three Onshape trees."""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit, parse_qs, urlencode

from .client import OnshapeError


def target_from_url(url):
    u = urlsplit(url)
    if u.scheme != "https" or u.netloc != "cad.onshape.com":
        raise OnshapeError("Use a cad.onshape.com HTTPS document URL.")
    match = re.fullmatch(r"/documents/([a-f0-9]{24})/([wvm])/([a-f0-9]{24})(?:/e/([a-f0-9]{24}))?/?", u.path)
    if not match: raise OnshapeError("Use /documents/DID/w/WID, optionally /e/EID (v/m supported for reads).")
    did, mode, ref, eid = match.groups()
    return {"did": did, "wvm": mode, "wvmid": ref, "eid": eid,
            "configuration": parse_qs(u.query).get("configuration", [""])[0]}


def element_url(target, eid, microversion=None):
    mode, ref = ("m", microversion) if microversion else (target["wvm"], target["wvmid"])
    url = f"https://cad.onshape.com/documents/{target['did']}/{mode}/{ref}/e/{eid}"
    return url + ("?" + urlencode({"configuration": target["configuration"]}) if target.get("configuration") else "")


def document_rows(contents, target, microversion):
    elements = {x["id"]: x for x in contents.get("elements", [])}
    rows, issues, placed, seen = [], [], set(), set()
    root = contents.get("folders")
    if not isinstance(root, dict):
        issues.append("Document folder tree missing; no folder membership inferred.")
        root = None

    def visit(node, parent, ancestors, index, pointer, is_root=False):
        native_id = node.get("nodeId")
        if not native_id or native_id in seen:
            issues.append("Missing or duplicate folder/reference node ID at " + pointer)
            return
        seen.add(native_id)
        if "elementId" in node:
            eid = node["elementId"]
            if eid in placed: issues.append("Element appears more than once: " + eid)
            placed.add(eid)
            element = elements.get(eid, {})
            if not element: issues.append("Folder references an unavailable element: " + eid)
            rows.append({"id": "element:" + eid, "kind": "element", "element_id": eid,
                         "node_id": native_id, "name": element.get("name"), "element_type": element.get("elementType"),
                         "parent_id": parent, "ancestors": ancestors, "index": index, "placement": "listed",
                         "url": element_url(target, eid), "immutable_url": element_url(target, eid, microversion),
                         "element_microversion": element.get("microversionId"), "raw_pointer": pointer})
        elif isinstance(node.get("groups"), list):
            rid = "root" if is_root else "folder:" + native_id
            rows.append({"id": rid, "kind": "document_root" if is_root else "document_folder", "node_id": native_id,
                         "name": node.get("groupName", ""), "group_id": node.get("groupId"), "parent_id": parent,
                         "ancestors": ancestors, "index": index, "child_count": len(node["groups"]), "raw_pointer": pointer})
            if len(ancestors) > 100: raise OnshapeError("Document folder nesting exceeds 100 levels.")
            for i, child in enumerate(node["groups"]): visit(child, rid, ancestors+[rid], i, pointer+f"/groups/{i}")
        else:
            issues.append("Unknown document tree entry at " + pointer)
    if root: visit(root, None, [], 0, "/contents/folders", True)
    for eid, element in elements.items():
        if eid not in placed:
            rows.append({"id": "element:"+eid, "kind": "element", "element_id": eid,
                         "name": element.get("name"), "element_type": element.get("elementType"),
                         "parent_id": None, "ancestors": [], "placement": "unlisted",
                         "url": element_url(target, eid), "immutable_url": element_url(target, eid, microversion),
                         "element_microversion": element.get("microversionId"),
                         "note": "Returned by server but absent from folder tree; may be a generated/hidden tab. Parent is unknown."})
    return rows, issues


def feature_rows(native, features):
    """Folders are paired delimiters in a flat list, not nested child objects."""
    rows = [{"id": "root", "kind": "feature_root", "parent_id": None, "ancestors": [], "name": "Features"}]
    stack, issues, seen = [], [], set()
    root = native.get("tree", {})
    children = root.get("children", [])
    states = features.get("featureStates", {})
    folders = {}
    for i, node in enumerate(children):
        typ = node.get("$type", "")
        node_id = node.get("nodeId")
        if not node_id or node_id in seen:
            issues.append("Missing or duplicate native node ID at feature position " + str(i)); continue
        seen.add(node_id)
        parents = ["root"] + [r["id"] for r in stack]
        common = {"node_id": node_id, "parent_id": parents[-1], "ancestors": parents, "index": i,
                  "raw_pointer": f"/native/tree/children/{i}"}
        if typ == "bsedit.GBTMFolder":
            fid = node.get("folderId")
            if node.get("isStartFolder"):
                if not fid or fid in folders: issues.append("Missing or duplicate folder ID at " + str(i))
                row = {**common, "id": "feature_folder:"+str(fid), "kind": "feature_folder", "folder_id": fid,
                       "name": node.get("name"), "start_index": i, "end_index": None, "end_node_id": None}
                rows.append(row); stack.append(row); folders[fid] = row
            elif not stack or stack[-1]["folder_id"] != fid:
                issues.append("Unbalanced folder end marker at " + str(i))
            else:
                row = stack.pop(); row.update(end_index=i, end_node_id=node_id)
        elif node.get("featureId"):
            fid = node["featureId"]
            status = states.get(fid, {}).get("featureStatus")
            rows.append({**common, "id": "feature:"+fid, "kind": "feature", "feature_id": fid,
                         "name": node.get("name"), "feature_type": node.get("featureType"),
                         "suppressed": node.get("suppressed", False), "status": status})
        else:
            rows.append({**common, "id": "node:"+node_id, "kind": "auxiliary", "name": node.get("name"), "native_type": typ})
    if stack: issues.append("Unclosed feature folders: " + ", ".join(r["id"] for r in stack))
    native_ids = [r["feature_id"] for r in rows if r["kind"] == "feature"]
    rest_ids = [f["featureId"] for f in features.get("features", [])]
    if native_ids != rest_ids: issues.append("Native feature inventory/order differs from pinned REST features; cached tree may be stale.")
    defaults = root.get("defaultFeatures", {}).get("children", [])
    for i, node in enumerate(defaults):
        rows.append({"id": "default:"+node.get("featureId", str(i)), "kind": "default_feature",
                     "feature_id": node.get("featureId"), "node_id": node.get("nodeId"), "name": node.get("name"),
                     "parent_id": "root", "ancestors": ["root"], "read_only": True,
                     "raw_pointer": f"/native/tree/defaultFeatures/children/{i}"})
    return rows, issues


def assembly_rows(definition):
    """Full occurrence paths prevent collisions for reused nested subassemblies."""
    root = definition.get("rootAssembly", {})
    rows = [{"id": "root", "kind": "assembly_root", "parent_id": None, "ancestors": [], "name": "Assembly"}]
    issues = []
    def identity(x):
        return tuple(x.get(k) for k in ("documentId", "elementId")) + (x.get("documentMicroversion") or x.get("documentVersion"), x.get("fullConfiguration", x.get("configuration", "")))
    definitions = {identity(a): a for a in definition.get("subAssemblies", [])}
    occurrence_map = {tuple(o.get("path", [])): o for o in root.get("occurrences", [])}
    def rid(path): return "occurrence:" + json.dumps(path, separators=(",", ":"))
    def visit(assembly, path, ancestry, definition_chain):
        if len(path) > 100: raise OnshapeError("Assembly nesting exceeds 100 levels.")
        for i, inst in enumerate(assembly.get("instances", [])):
            current = path + [inst["id"]]; current_id = rid(current)
            key = identity(inst); occurrence = occurrence_map.get(tuple(current), {})
            row = {"id": current_id, "kind": "occurrence", "occurrence_path": current,
                   "parent_id": rid(path) if path else "root", "ancestors": ancestry,
                   "index": i, "instance_id": inst["id"], "name": inst.get("name"), "instance_type": inst.get("type"),
                   "suppressed": inst.get("suppressed", False), "fixed": occurrence.get("fixed"), "hidden": occurrence.get("hidden"),
                   "transform": occurrence.get("transform"), "transform_scope": "absolute object-to-world; translation in meters",
                   "reference": {k: inst.get(k) for k in ("documentId", "elementId", "documentMicroversion", "documentVersion", "configuration", "fullConfiguration", "partId")}}
            if inst.get("documentId") and inst.get("elementId") and (inst.get("documentMicroversion") or inst.get("documentVersion")):
                mode, ref = ("m", inst["documentMicroversion"]) if inst.get("documentMicroversion") else ("v", inst["documentVersion"])
                row["reference_url"] = element_url({"did": inst["documentId"], "wvm": mode, "wvmid": ref,
                                                    "configuration": inst.get("fullConfiguration", inst.get("configuration", ""))}, inst["elementId"])
            rows.append(row)
            if str(inst.get("type", "")).lower() == "assembly":
                child = definitions.get(key)
                if key in definition_chain:
                    row["children_complete"] = False; issues.append("Cyclic assembly reference at " + current_id)
                elif child is None:
                    row["children_complete"] = False; issues.append("Subassembly definition unavailable at " + current_id)
                else:
                    row["children_complete"] = True
                    visit(child, current, ancestry+[current_id], definition_chain | {key})
        for i, f in enumerate(assembly.get("features", [])):
            rows.append({"id": "assembly_feature:"+json.dumps(path+[f["id"]], separators=(",", ":")),
                         "kind": "assembly_feature", "parent_id": rid(path) if path else "root", "ancestors": ancestry,
                         "occurrence_path": path, "feature_id": f["id"], "index": i,
                         "name": f.get("featureData", {}).get("name"), "feature_type": f.get("featureType"), "suppressed": f.get("suppressed", False)})
    visit(root, [], ["root"], {identity(root)})
    represented = {tuple(r["occurrence_path"]) for r in rows if r["kind"] == "occurrence"}
    for path, occurrence in occurrence_map.items():
        if path not in represented:
            issues.append("Occurrence has no resolved instance definition: " + rid(list(path)))
            rows.append({"id": rid(list(path)), "kind": "unresolved_occurrence", "occurrence_path": list(path),
                         "parent_id": rid(list(path[:-1])) if len(path)>1 else "root", "ancestors": [],
                         "transform": occurrence.get("transform"), "children_complete": False})
    return rows, issues


def assembly_sidebar_rows(native):
    """The editor's display tree includes folders absent from REST occurrences."""
    entries = native.get("assemblyTree", {}).get("pathToNodes", {}).get("$map")
    if entries is None:
        return [], ["Assembly sidebar map unavailable. Reload the updated extension; REST occurrences remain available."]
    nodes = dict(entries)
    issues = []
    if not native.get("assemblyTreeValid") or "" not in nodes:
        issues.append("Assembly sidebar has not finished loading.")
    if len(nodes) != len(entries): issues.append("Duplicate assembly sidebar paths.")
    systems = {"mateList": "mates", "itemList": "items", "loadList": "simulation", "generativeList": "generative"}
    def rid(path):
        if not path: return "assembly_sidebar"
        parts = path.split(".")
        physical = [part for i, part in enumerate(parts[:-1])
                    if not nodes.get(".".join(parts[:i+1]), {}).get("$type", "").endswith("GBTAssemblyTreeFolder")]
        return "assembly_node:" + json.dumps(physical+[parts[-1]], separators=(",", ":"))
    rows = []
    for path, node in entries:
        segments = path.split(".") if path else []
        parent_path = ".".join(segments[:-1])
        typ = node.get("$type", "")
        folder = typ.endswith("GBTAssemblyTreeFolder")
        system = bool(segments and segments[-1] in systems)
        ancestor_paths = [".".join(segments[:i]) for i in range(len(segments))]
        if path and parent_path not in nodes: issues.append("Missing assembly sidebar parent: " + path)
        owner = [p.split(".")[-1] for p in ancestor_paths if nodes.get(p, {}).get("$type", "").endswith(("GBTAssemblyTreeInstance", "GBTAssemblyTreeParametricInstance")) and p]
        category = next((systems[s] for s in reversed(segments) if s in systems), "instances")
        kind = "assembly_sidebar_root" if not path else "assembly_system_folder" if system else "assembly_folder" if folder else "assembly_instance" if typ.endswith(("GBTAssemblyTreeInstance", "GBTAssemblyTreeParametricInstance")) else "assembly_sidebar_feature"
        common = node.get("commonFlags", 0)
        rows.append({"id": rid(path), "kind": kind, "path": path, "node_id": segments[-1] if segments else "",
                     "name": node.get("displayName", ""), "parent_id": rid(parent_path) if path else "root",
                     "ancestors": ["root"] + [rid(p) for p in ancestor_paths], "index": node.get("indexInParent", 0),
                     "category": category, "owner_occurrence_path": owner, "native_type": typ,
                     "children_count": node.get("childrenCount", 0), "suppressed": bool(common & 1), "hidden": bool(common & 2),
                     "native_status": node.get("status"), "read_only": system or not path or bool(owner),
                     "raw_pointer": "/native/assemblyTree/pathToNodes/$map/" + str(len(rows)) + "/1"})
    # Return actual sibling order, independent of JavaScript Map insertion order.
    children = {}
    for row in rows: children.setdefault(row["parent_id"], []).append(row)
    ordered, seen = [], set()
    def walk(parent):
        for row in sorted(children.get(parent, []), key=lambda r: (r["index"], r["id"])):
            if row["id"] in seen: continue
            seen.add(row["id"]); ordered.append(row); walk(row["id"])
    walk("root")
    for row in rows:
        if row["id"] not in seen: ordered.append(row)
        count = len(children.get(row["id"], []))
        if count != row["children_count"]:
            issues.append("Incomplete assembly sidebar children: " + row["id"])
    return ordered, issues


def page_tree(store, data, snapshot, parent_id="", recursive=True, offset=0, limit=20):
    if parent_id and not any(r["id"] == parent_id for r in data["rows"]): raise OnshapeError("Unknown parent ID in this snapshot.")
    rows = [r for r in data["rows"] if not parent_id or r["parent_id"] == parent_id or (recursive and parent_id in r.get("ancestors", []))]
    return {"snapshot": snapshot, "microversion": data["microversion"], "tree_kind": data["tree_kind"],
            **({"occurrences_complete": data["occurrences_complete"], "sidebar_complete": data["sidebar_complete"]} if data["tree_kind"] == "assembly" else {}),
            "complete": data["complete"], "issues": data["issues"], "root_id": "root",
            **store.page(rows, offset=offset, limit=limit),
            "next": "Reuse snapshot to page locally; obtain a fresh snapshot after mutations. IDs, not labels, identify nodes."}


def pointer_get(value, pointer):
    for key in pointer.split("/")[1:]:
        key = key.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def document_native(node):
    kind = node.get("btType", "")
    names = {"BTElementGroup-1458": "document.GBTElementGroup", "BTDocumentElementReference-2484": "document.GBTDocumentElementReference"}
    if kind not in names: raise OnshapeError("Unknown document folder type; refusing a lossy rewrite.")
    out = {"$type": names[kind], **{k: v for k, v in node.items() if k != "btType"}}
    if "groups" in out: out["groups"] = [document_native(c) for c in out["groups"]]
    return out
