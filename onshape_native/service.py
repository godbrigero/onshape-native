from __future__ import annotations

import asyncio
import copy
import json
import re
from urllib.parse import urlsplit, parse_qs

from .catalog import Catalog
from .client import Client, OnshapeError, Settings
from .geometry import SUMMARY_SCRIPT, decode_fs, delta, feature_rows
from .store import Store


class Service:
    def __init__(self, settings=None, transport=None):
        self.settings = settings or Settings.load()
        self.client = Client(self.settings, transport)
        self.catalog = Catalog()
        self.store = Store(self.settings.cache_dir)
        self.locks = {}

    async def call(self, operation, path=None, query=None, body=None):
        method, url = self.catalog.resolve(operation, path or {}, query)
        return await self.client.request(method, url, query, body, read_only=operation == "evalFeatureScript")

    def target(self, url):
        u = urlsplit(url)
        if u.netloc != urlsplit(self.settings.base_url).netloc or u.scheme != "https":
            raise OnshapeError("Document URL must match the configured Onshape HTTPS stack.")
        m = re.fullmatch(r"/documents/([a-f0-9]{24})/([wvm])/([a-f0-9]{24})/e/([a-f0-9]{24})/?", u.path)
        if not m:
            raise OnshapeError("Provide an Onshape element URL: /documents/DID/w/WID/e/EID (or v/m).")
        return dict(zip(("did", "wvm", "wvmid", "eid"), m.groups())), parse_qs(u.query).get("configuration", [""])[0]

    def snapshot_data(self, snapshot):
        data = self.store.read(snapshot)
        if data.get("kind") != "onshape-snapshot":
            raise OnshapeError("Expected a snapshot artifact from inspect_model.")
        return data

    @staticmethod
    def pinned(data):
        return {**data["target"], "wvm": "m", "wvmid": data["microversion"]}

    async def eval(self, data, script, queries=None):
        result = await self.call("evalFeatureScript", self.pinned(data),
                                 {"configuration": data["configuration"]},
                                 {"script": script, "queries": queries or {}, "libraryVersion": data["libraryVersion"]})
        parsed = decode_fs(result.get("result"))
        if parsed is None:
            # Notices are bounded by artifact paging; they may contain user model text.
            return {"evaluation_failed": True, "details": self.store.response(result)}
        return {"result": parsed, "notices": result.get("notices", [])}

    async def inspect(self, url, geometry=True, previous=None):
        target, configuration = self.target(url)
        old = self.snapshot_data(previous) if previous else None
        if old and (old["target"] != target or old["configuration"] != configuration):
            raise OnshapeError("Previous snapshot refers to another element or configuration.")
        raw = await self.call("getPartStudioFeatures", target, {"configuration": configuration, "noSketchGeometry": True})
        micro = raw.get("sourceMicroversion")
        if not micro:
            raise OnshapeError("Feature response lacks sourceMicroversion; cannot construct a consistent snapshot.")
        if old and micro == old["microversion"] and (not geometry or old.get("geometry_complete")):
            return {"snapshot": previous, "microversion": micro, "unchanged": True, "api_calls": 1}
        data = {"kind": "onshape-snapshot", "url": url, "target": target, "configuration": configuration,
                "microversion": micro, "libraryVersion": raw["libraryVersion"],
                "serializationVersion": raw["serializationVersion"], "features": feature_rows(raw),
                "feature_artifact": self.store.put(raw)["artifact"],
                "frame": {"coordinates": "Part Studio world, right-handed XYZ", "length": "mm", "volume": "mm^3"},
                "geometry_complete": False}
        if geometry:
            parts, measured = await asyncio.gather(
                self.call("getPartsWMVE", self.pinned(data), {"configuration": configuration}),
                self.eval(data, SUMMARY_SCRIPT))
            names = {p["partId"]: p.get("name") for p in parts}
            data["part_count"] = len(parts)
            data["parts"] = [{"id": p["partId"], "name": p.get("name"), "type": p.get("bodyType")} for p in parts]
            if isinstance(measured.get("result"), list):
                data["solids"] = [{**p, "name": names.get(p["id"])} for p in measured["result"]]
                data["geometry_complete"] = True
            else:
                data["geometry_error"] = measured
        saved = self.store.put(data)
        output = {"snapshot": saved["artifact"], "microversion": micro, "frame": data["frame"],
                  "feature_count": len(data["features"]), "geometry_complete": data["geometry_complete"],
                  "feature_errors": [f for f in data["features"] if f["status"] not in ("OK", "SUPPRESSED")],
                  "artifact_path": saved["path"]}
        if old and old.get("geometry_complete") == data.get("geometry_complete"):
            output["delta"] = delta(old, data)
        else:
            output.update({k: data[k] for k in ("features", "solids", "parts", "geometry_error") if k in data})
        if len(json.dumps(output)) > 9000:
            for field in ("features", "solids", "parts", "feature_errors", "delta"):
                if field in output:
                    output[field] = {"omitted": True, "retrieve": "artifact_page", "pointer": "/" + field}
            output["note"] = "Full snapshot is saved. Page features, parts, and solids from snapshot; delta can be derived from snapshots."
        return output

    async def feature(self, snapshot, action, changes):
        data = self.snapshot_data(snapshot)
        if data["target"]["wvm"] != "w":
            raise OnshapeError("Versions and microversions are immutable; choose a workspace URL.")
        if not 1 <= len(changes) <= 20:
            raise OnshapeError("Supply 1-20 changes. Batch is sequential, not atomic.")
        if action not in ("add", "edit"):
            raise OnshapeError("Use add or edit.")
        if action == "edit" and len({c.get("id") for c in changes}) != len(changes):
            raise OnshapeError("Combine all changes to the same feature into one edit entry.")
        raw = self.store.read(data["feature_artifact"])
        originals = {f["featureId"]: f for f in raw.get("features", [])}
        work = []
        for change in changes:
            if action == "add":
                if change.get("featureId"):
                    raise OnshapeError("Do not reuse an existing featureId when adding a feature.")
                if not change.get("featureType") or not change.get("name"):
                    raise OnshapeError("Added feature needs featureType and name; use current feature schema.")
                f = copy.deepcopy(change)
            else:
                if change.get("id") not in originals:
                    raise OnshapeError("Feature ID is absent from this snapshot.")
                f = copy.deepcopy(originals[change["id"]])
                if set(change) - {"id", "parameters", "name", "suppressed"}:
                    raise OnshapeError("Edit keys: id, parameters, name, suppressed.")
                if f.get("featureType") == "newSketch":
                    # A lightweight snapshot omits sketch entities. Fetch a complete definition
                    # at the same immutable revision before editing, never erase constraints.
                    full = await self.call("getPartStudioFeatures", self.pinned(data),
                                           {"featureId": [change["id"]], "configuration": data["configuration"], "noSketchGeometry": False})
                    f = next(x for x in full["features"] if x["featureId"] == change["id"])
                for k in ("name", "suppressed"):
                    if k in change:
                        f[k] = change[k]
                params = {p["parameterId"]: p for p in f.get("parameters", [])}
                for pid, patch in change.get("parameters", {}).items():
                    if pid not in params:
                        raise OnshapeError(f"Unknown parameter {pid}; inspect the feature definition.")
                    if isinstance(patch, str):
                        if "expression" not in params[pid]:
                            raise OnshapeError("String shorthand requires an expression parameter.")
                        params[pid]["expression"] = patch
                    elif isinstance(patch, dict) and not set(patch) - {"expression", "value", "queries"}:
                        params[pid].update(patch)
                    else:
                        raise OnshapeError("Use expression string or a patch with expression/value/queries.")
            work.append(f)
        result, micro = [], data["microversion"]
        lock = self.locks.setdefault(data["target"]["did"] + data["target"]["wvmid"], asyncio.Lock())
        async with lock:
            for f in work:
                body = {"btType": "BTFeatureDefinitionCall-1406", "feature": f,
                        "sourceMicroversion": micro, "rejectMicroversionSkew": True,
                        "libraryVersion": data["libraryVersion"], "serializationVersion": data["serializationVersion"]}
                target = data["target"]
                op, path = "addPartStudioFeature", target
                if action == "edit":
                    op, path = "updatePartStudioFeature", {"did": target["did"], "wid": target["wvmid"], "eid": target["eid"], "fid": f["featureId"]}
                try:
                    response = await self.call(op, path, body=body)
                except OnshapeError as error:
                    return {"completed": result, "stopped": True, "error": str(error), "next": "Inspect current state before continuing; completed changes remain."}
                result.append({"id": response.get("feature", {}).get("featureId"),
                               "name": f["name"], "state": response.get("featureState"),
                               "response": self.store.put(response)["artifact"]})
                micro = response.get("sourceMicroversion")
                if not micro or response.get("microversionSkew") or response.get("featureState", {}).get("featureStatus") != "OK":
                    return {"completed": result, "stopped": True, "next": "Inspect regeneration errors; do not replay the batch."}
        return {"completed": result, "microversion": micro, "next": "inspect_model(url, previous=snapshot) to verify geometry and refresh references"}

    async def write(self, operation, path, query, body):
        method, _ = self.catalog.resolve(operation, path, query)
        if method == "GET" or operation == "evalFeatureScript":
            raise OnshapeError("Use api_read or evaluate for reads.")
        if path.get("wvm") in ("v", "m"):
            raise OnshapeError("Mutation requires a workspace, not a version/microversion.")
        if operation in ("addPartStudioFeature", "updatePartStudioFeature", "updateFeatures", "updateFeatureStudioContents"):
            if not body or not body.get("sourceMicroversion") or body.get("rejectMicroversionSkew") is not True:
                raise OnshapeError("Feature writes require sourceMicroversion and rejectMicroversionSkew=true. Prefer feature tool.")
        if operation == "createDocument":
            body = {**(body or {}), "isPublic": (body or {}).get("isPublic", False)}
        return self.store.response(await self.call(operation, path, query, body))
