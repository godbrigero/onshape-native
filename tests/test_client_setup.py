import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

from onshape_native.installation import mcp_configuration, require_pairing, venv_python

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_executable_layout_for_windows_and_posix_and_paths_with_spaces(tmp_path):
    environment = tmp_path / "My runtime" / "claude-venv"
    assert venv_python(environment, "nt") == environment / "Scripts/python.exe"
    assert venv_python(environment, "posix") == environment / "bin/python"
    result = mcp_configuration(tmp_path / "My plugin", tmp_path / "My runtime", "claude-venv")
    server = json.loads(json.dumps(result))["mcpServers"]["onshape_native"]
    assert server["args"] == [str(tmp_path / "My plugin/scripts/serve.py")]
    assert server["env"]["ONSHAPE_NATIVE_RUNTIME"] == str(tmp_path / "My runtime")
    assert Path(server["command"]) == venv_python(environment)
    assert server["type"] == "stdio"


def test_configure_is_repeatable_preserves_pairing_and_generates_device_paths(tmp_path, monkeypatch):
    module = script("configure")
    source = tmp_path / "source with spaces"
    runtime = tmp_path / "private runtime"
    (source / "extension").mkdir(parents=True)
    python = venv_python(source / ".venv")
    python.parent.mkdir(parents=True); python.touch()
    monkeypatch.setenv("ONSHAPE_NATIVE_RUNTIME", str(runtime))
    first = module.configure(source)
    token = json.loads((runtime / "bridge.json").read_text())["token"]
    assert module.configure(source) == first
    assert json.loads((runtime / "bridge.json").read_text())["token"] == token
    assert token not in (source / ".mcp.json").read_text()
    assert first["mcpServers"]["onshape_native"]["command"] == str(python)
    require_pairing(source, runtime)
    (source / "extension/local-config.js").write_text('export const BRIDGE_TOKEN = "different-pairing";\n')
    with pytest.raises(ValueError, match="pairing differ"):
        require_pairing(source, runtime)
    assert json.loads((runtime / "bridge.json").read_text())["token"] == token


def test_missing_environment_or_pairing_fails_without_minting_new_token(tmp_path):
    with pytest.raises(ValueError, match="uv sync"):
        script("configure").configure(tmp_path)
    with pytest.raises(ValueError, match="configure"):
        require_pairing(tmp_path, tmp_path / "missing")
    assert not (tmp_path / "missing/bridge.json").exists()


def test_claude_registration_is_additive_and_reruns_update_only_owned_plugin(tmp_path):
    module = script("install_claude")
    root = tmp_path / "my marketplace"
    marketplaces = [{"name": "unrelated", "source": "github", "repo": "example/plugin"}]
    plugins = [{"id": "other@unrelated", "scope": "user", "enabled": True}]
    commands = module.registration_plan(root, marketplaces, plugins)
    assert commands[0] == ["plugin", "marketplace", "add", "--scope", "user", str(root)]
    assert commands[1][1] == "install"
    assert len(marketplaces) == len(plugins) == 1
    marketplaces.append({"name": module.MARKETPLACE, "source": "directory", "path": str(root)})
    plugins.append({"id": module.PLUGIN, "scope": "user", "enabled": True})
    commands = module.registration_plan(root, marketplaces, plugins)
    assert commands == [["plugin", "marketplace", "update", module.MARKETPLACE],
                        ["plugin", "update", module.PLUGIN, "--scope", "user", "--json"]]
    assert all("unrelated" not in " ".join(c) for c in commands)


def test_claude_refuses_marketplace_collision_and_respects_disabled_plugin(tmp_path):
    module = script("install_claude")
    with pytest.raises(ValueError, match="elsewhere"):
        module.registration_plan(tmp_path, [{"name": module.MARKETPLACE, "source": "github"}], [])
    with pytest.raises(ValueError, match="elsewhere"):
        module.registration_plan(tmp_path, [{"name": module.MARKETPLACE, "path": str(tmp_path / "different")}], [])
    with pytest.raises(ValueError, match="disabled"):
        module.registration_plan(tmp_path, [], [{"id": module.PLUGIN, "scope": "user", "enabled": False}])


def test_device_archive_contains_both_plugins_and_no_generated_config_or_secrets(tmp_path):
    path = script("package").build_zip(tmp_path / "device.zip")
    with zipfile.ZipFile(path) as archive:
        names = {name.removeprefix("onshape-native/") for name in archive.namelist()}
        assert {".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "scripts/configure.py",
                "scripts/install_claude.py", "docs/installation.md", "docs/claude-code.md"} <= names
        assert ".mcp.json" not in names and "extension/local-config.js" not in names
        assert not any(set(Path(n).parts) & {".runtime", ".venv", "__pycache__", ".env"} for n in names)
        assert not any(n.endswith((".har", ".pyc")) for n in names)
