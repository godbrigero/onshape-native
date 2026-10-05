"""Shared local packaging; executable paths and pairing are generated per device."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import shutil

PUBLIC = (".codex-plugin", ".claude-plugin", "onshape_native", "scripts", "skills",
          "docs", "data", "assets", "extension", "pyproject.toml", "uv.lock", "README.md")


def venv_python(directory, platform=None):
    return Path(directory) / ("Scripts/python.exe" if (platform or os.name) == "nt" else "bin/python")


def mcp_configuration(destination, runtime, environment="plugin-venv"):
    return {"mcpServers": {"onshape_native": {
        "type": "stdio",
        "command": str(venv_python(Path(runtime) / environment)),
        "args": [str(Path(destination) / "scripts/serve.py")],
        "env": {"ONSHAPE_NATIVE_RUNTIME": str(runtime)},
    }}}


def stage_package(source, destination):
    """Only package source/assets; never cache pairing, credentials, or a venv."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "local-config.js", ".env", "*.har")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name in PUBLIC:
        src, dst = Path(source) / name, destination / name
        if src.is_dir(): shutil.copytree(src, dst, ignore=ignore)
        else: shutil.copy2(src, dst)


def require_pairing(source, runtime):
    """Validate the intended pairing without creating a second token or printing it."""
    from .config import load_config
    runtime = Path(runtime)
    if not (runtime / "bridge.json").is_file():
        raise ValueError("Run scripts/configure.py with this runtime before installing.")
    os.environ["ONSHAPE_NATIVE_RUNTIME"] = str(runtime)
    config = load_config()
    pairing = Path(source) / "extension/local-config.js"
    if not pairing.is_file():
        raise ValueError("Run scripts/configure.py and load its extension folder before installing.")
    match = re.search(r'^export const BRIDGE_TOKEN = ("[^"\n]+");$', pairing.read_text(), re.MULTILINE)
    if not match or not secrets.compare_digest(json.loads(match[1]), config["token"]):
        raise ValueError("Runtime and extension pairing differ. Select the existing runtime or rerun configure.py with the intended runtime.")


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
