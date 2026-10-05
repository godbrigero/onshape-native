#!/usr/bin/env python3
"""Generate local pairing material and an independent MCP launcher."""
import json
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from onshape_native.config import load_config, runtime_dir
from onshape_native.installation import venv_python, write_json


def configure(root=ROOT, runtime=None):
    root = Path(root).resolve()
    python = venv_python(root / ".venv")
    if not python.is_file():
        raise ValueError("Run uv sync --frozen in the onshape-native directory first.")
    if runtime is not None:
        os.environ["ONSHAPE_NATIVE_RUNTIME"] = str(Path(runtime).expanduser().resolve())
    config = load_config()
    local = root / "extension/local-config.js"
    fd = os.open(local, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write("// Local pairing material; excluded from source control and distribution.\n")
        stream.write("export const BRIDGE_TOKEN = " + json.dumps(config["token"]) + ";\n")
    local.chmod(0o600)
    result = {"mcpServers": {"onshape_native": {
        "type": "stdio", "command": str(python), "args": [str(root / "scripts/serve.py")],
        "env": {"ONSHAPE_NATIVE_RUNTIME": str(runtime_dir().resolve())}
    }}}
    write_json(root / ".mcp.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, help="Private pairing/artifact directory; defaults to .runtime or ONSHAPE_NATIVE_RUNTIME.")
    args = parser.parse_args()
    try:
        configure(runtime=args.runtime_dir)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    print("Configured onshape-native for this device. Pairing stays local; no Onshape credentials needed.")
