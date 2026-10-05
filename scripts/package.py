#!/usr/bin/env python3
"""Build a clean source ZIP for installation on another device; never copy pairing."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from onshape_native.installation import stage_package


def build_zip(output):
    output = Path(output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="onshape-native-package-") as temporary:
        staged = Path(temporary) / "onshape-native"
        stage_package(ROOT, staged)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staged.rglob("*")):
                if path.is_file(): archive.write(path, path.relative_to(staged.parent))
    return output


if __name__ == "__main__":
    version = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / f"onshape-native-{version}.zip")
    print(build_zip(parser.parse_args().output))
