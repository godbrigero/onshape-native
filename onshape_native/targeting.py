"""Resolve task scope without guessing from tab order or background documents."""
from .client import OnshapeError
from .structures import target_from_url


def resolve_context(url="", tab_id=None, context=None):
    explicit = target_from_url(url.strip()) if url.strip() else None
    if tab_id is not None and (isinstance(tab_id, bool) or not isinstance(tab_id, int) or tab_id < 0):
        raise OnshapeError("tab_id must be a nonnegative browser tab ID.")
    context = context or {}
    tabs = context.get("tabs", [])
    candidates = []
    for tab in tabs:
        try:
            target_from_url(tab.get("url", ""))
        except (OnshapeError, ValueError):
            continue
        candidates.append({key: tab.get(key) for key in ("id", "title", "url", "active", "window_id")})

    def unresolved(reason):
        return {"status": "needs_selection", "reason": reason, "candidates": candidates[:50],
                "candidate_count": len(candidates),
                "next": "Supply an exact Onshape URL or tab_id. Do not choose a background tab on the user's behalf."}

    selected = None
    if tab_id is not None:
        selected = next((tab for tab in tabs if tab.get("id") == tab_id), None)
        if selected is None:
            return unresolved("The requested tab is no longer available in the connected browser.")
        try:
            tab_target = target_from_url(selected.get("url", ""))
        except (OnshapeError, ValueError):
            return unresolved("The selected tab is not an Onshape document URL.")
        if explicit is not None and explicit != tab_target:
            return unresolved("The supplied URL and tab_id refer to different document contexts.")
    elif explicit is None:
        if context.get("context_version") != 1 or context.get("last_focused_window_id") is None:
            return unresolved("Current-window metadata is unavailable. Reload the updated extension or supply a URL.")
        active = [tab for tab in tabs if tab.get("active") is True and
                  tab.get("window_id") == context["last_focused_window_id"]]
        if len(active) != 1:
            return unresolved("The last-focused browser window has no single active Onshape tab.")
        selected = active[0]

    source = "url" if explicit is not None else "tab_id" if tab_id is not None else "current_tab"
    resolved_url = url.strip() if explicit is not None else selected["url"]
    try:
        target = explicit or target_from_url(resolved_url)
    except (OnshapeError, ValueError):
        return unresolved("The active Onshape page is not a document. Open a document or supply its URL.")
    return {"status": "resolved", "source": source, "url": resolved_url, "target": target,
            "tab_id": selected.get("id") if selected else None,
            "workspace_url": target["wvm"] == "w",
            "native_editor_eligible": target["wvm"] == "w" and bool(target["eid"]) and not target["configuration"],
            "next": "Call document_tree to identify the element type and document folders, then element_tree. Use inspect_model only for a Part Studio.",
            "scope": "Keep this resolved URL for the task. Re-resolve only when the user changes the target. Workspace URLs still require edit permission; v/m URLs are read-only."}
