import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("native_installer", ROOT / "scripts/install_local.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_public_bundle_is_complete_without_pairing_runtime_or_venv(tmp_path):
    dest = tmp_path / "bundle"
    installer.stage_package(ROOT, dest)
    assert not (dest / ".runtime").exists()
    assert not (dest / ".venv").exists()
    assert not (dest / "extension/local-config.js").exists()
    assert not list(dest.rglob("*.pyc"))
    assert (dest / "extension/tab-context.js").is_file()
    manifest = json.loads((dest / ".codex-plugin/plugin.json").read_text())
    skill = dest / manifest["skills"] / "onshape-native-modeling/SKILL.md"
    assert skill.is_file()
    # Relative references must still work in the independent installed package.
    import re
    for link in re.findall(r"\]\(([^)]+\.md)\)", skill.read_text()):
        assert (skill.parent / link).resolve().is_file(), link
    for data in ("openapi.json", "native-commands.json", "LICENSE-APACHE"):
        assert (dest / "data" / data).is_file()
    runtime = tmp_path / "private runtime"
    config = installer.launcher(dest, runtime)["mcpServers"]["onshape_native"]
    assert config["args"] == [str(dest / "scripts/serve.py")]
    assert config["env"]["ONSHAPE_NATIVE_RUNTIME"] == str(runtime)
    assert "onshape-api" not in json.dumps(config)


def test_marketplace_preserves_other_plugins_and_existing_native_policy():
    previous = {"name": "personal", "interface": {"displayName": "Mine"}, "plugins": [
        {"name": "onshape", "source": {"source": "local", "path": "./plugins/onshape"}},
        {"name": "onshape-native", "source": {"source": "local", "path": "old"}, "policy": {"installation": "AVAILABLE"}, "extra": "keep"}]}
    updated = installer.merge_marketplace(previous, "./plugins/onshape-native")
    assert updated["plugins"][0] == previous["plugins"][0]
    assert updated["plugins"][1]["policy"] == previous["plugins"][1]["policy"]
    assert updated["plugins"][1]["extra"] == "keep"
    assert previous["plugins"][1]["source"]["path"] == "old"
    assert installer.merge_marketplace(updated, "./plugins/onshape-native") == updated
    with pytest.raises(ValueError): installer.merge_marketplace({"name": "other", "plugins": []}, "path")


def test_first_marketplace_install_is_additive():
    previous = {"name": "personal", "plugins": [{"name": "unrelated"}]}
    updated = installer.merge_marketplace(previous, "./plugins/onshape-native")
    assert len(updated["plugins"]) == 2 and len(previous["plugins"]) == 1
    assert updated["plugins"][1]["name"] == "onshape-native"
