#!/usr/bin/env python3
"""Install the MCP server and modeling skill as a local Claude Code plugin."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from onshape_native.config import runtime_dir
from onshape_native.installation import stage_package, mcp_configuration, require_pairing, write_json

MARKETPLACE = "onshape-native-local"
PLUGIN = "onshape-native@" + MARKETPLACE
MARKER = ".onshape-native-local.json"


def marketplace_manifest():
    return {"name": MARKETPLACE, "owner": {"name": "Local developer"}, "plugins": [{
        "name": "onshape-native", "source": "./plugin",
        "description": "Onshape Native MCP server and modeling skill."
    }]}


def registration_plan(market_root, marketplaces, plugins):
    """Touch only this marketplace/plugin; refuse a same-name source collision."""
    existing = next((m for m in marketplaces if m.get("name") == MARKETPLACE), None)
    if existing:
        source = existing.get("source")
        known_path = existing.get("path") or (source.get("path") if isinstance(source, dict) else None)
        if not known_path and source == "directory": known_path = existing.get("installLocation")
        if not known_path or Path(known_path).resolve() != market_root.resolve():
            raise ValueError(f"Marketplace {MARKETPLACE} already points elsewhere; no registration changed.")
        market_command = ["plugin", "marketplace", "update", MARKETPLACE]
    else:
        market_command = ["plugin", "marketplace", "add", "--scope", "user", str(market_root)]
    installed = next((p for p in plugins if p.get("id") == PLUGIN and p.get("scope") == "user"), None)
    if installed and not installed.get("enabled", True):
        raise ValueError("The existing Claude plugin is disabled. Enable it explicitly before updating.")
    plugin_command = ["plugin", "update" if installed else "install", PLUGIN, "--scope", "user", "--json"]
    return [market_command, plugin_command]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, help="Reuse a configured runtime instead of .runtime/ONSHAPE_NATIVE_RUNTIME.")
    args = parser.parse_args()
    runtime = (args.runtime_dir or runtime_dir()).expanduser().resolve()
    config_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")).expanduser().resolve()
    market_root = config_home / MARKETPLACE
    destination = market_root / "plugin"
    if runtime == market_root or market_root in runtime.parents:
        raise ValueError("Runtime must be outside the distributed Claude marketplace.")
    if ROOT == destination or destination in ROOT.parents:
        raise ValueError("Run this installer from the source checkout, not its installed copy.")
    require_pairing(ROOT, runtime)
    claude, uv = shutil.which("claude"), shutil.which("uv")
    if not claude or not uv:
        raise ValueError("Install Claude Code and uv on PATH, then rerun this installer.")
    if market_root.is_symlink() or (market_root.exists() and not (market_root / MARKER).is_file()):
        raise ValueError(f"Refusing to replace an unmanaged marketplace directory: {market_root}")
    if destination.is_symlink(): raise ValueError("Refusing to replace a symlinked plugin directory.")
    def cli_json(*parts):
        return json.loads(subprocess.run([claude, *parts, "--json"], check=True, capture_output=True, text=True).stdout)
    plan = registration_plan(market_root, cli_json("plugin", "marketplace", "list"), cli_json("plugin", "list"))
    market_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".stage-", dir=market_root) as temporary:
        staged = Path(temporary) / "plugin"
        stage_package(ROOT, staged)
        subprocess.run([uv, "sync", "--project", str(staged), "--frozen", "--no-dev"], check=True,
                       env={**os.environ, "UV_PROJECT_ENVIRONMENT": str(runtime / "claude-venv")})
        write_json(staged / ".mcp.json", mcp_configuration(destination, runtime, "claude-venv"))
        subprocess.run([claude, "plugin", "validate", str(staged), "--strict"], check=True)
        backup = Path(temporary) / "previous"
        if destination.exists(): destination.rename(backup)
        try: staged.rename(destination)
        except BaseException:
            if backup.exists(): backup.rename(destination)
            raise
    (market_root / ".claude-plugin").mkdir(exist_ok=True)
    write_json(market_root / ".claude-plugin/marketplace.json", marketplace_manifest())
    write_json(market_root / MARKER, {"source": str(ROOT), "runtime": str(runtime)})
    for command in plan:
        subprocess.run([claude, *command], check=True)
    print(json.dumps({"plugin": PLUGIN, "source": str(destination), "runtime": str(runtime),
                      "extension": str(ROOT / "extension"),
                      "next": "Restart Claude Code. Check /mcp, then invoke /onshape-native:onshape-native-modeling with an Onshape URL."}, indent=2))


if __name__ == "__main__":
    try: main()
    except (ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from None
