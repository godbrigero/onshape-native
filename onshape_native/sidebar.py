"""Prepare browser-only folder actions and independently verify CAD invariants.

These are explicitly not undocumented REST mutations. Onshape's public feature
API does not serialize Part Studio folder boundaries. The caller executes the
returned workflow through Codex Computer Use, then attaches observed UI evidence.
"""
from __future__ import annotations

import math
from .client import OnshapeError

ACTIONS = {"create_folder", "rename_folder", "unpack_folder", "move_into_folder", "reorder_features"}


def prepare_plan(data, snapshot, action, feature_ids, folder_name, new_name, before_feature_id, allow_reorder):
    if action not in ACTIONS:
        raise OnshapeError("Unsupported sidebar action.")
    if data["target"]["wvm"] != "w":
        raise OnshapeError("Sidebar editing requires a workspace URL.")
    if not data.get("geometry_complete"):
        raise OnshapeError("A successful geometry baseline is required before organizing the sidebar.")
    if any(not isinstance(x, str) for x in feature_ids) or len(set(feature_ids)) != len(feature_ids):
        raise OnshapeError("Feature IDs must be distinct strings.")
    if len(feature_ids) > 100:
        raise OnshapeError("Select at most 100 features per sidebar operation.")
    if allow_reorder and action not in ("move_into_folder", "reorder_features"):
        raise OnshapeError("This folder action must preserve feature order.")
    rows = data["features"]
    order = [f["id"] for f in rows]
    if set(feature_ids) - set(order):
        raise OnshapeError("Selection contains feature IDs absent from the baseline.")
    selected = [f for f in rows if f["id"] in feature_ids]
    positions = [order.index(f["id"]) for f in selected]
    if action == "create_folder" and positions and positions != list(range(min(positions), max(positions)+1)):
        raise OnshapeError("Choose a contiguous feature range for folder creation; group separate ranges separately.")
    if action in ("create_folder", "rename_folder", "unpack_folder", "move_into_folder") and not folder_name.strip():
        raise OnshapeError("folder_name is required. For nested folders, provide the full visible path.")
    if action == "rename_folder" and not new_name.strip():
        raise OnshapeError("new_name is required.")
    if action in ("move_into_folder", "reorder_features") and not selected:
        raise OnshapeError("Select at least one feature.")
    if action == "reorder_features" and not allow_reorder:
        raise OnshapeError("Reordering requires allow_reorder=true and authorization to change feature order.")
    if before_feature_id and (before_feature_id not in order or before_feature_id in feature_ids):
        raise OnshapeError("before_feature_id must identify an unselected baseline feature.")
    if before_feature_id and action != "reorder_features":
        raise OnshapeError("before_feature_id is only supported for reorder_features.")
    expected_order = order
    if action == "reorder_features":
        expected_order = [f for f in order if f not in feature_ids]
        at = expected_order.index(before_feature_id) if before_feature_id else len(expected_order)
        expected_order[at:at] = [f["id"] for f in selected]
    instructions = {
        "create_folder": "Select the listed contiguous features in order, right-click and choose Add selection to folder, then enter folder_name. For an empty selection, use the feature-list folder button. Check that the folder contains exactly the intended range.",
        "rename_folder": "Locate the exact folder path, open its context menu and choose Rename. Enter new_name and verify the new label. Do not rename a feature with a similar name.",
        "unpack_folder": "Locate the exact folder and use Unpack (preserve contents). Never substitute Delete: deleting a folder can delete its features.",
        "move_into_folder": "Locate the exact destination folder and selected features. Move them using the visible sidebar controls. If preserving feature order is impossible and allow_reorder is false, stop and report the conflict.",
        "reorder_features": "Move the selected features, preserving their relative order, immediately before before_feature_id, or to the end if empty. Verify the actual sequence and wait for regeneration.",
    }
    return {"kind": "onshape-sidebar-plan", "snapshot": snapshot, "url": data["url"],
            "microversion": data["microversion"], "action": action, "selection": [{"id": f["id"], "name": f["name"]} for f in selected],
            "folder_name": folder_name.strip(), "new_name": new_name.strip(), "before_feature_id": before_feature_id,
            "allow_reorder": allow_reorder, "expected_order": expected_order,
            "execution": "browser_required", "model_changed_by_prepare": False,
            "workflow": [
                "Use Codex's browser tools (cua_repl) to open/select this exact Onshape element URL. No API keys belong in the browser.",
                "Read current accessibility state. Disambiguate duplicate feature/folder labels by position/path. Do not interrupt an active feature dialog or another task's browser session.",
                "Check that the displayed feature order matches the baseline before acting. If a collaborator changed the model, prepare a fresh plan.",
                instructions[action],
                "Read fresh sidebar accessibility state after the action; use a screenshot only if the tree is not exposed. Verify folder membership/name/order visually, not from API feature rows.",
                "Call sidebar_verify with the plan handle and a short factual browser observation. A prepared plan alone has performed no folder change.",
            ]}


def compare_baseline(before, after, plan, tolerance_mm=1e-6):
    if not math.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise OnshapeError("tolerance_mm must be finite and positive.")
    if before["target"] != after["target"] or before["configuration"] != after["configuration"]:
        raise OnshapeError("Baseline and result must refer to the same element and configuration.")
    issues = []
    a, b = before["features"], after["features"]
    a_by_id, b_by_id = {f["id"]: f for f in a}, {f["id"]: f for f in b}
    if a_by_id.keys() != b_by_id.keys():
        issues.append("feature_inventory_changed")
    for fid in a_by_id.keys() & b_by_id.keys():
        for field in ("name", "type", "suppressed", "parameters"):
            if a_by_id[fid].get(field) != b_by_id[fid].get(field):
                issues.append(f"feature_{field}_changed:{fid}")
        if a_by_id[fid].get("status") != b_by_id[fid].get("status"):
            issues.append(f"regeneration_status_changed:{fid}")
    failures = [f["id"] for f in b if f.get("status") not in ("OK", "SUPPRESSED")]
    if failures:
        issues.append("regeneration_not_clean")
    if not plan["allow_reorder"] or plan["action"] == "reorder_features":
        if [f["id"] for f in b] != plan["expected_order"]:
            issues.append("unexpected_feature_order")
    if not before.get("geometry_complete") or not after.get("geometry_complete"):
        issues.append("geometry_unavailable")
    old_parts, new_parts = before.get("parts", []), after.get("parts", [])
    if sorted((p["id"], p.get("type") or "") for p in old_parts) != sorted((p["id"], p.get("type") or "") for p in new_parts):
        issues.append("part_inventory_changed")
    old = {p["id"]: p for p in before.get("solids", [])}
    new = {p["id"]: p for p in after.get("solids", [])}
    if old.keys() != new.keys():
        issues.append("solid_inventory_changed")
    for pid in old.keys() & new.keys():
        for field in ("min_mm", "max_mm", "size_mm"):
            if any(not math.isclose(x, y, abs_tol=tolerance_mm, rel_tol=1e-10) for x, y in zip(old[pid][field], new[pid][field], strict=True)):
                issues.append(f"{field}_changed:{pid}")
        if not math.isclose(old[pid]["volume_mm3"], new[pid]["volume_mm3"], abs_tol=1e-6, rel_tol=1e-10):
            issues.append(f"volume_changed:{pid}")
        for field in ("faces", "edges"):
            if old[pid][field] != new[pid][field]:
                issues.append(f"{field}_changed:{pid}")
    return {"api_checks_passed": not issues, "issues": issues, "regeneration_failures": failures,
            "baseline_microversion": before["microversion"], "current_microversion": after["microversion"],
            "geometry_check_scope": "Solid bounds, volume, topology counts and part inventory; not a proof of B-rep equivalence. Sheets/wires are inventory-only.",
            "folder_membership_verified_by_api": False,
            "next": "Review browser evidence to confirm the folder operation. API checks alone cannot prove a folder was created or renamed."}

