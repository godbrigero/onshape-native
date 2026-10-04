#!/usr/bin/env python3
"""Install a clean, independent personal Codex plugin; keep pairing outside it."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NAME = "onshape-native"
MARKER = ".onshape-native-install.json"
PUBLIC = (".codex-plugin", "onshape_native", "scripts", "skills", "docs", "data", "assets",
          "extension", "pyproject.toml", "uv.lock", "README.md")


def stage_package(source: Path, destination: Path):
    """Allowlist distributable roots and omit generated pairing and bytecode."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "local-config.js", ".env", "*.har")
    destination.mkdir(parents=True, exist_ok=True)
    for name in PUBLIC:
        src, dst = source / name, destination / name
        if src.is_dir(): shutil.copytree(src, dst, ignore=ignore)
        else: shutil.copy2(src, dst)


def merge_marketplace(existing: dict, relative_source: str):
    result = deepcopy(existing)
    if result.get("name") != "personal" or not isinstance(result.get("plugins"), list):
        raise ValueError("Expected the personal marketplace with a plugins list; no changes made.")
    matches = [i for i, entry in enumerate(result["plugins"]) if entry.get("name") == NAME]
    if len(matches) > 1:
        raise ValueError("Duplicate onshape-native marketplace entries; resolve them before installing.")
    entry = result["plugins"][matches[0]] if matches else {
        "name": NAME, "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Productivity"}
    entry["source"] = {"source": "local", "path": relative_source}
    if not matches: result["plugins"].append(entry)
    return result


def launcher(destination: Path, runtime: Path):
    return {"mcpServers": {"onshape_native": {
        "command": str(runtime / "plugin-venv/bin/python"),
        "args": [str(destination / "scripts/serve.py")],
        "env": {"ONSHAPE_NATIVE_RUNTIME": str(runtime)},
    }}}


def write_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, help="Reuse this private bridge runtime (defaults to existing pairing).")
    args = parser.parse_args()
    home = Path.home()
    destination = home / "plugins" / NAME
    market = home / ".agents/plugins/marketplace.json"
    sys.path.insert(0, str(ROOT))
    from onshape_native.config import load_config, runtime_dir
    runtime = (args.runtime_dir or runtime_dir()).expanduser().resolve()
    if runtime == destination or destination in runtime.parents:
        raise SystemExit("Runtime must be outside the distributed plugin directory.")
    if ROOT == destination or destination in ROOT.parents:
        raise SystemExit("Run the installer from the source checkout, not its installed copy.")
    os.environ["ONSHAPE_NATIVE_RUNTIME"] = str(runtime)
    # Validate before any replacement. Preserve the extension's existing token.
    config = load_config()
    pairing = ROOT / "extension/local-config.js"
    if not pairing.exists():
        raise SystemExit("Run scripts/configure.py with this runtime and load the extension before installing.")
    match = re.search(r'^export const BRIDGE_TOKEN = ("[^"\n]+");$', pairing.read_text(), re.MULTILINE)
    if not match or not secrets.compare_digest(json.loads(match[1]), config["token"]):
        raise SystemExit("This runtime does not match the configured extension. Select its existing runtime or rerun configure.py with the intended runtime.")
    uv, codex = shutil.which("uv"), shutil.which("codex")
    if not uv or not codex:
        raise SystemExit("Install uv and the Codex CLI, then run this installer again.")
    if destination.is_symlink() or (destination.exists() and not (destination / MARKER).is_file()):
        raise SystemExit(f"Refusing to replace an unmanaged destination: {destination}")
    previous = json.loads(market.read_text()) if market.exists() else {
        "name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}
    updated = merge_marketplace(previous, "./plugins/" + NAME)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # uv creates its environment outside the bundle so Codex caches only source.
    with tempfile.TemporaryDirectory(prefix=".onshape-native-stage-", dir=destination.parent) as temporary:
        staged = Path(temporary) / NAME
        stage_package(ROOT, staged)
        subprocess.run([uv, "sync", "--project", str(staged), "--frozen", "--no-dev"],
                       env={**os.environ, "UV_PROJECT_ENVIRONMENT": str(runtime / "plugin-venv")}, check=True)
        write_json(staged / ".mcp.json", launcher(destination, runtime))
        write_json(staged / MARKER, {"source": str(ROOT), "runtime": str(runtime)})
        backup = Path(temporary) / "previous"
        if destination.exists(): destination.rename(backup)
        try: staged.rename(destination)
        except BaseException:
            if backup.exists(): backup.rename(destination)
            raise
    market.parent.mkdir(parents=True, exist_ok=True)
    if market.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        shutil.copy2(market, market.with_name(f"marketplace.before-onshape-native-{stamp}.json"))
    fd, pending = tempfile.mkstemp(prefix=".marketplace-", suffix=".json", dir=market.parent)
    try:
        with os.fdopen(fd, "w") as stream: stream.write(json.dumps(updated, indent=2) + "\n")
        os.replace(pending, market)
    finally:
        if os.path.exists(pending): os.unlink(pending)
    subprocess.run([codex, "plugin", "add", NAME + "@personal", "--json"], check=True)
    print(json.dumps({"plugin": NAME + "@personal", "source": str(destination),
                      "skill": "onshape-native-modeling", "mcp_server": "onshape_native",
                      "runtime": str(runtime), "extension": str(ROOT / "extension"),
                      "next": "Start a new Codex task to load the plugin's skill and MCP tools."}, indent=2))


if __name__ == "__main__":
    main()
