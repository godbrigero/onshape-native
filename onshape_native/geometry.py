"""Kernel-side measurements: geometry, not pixels, is the source of truth."""

SUMMARY_SCRIPT = '''function(context is Context, queries) {
    const bodies = evaluateQuery(context, qBodyType(qEverything(EntityType.BODY), BodyType.SOLID));
    var rows = [];
    for (var body in bodies) {
        const bounds = evBox3d(context, { "topology" : body, "tight" : true });
        rows = append(rows, {
            "id" : transientQueriesToStrings([body])[0],
            "min_mm" : bounds.minCorner / millimeter,
            "max_mm" : bounds.maxCorner / millimeter,
            "size_mm" : (bounds.maxCorner - bounds.minCorner) / millimeter,
            "volume_mm3" : evVolume(context, { "entities" : body }) / (millimeter^3),
            "faces" : size(evaluateQuery(context, qOwnedByBody(body, EntityType.FACE))),
            "edges" : size(evaluateQuery(context, qOwnedByBody(body, EntityType.EDGE)))
        });
    }
    return rows;
}'''


def decode_fs(value):
    """Decode typed FeatureScript values; unknown representations remain explicit."""
    if isinstance(value, list):
        return [decode_fs(x) for x in value]
    if not isinstance(value, dict):
        return value
    msg = value.get("message", value)
    typ = str(value.get("typeName", value.get("btType", "")))
    if "FSValueMap" in typ:
        out = {}
        for pair in msg.get("value", []):
            pair = pair.get("message", pair)
            out[str(decode_fs(pair["key"]))] = decode_fs(pair["value"])
        return out
    if any(t in typ for t in ("FSValueArray", "FSValueVector")):
        return [decode_fs(x) for x in msg.get("value", [])]
    if any(t in typ for t in ("FSValueString", "FSValueNumber", "FSValueBoolean")):
        if msg.get("unitToPower"):
            return {"value": msg.get("value"), "units": msg["unitToPower"]}
        return msg.get("value")
    return {k: decode_fs(v) for k, v in value.items()}


def feature_rows(raw):
    states = raw.get("featureStates", {})
    return [{"id": f.get("featureId"), "name": f.get("name"), "type": f.get("featureType"),
             "suppressed": f.get("suppressed", False),
             "status": states.get(f.get("featureId"), {}).get("featureStatus", "UNKNOWN"),
             "parameters": {p["parameterId"]: p.get("expression", p.get("value"))
                            for p in f.get("parameters", [])
                            if "parameterId" in p and ("expression" in p or "value" in p)}}
            for f in raw.get("features", [])]


def delta(before, after):
    out = {}
    for field in ("features", "solids"):
        a = {v["id"]: v for v in before.get(field, [])}
        b = {v["id"]: v for v in after.get(field, [])}
        out[field] = {"added": [b[k] for k in b.keys() - a.keys()],
                      "removed": sorted(a.keys() - b.keys()),
                      "changed": [b[k] for k in b.keys() & a.keys() if a[k] != b[k]]}
    return out


def measurement_script(expression, metrics, other=""):
    """Small caller inputs expand into one deterministic kernel-side batch."""
    from .client import OnshapeError
    if not expression or not metrics or len(metrics) > 8:
        raise OnshapeError("Supply a Query expression and 1-8 metrics.")
    statements = ['const q = (' + expression + ');', 'const count = size(evaluateQuery(context, q));',
                  'var result = { "count" : count };', 'if (count == 0) return result;']
    definitions = {
        "bounds": 'const b = evBox3d(context, {"topology":q,"tight":true}); result.bounds_mm = {"min":b.minCorner/millimeter,"max":b.maxCorner/millimeter,"size":(b.maxCorner-b.minCorner)/millimeter};',
        "volume": 'result.volume_mm3 = evVolume(context, {"entities":q})/(millimeter^3);',
        "area": 'result.area_mm2 = evArea(context, {"entities":q})/(millimeter^2);',
        "length": 'result.length_mm = evLength(context, {"entities":q})/millimeter;',
        "plane": 'if (count == 1) { const p = evPlane(context, {"face":q}); result.plane = {"origin_mm":p.origin/millimeter,"normal":p.normal,"x":p.x}; } else result.plane_error = "Expected exactly one face";',
        "distance": 'const other = (' + (other or 'qNothing()') + '); result.other_count = size(evaluateQuery(context, other)); if (result.other_count > 0) result.distance_mm = evDistance(context, {"side0":q,"side1":other}).distance/millimeter;',
    }
    for metric in dict.fromkeys(metrics):
        if metric not in definitions:
            raise OnshapeError("Metrics: bounds, volume, area, length, plane, distance.")
        if metric == "distance" and not other:
            raise OnshapeError("distance requires other_expression.")
        statements.append(definitions[metric])
    return 'function(context is Context, queries) { ' + ' '.join(statements) + ' return result; }'


def topology_script(expression, offset=0, limit=20):
    from .client import OnshapeError
    if not expression or offset < 0 or not 1 <= limit <= 50:
        raise OnshapeError("topology requires a face Query, offset >= 0, and limit 1-50.")
    return '''function(context is Context, queries) {
      const faces = evaluateQuery(context, qEntityFilter((''' + expression + '''), EntityType.FACE));
      var rows = [];
      for (var i = ''' + str(offset) + '''; i < min(size(faces), ''' + str(offset + limit) + '''); i += 1) {
        const face = faces[i];
        const surface = evSurfaceDefinition(context, {"face":face,"returnBSplinesAsOther":true});
        var row = {"id":transientQueriesToStrings([face])[0],
                   "area_mm2":evArea(context,{"entities":face})/(millimeter^2),
                   "adjacent_faces":transientQueriesToStrings(evaluateQuery(context,qAdjacent(face,AdjacencyType.EDGE,EntityType.FACE)))};
        if (surface is Plane) {
          row["type"] = "plane";
          row.origin_mm = surface.origin/millimeter;
          row.normal = surface.normal;
        } else if (surface is Cylinder) {
          row["type"] = "cylinder";
          row.radius_mm = surface.radius/millimeter;
          row.axis_origin_mm = surface.coordSystem.origin/millimeter;
          row.axis = surface.coordSystem.zAxis;
        } else if (surface is Sphere) {
          row["type"] = "sphere";
          row.radius_mm = surface.radius/millimeter;
          row.center_mm = surface.center/millimeter;
        } else {
          row["type"] = "other";
        }
        rows = append(rows,row);
      }
      return {"count":size(faces),"offset":''' + str(offset) + ''',"rows":rows};
    }'''
