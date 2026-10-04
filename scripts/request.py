#!/usr/bin/env python3
"""Authenticated HTTP CLI: JSON body from a file or stdin, never shell interpolation."""
import argparse
import json
from pathlib import Path
import sys
import urllib.request
import urllib.error
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from onshape_native.config import load_config

p = argparse.ArgumentParser()
p.add_argument("method", choices=["GET", "POST", "PUT", "PATCH", "DELETE"])
p.add_argument("path")
p.add_argument("--body", help="JSON file, or - for stdin")
a = p.parse_args()
if not a.path.startswith("/") or a.path.startswith("//"):
    p.error("Use a local absolute path such as /health or /command")
config = load_config()
body = None
if a.body:
    body = json.dumps(json.loads(sys.stdin.read() if a.body == "-" else Path(a.body).read_text())).encode()
req = urllib.request.Request(f"http://127.0.0.1:{config['port']}" + a.path, data=body, method=a.method,
    headers={"Authorization": "Bearer " + config["token"], "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=110) as response:
        print(response.read().decode())
except urllib.error.HTTPError as error:
    print(error.read().decode(), file=sys.stderr)
    sys.exit(1)
