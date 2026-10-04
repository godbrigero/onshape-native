"""Local bridge settings. Onshape session credentials never leave the browser."""
import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def runtime_dir():
    return Path(os.environ.get("ONSHAPE_NATIVE_RUNTIME", ROOT / ".runtime")).expanduser()


def load_config():
    root = runtime_dir()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    path = root / "bridge.json"
    if not path.exists():
        data = {"host": "127.0.0.1", "port": 8766, "token": secrets.token_urlsafe(32)}
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as stream:
                json.dump(data, stream, indent=2)
    data = json.loads(path.read_text())
    if data.get("host") != "127.0.0.1" or data.get("port") != 8766:
        raise ValueError("This extension is paired with 127.0.0.1:8766.")
    if not isinstance(data.get("token"), str) or len(data["token"]) < 32:
        raise ValueError("Bridge token must contain at least 32 characters.")
    path.chmod(0o600)
    return data
