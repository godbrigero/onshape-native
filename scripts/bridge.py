#!/usr/bin/env python3
"""Run the loopback API without an MCP client."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from onshape_native.bridge import running_bridge

async def main():
    async with running_bridge():
        print("Onshape Native API listening on 127.0.0.1:8766", flush=True)
        await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
