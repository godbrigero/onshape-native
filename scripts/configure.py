#!/usr/bin/env python3
"""Generate local pairing material and an independent MCP launcher."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from onshape_native.config import load_config, runtime_dir

config = load_config()
local = ROOT / "extension/local-config.js"
fd = os.open(local, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as stream:
    stream.write("// Local pairing material; excluded from source control and distribution.\n")
    stream.write("export const BRIDGE_TOKEN = " + json.dumps(config["token"]) + ";\n")
local.chmod(0o600)
(ROOT / ".mcp.json").write_text(json.dumps({"mcpServers": {"onshape_native": {
    "command": str(ROOT / ".venv/bin/python"), "args": [str(ROOT / "scripts/serve.py")],
    "env": {"ONSHAPE_NATIVE_RUNTIME": str(runtime_dir().resolve())}
}}}, indent=2) + "\n")
print("Configured onshape-native. Pairing stays local; no Onshape credentials needed.")
