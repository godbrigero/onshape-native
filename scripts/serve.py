#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from onshape_native.server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
