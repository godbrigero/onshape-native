"""Progressive API discovery: one registry, not hundreds of model-visible tools."""
import json
import re
from pathlib import Path
from urllib.parse import quote
from .client import OnshapeError


class Catalog:
    def __init__(self):
        self.spec = json.loads((Path(__file__).resolve().parents[1] / "data/openapi.json").read_text())
        self.prefix = "/api/v17"
        self.ops = {o["operationId"]: (method.upper(), path, o)
                    for path, methods in self.spec["paths"].items()
                    for method, o in methods.items() if isinstance(o, dict) and "operationId" in o}

    def search(self, query, limit=10):
        terms = re.findall(r"[a-z0-9]+", query.lower())
        rows = []
        for op, (method, path, data) in self.ops.items():
            hay = (op + " " + path + " " + data.get("summary", "")).lower()
            score = sum(t in hay for t in terms) + (100 if query.lower() == op.lower() else 0)
            if score or not terms:
                rows.append((score, {"operation": op, "method": method, "summary": data.get("summary", "")[:180]}))
        rows.sort(key=lambda row: (-row[0], row[1]["operation"]))
        return {"matches": [v for _, v in rows[:max(1, min(limit, 20))]], "total": len(rows), "schema_version": self.spec["info"]["version"]}

    def schema(self, name):
        if name in self.ops:
            method, path, o = self.ops[name]
            return {"operation": name, "method": method, "path": self.prefix + path,
                    "description": o.get("description", o.get("summary", "")),
                    "parameters": o.get("parameters", []), "requestBody": o.get("requestBody"), "responses": o.get("responses")}
        if name in self.spec["components"]["schemas"]:
            return self.spec["components"]["schemas"][name]
        raise OnshapeError("Unknown operation/schema. Use api_catalog first.")

    def resolve(self, operation, path_params, query=None):
        if operation not in self.ops:
            raise OnshapeError("Unknown operation. Use api_catalog.")
        method, path, op = self.ops[operation]
        required = set(re.findall(r"\{(\w+)\}", path))
        if set(path_params) != required:
            raise OnshapeError(f"Path parameters must be exactly: {sorted(required)}")
        for key, value in path_params.items():
            if not isinstance(value, str) or not value or value in (".", ".."):
                raise OnshapeError("Path values must be nonempty strings.")
            path = path.replace("{" + key + "}", quote(value, safe=""))
        declared = {p["name"] for p in op.get("parameters", []) if p.get("in") == "query"}
        if set(query or {}) - declared:
            raise OnshapeError(f"Unknown query parameters: {sorted(set(query or {}) - declared)}")
        for p in op.get("parameters", []):
            if p.get("in") == "query" and p.get("required") and p["name"] not in (query or {}):
                raise OnshapeError(f"Missing query parameter: {p['name']}")
        return method, self.prefix + path
