#!/usr/bin/env python3
"""Render the original SVG mark to the exact PNG sizes used by both manifests.

Requires rsvg-convert (librsvg). Generated PNGs are checked in; runtime and
installation do not need a renderer. No remote assets or model calls are used.
"""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    renderer = shutil.which("rsvg-convert")
    if not renderer:
        raise SystemExit("Install librsvg to rebuild icons; the checked-in PNGs are ready to use.")
    source = ROOT / "assets/onshape-native.svg"
    outputs = [(ROOT / "extension/icons" / f"icon-{size}.png", size)
               for size in (16, 24, 32, 48, 64, 128)]
    outputs += [(ROOT / "assets/composer-icon.png", 128), (ROOT / "assets/logo.png", 512)]
    skill_assets = ROOT / "skills/onshape-native-modeling/assets"
    outputs += [(skill_assets / "icon.png", 128), (skill_assets / "logo.png", 512)]
    for path, size in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([renderer, "--width", str(size), "--height", str(size),
                        "--output", str(path), str(source)], check=True)
    print(f"Rendered {len(outputs)} icons from assets/onshape-native.svg.")


if __name__ == "__main__":
    main()
