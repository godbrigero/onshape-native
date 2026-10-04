import json
from pathlib import Path
import re

from onshape_native.catalog import Catalog
from onshape_native.native_catalog import catalog


def test_every_bundled_official_operation_is_discoverable_and_resolves():
    c = Catalog()
    assert len(c.ops) == 302
    for name, (method, path, spec) in c.ops.items():
        params = {key: "id" for key in re.findall(r"\{(\w+)\}", path)}
        for key in ("wvm", "wv", "vm"):
            if key in params: params[key] = "w" if key != "vm" else "m"
        query = {item["name"]: "value" for item in spec.get("parameters", []) if item.get("in") == "query" and item.get("required")}
        actual_method, endpoint = c.resolve(name, params, query)
        assert actual_method == method and endpoint.startswith("/api/v17/")
        assert c.search(name)["matches"][0]["operation"] == name


def test_native_schema_includes_assemblies_materials_and_features():
    rows = catalog()
    assert len(rows) >= 480
    names = " ".join(r["command"] for r in rows).lower()
    for word in ("assembly", "material", "feature", "sketch", "mass"):
        assert word in names


def test_packages_have_no_sibling_imports_or_runtime_paths():
    root = Path(__file__).resolve().parents[1]
    for path in (root / "onshape_native").glob("*.py"):
        source = path.read_text()
        assert "onshape-api" not in source and "from onshape_mcp" not in source


def test_all_multipart_operations_remain_in_the_catalog():
    c = Catalog()
    multipart = {name for name in c.ops if "multipart/form-data" in (c.schema(name).get("requestBody") or {}).get("content", {})}
    assert multipart == {"uploadBlobSubelement", "uploadFileCreateElement", "uploadFileUpdateElement", "addAttachment", "updateLibrary", "createTranslation"}
