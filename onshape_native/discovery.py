"""Offline sparse-vector retrieval and exhaustive, deterministic command browsing.

TF-IDF vectors are normalized and ranked by cosine similarity. No remote model,
API key, user CAD content, or network request is involved in building the index.
"""
from __future__ import annotations

import ast
from collections import Counter
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re

from .catalog import Catalog
from .client import OnshapeError
from .native_catalog import catalog as native_catalog

ROOT = Path(__file__).resolve().parents[1]
STOP = set("a an and are as at be by can do does for from how i in into is it me much of on or should that the this to use using want with would you".split())
ALIASES = {
    "weight": "mass density material", "weigh": "mass properties", "heavy": "mass density",
    "hollow": "shell thickness", "round": "fillet radius", "bevel": "chamfer",
    "cube": "sketch extrude depth", "torus": "sketch circle revolve",
    "duplicate": "copy", "dupe": "copy duplicate", "remove": "delete",
    "make": "create add", "browse": "tree traverse hierarchy", "traverse": "tree hierarchy",
    "directory": "folder group", "tabs": "tab element", "tab": "element",
    "partstudio": "part studio", "partstudios": "part studio",
    "folders": "folder group", "sidebar": "feature folder tree",
    "history": "microversion revision", "undo": "history restore",
    "assemble": "assembly instance mate", "assembly": "occurrence instance",
    "extrusion": "extrude depth", "thickness": "depth shell",
    "height": "extrude depth length", "taller": "extrude depth length", "change": "edit modify",
}
HINTS = {
    "display_state": "assembly complete sidebar actual effective visibility hidden shown inherited Part Studio mate connectors motors joints display markers",
    "set_visibility": "batch show hide individual mates joints inherited Part Studio connectors assembly occurrences markers",
    "mate_animation": "animate revolute mate lidar rotor motion preview play stop step angle restore pose",
    "view_control": "camera front back left right top bottom isometric orientation zoom fit selection occurrences save restore view",
    "capture_viewport": "screenshot current viewport image markers connectors visibility PNG artifact",
    "resolve_target": "current opened active Onshape browser window tab URL link choose target document workspace",
    "getDocumentContents": "traverse browse document tabs nested folders hierarchy parent children",
    "getDocumentHistory": "document tab edit history microversions changes timeline",
    "copyElementFromSourceDocument": "duplicate copy part studio assembly tab",
    "updateWVEMetadata": "rename tab part studio assembly element name properties",
    "GBTUiEditElementGroups": "create rename delete unpack move document tab folders hierarchy",
    "GBTUiCreateFolder": "create feature sidebar folder group contiguous feature range",
    "GBTUiDeleteFolder": "delete unpack feature sidebar folder keep contents",
    "GBTUiReorderFeatures": "move reorder feature sidebar folder hierarchy",
    "GBTUiBatchPartPropertyChange": "assign material density mass weight part properties",
    "GBTUiMassPropCall": "measure mass weight volume center gravity inertia",
    "getPartMassProperties": "how much does this part weigh measure mass weight volume center gravity inertia",
    "getAssemblyMassProperties": "how much does assembly weigh measure total mass weight center gravity inertia",
    "feature_template": "create modify cube height extrusion depth round solid edges fillet hollow shell thickness torus revolve sketch loft sweep pattern parameters",
    "feature": "change edit cube height extrusion depth round solid edges fillet hollow shell thickness torus revolve sketch parameters",
    "document_edit": "move Part Studio tab into document folder create rename delete duplicate assembly tab folder unpack nested folders",
    "document_tree": "browse traverse Part Studios assemblies document tabs nested folders hierarchy parents children",
    "element_tree": "browse traverse feature sidebar folder assembly occurrence instances mate hierarchy parents children",
    "sidebar_edit": "move features into sidebar folder create rename delete unpack nested feature folders reorder suppress features",
}
MANUAL = [
    "Call browse_commands with source=rest/tool/native and literal query words; paginate next_offset until exhausted. Empty query enumerates every entry.",
    "For REST: api_catalog(schema=operation), then follow request/response $ref component names. Path keys must match exactly.",
    "For modeling: inspect_model, then feature_template to discover live feature types and parameter specifications.",
    "For native: native_catalog(search=exact_name), native_schema(url,name), and fresh native_state. Check evidence; a constructor is not proof of a callable RPC.",
    "If still missing: inspect the actual action in Comet DevTools Network; route an observed /api/ request through api_request. Never guess endpoint or payload fields.",
    "Use ui_inspect/ui_action only when backend execution is unavailable, then verify persisted server state. Do not replay an action already performed during research.",
]


def words(text):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]


def terms(text):
    tokens = words(text)
    result = Counter(tokens)
    for a, b in zip(tokens, tokens[1:]):
        result[a + " " + b] += .7
    for token in tokens:
        for alias in ALIASES.get(token, "").split():
            result[alias] += .45
    return result


def records():
    c = Catalog()
    rows = []
    for name, (method, path, spec) in c.ops.items():
        multipart = "multipart/form-data" in (spec.get("requestBody") or {}).get("content", {})
        tool = "api_read" if method == "GET" else "api_upload" if multipart else "api_request" if name == "evalFeatureScript" else "api_write"
        route = {"tool": tool, "operation": name, "schema": name}
        if tool == "api_request": route.update(method=method, endpoint=c.prefix + path)
        row = {"id": "rest:" + name, "source": "rest", "name": name, "method": method,
               "path": c.prefix + path, "summary": spec.get("summary", ""),
               "read_only": method == "GET" or name == "evalFeatureScript", "evidence": "official-schema",
               "available": name != "session", "invoke": route}
        details = " ".join(p["name"] + " " + p.get("description", "") for p in spec.get("parameters", []))
        row["_hints"] = HINTS.get(name, "")
        row["_text"] = " ".join([name, name, path, spec.get("summary", ""), spec.get("description", ""), details, " ".join(spec.get("tags", [])), row["_hints"]])
        rows.append(row)
    for item in native_catalog():
        name = item["command"]
        rows.append({"id": "native:" + name, "source": "native", "name": name,
                     "summary": HINTS.get(name.split(".")[-1], "Native serializer candidate; inspect its schema and evidence."),
                     "read_only": item["read_only"], "evidence": item["evidence"],
                     "replay_verified": item.get("replay_verified", False), "available": True,
                     "invoke": {"tool": "native_read" if item["read_only"] else "native_write", "command": name,
                                "schema_tool": "native_schema", "requires": ["url", "body"] + ([] if item["read_only"] else ["expected_microversion"])},
                     "_hints": HINTS.get(name.split(".")[-1], ""),
                     "_text": name + " " + HINTS.get(name.split(".")[-1], "") + " " + " ".join(item.get("defaults", {}))})
    source = ast.parse((ROOT / "onshape_native/server.py").read_text())
    for fn in source.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
        dec = next((d for d in fn.decorator_list if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "tool"), None)
        if dec is None: continue
        annotation = next((k.value for k in dec.keywords if k.arg == "annotations"), None)
        read = isinstance(annotation, ast.Name) and annotation.id in ("READ", "LOCAL_READ")
        if isinstance(annotation, ast.Call):
            read = any(k.arg == "readOnlyHint" and isinstance(k.value, ast.Constant) and k.value.value is True for k in annotation.keywords)
        description = ast.get_docstring(fn) or ""
        rows.append({"id": "tool:" + fn.name, "source": "tool", "name": fn.name,
                     "summary": description.split(". ")[0], "read_only": read, "evidence": "implemented-tool", "available": True,
                     "invoke": {"tool": fn.name, "arguments": [a.arg for a in fn.args.args]},
                     "_hints": HINTS.get(fn.name, ""), "_text": fn.name + " " + description + " " + HINTS.get(fn.name, "")})
    return sorted(rows, key=lambda r: r["id"])


class SearchIndex:
    def __init__(self, rows):
        self.rows = rows
        bags = [terms(r["_text"]) for r in rows]
        df = Counter(t for b in bags for t in b)
        self.idf = {t: math.log((1 + len(rows)) / (1 + count)) + 1 for t, count in df.items()}
        self.vectors = [self.vector(b) for b in bags]
        self.hint_vectors = [self.vector(terms(r.get("_hints", ""))) for r in rows]
        public = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
        self.fingerprint = hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()

    def vector(self, bag):
        v = {t: (1 + math.log(c)) * self.idf[t] for t, c in bag.items() if t in self.idf and c >= 1}
        # Fractional expansions remain positive; log weighting is only for repeated terms.
        v.update({t: c * self.idf[t] for t, c in bag.items() if t in self.idf and c < 1})
        norm = math.sqrt(sum(x*x for x in v.values()))
        return {t: x/norm for t, x in v.items()} if norm else {}

    @staticmethod
    def public(row):
        return {k: v for k, v in row.items() if not k.startswith("_")}

    def filtered(self, source="all", read_only=None, method=""):
        if source not in {"all", "rest", "native", "tool"}: raise OnshapeError("source must be all, rest, native, or tool.")
        if method and method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}: raise OnshapeError("Invalid HTTP method filter.")
        return [(i, r) for i, r in enumerate(self.rows)
                if (source == "all" or r["source"] == source) and (read_only is None or r["read_only"] == read_only)
                and (not method or r.get("method") == method)]

    def search(self, task, limit=10, source="all", read_only=None):
        if not isinstance(task, str) or not task.strip() or len(task) > 4000: raise OnshapeError("Supply a task of 1–4000 characters.")
        if not 1 <= limit <= 10: raise OnshapeError("limit must be 1–10.")
        q = self.vector(terms(task))
        scored = []
        for i, row in self.filtered(source, read_only):
            vector = max((self.vectors[i], self.hint_vectors[i]), key=lambda vec: sum(v*vec.get(t,0) for t,v in q.items()))
            score = sum(v * vector.get(t, 0) for t, v in q.items())
            if task.strip().casefold() in (row["id"].casefold(), row["name"].casefold()): score = 1.0
            if score > 0:
                matched = sorted((t for t in q if t in vector), key=lambda t: -q[t]*vector[t])[:6]
                scored.append((score, row, matched))
        scored.sort(key=lambda x: (-x[0], x[1]["id"]))
        return {"engine": "local-tfidf-cosine", "index": self.fingerprint, "indexed_commands": len(self.rows),
                "matches": [{**self.public(r), "score": round(score, 6), "matched_terms": matched} for score, r, matched in scored[:limit]],
                "low_confidence": not scored or scored[0][0] < .18,
                "score_meaning": "Cosine similarity, not execution confidence. Native evidence is separate; inspect schemas before writing.",
                "manual_fallback": MANUAL}

    def browse(self, query="", source="all", read_only=None, method="", offset=0, limit=20):
        if offset < 0 or not 1 <= limit <= 100 or len(query) > 4000: raise OnshapeError("Use offset >= 0, limit 1–100, and query <= 4000 characters.")
        needles = query.casefold().split()
        rows = [r for _, r in self.filtered(source, read_only, method) if all(n in (r["id"] + " " + r["_text"]).casefold() for n in needles)]
        page = rows[offset:offset+limit]
        return {"matches": [self.public(r) for r in page], "total": len(rows),
                "next_offset": offset+len(page) if offset+len(page) < len(rows) else None, "manual_procedure": MANUAL}


@lru_cache(maxsize=1)
def index():
    return SearchIndex(records())
