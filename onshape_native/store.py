"""Private artifact storage and explicitly paginated model-facing output."""
import hashlib
import json
import os
import re
from pathlib import Path
from .client import OnshapeError


def compact(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)

    def put(self, data, suffix="json"):
        raw = compact(data).encode() if suffix == "json" else data
        key = hashlib.sha256(raw).hexdigest()
        path = self.root / f"{key}.{suffix}"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        return {"artifact": key + "." + suffix, "path": str(path.resolve()), "bytes": len(raw)}

    def read(self, artifact):
        if not re.fullmatch(r"[a-f0-9]{64}\.json", artifact):
            raise OnshapeError("Expected a JSON artifact ID returned by this server.")
        path = self.root / artifact
        if not path.is_file():
            raise OnshapeError("Artifact missing; inspect the model again.")
        return json.loads(path.read_text())

    def page(self, value, pointer="", offset=0, limit=20, max_chars=7000):
        if offset < 0 or not 1 <= limit <= 100:
            raise OnshapeError("offset >= 0 and 1 <= limit <= 100 required.")
        if pointer and not pointer.startswith("/"):
            raise OnshapeError("Use an RFC 6901 JSON pointer starting with /.")
        try:
            for segment in pointer.split("/")[1:]:
                key = segment.replace("~1", "/").replace("~0", "~")
                value = value[int(key)] if isinstance(value, list) else value[key]
        except (KeyError, IndexError, TypeError, ValueError):
            raise OnshapeError("JSON pointer does not exist.") from None
        total = len(value) if isinstance(value, (dict, list, str)) else 1
        if isinstance(value, dict):
            items = list(value.items())[offset:offset + limit]
            page = dict(items)
        elif isinstance(value, (list, str)):
            page = value[offset:offset + (max_chars if isinstance(value, str) else limit)]
            if isinstance(page, str):
                low, high = 0, len(page)
                while low < high:
                    mid = (low + high + 1) // 2
                    if len(compact(page[:mid])) <= max_chars:
                        low = mid
                    else:
                        high = mid - 1
                page = page[:low]
        else:
            page = value
        if len(compact(page)) > max_chars:
            return {"needs_narrower_pointer": True, "type": type(value).__name__, "total": total,
                    "keys": list(value)[:40] if isinstance(value, dict) else None,
                    "hint": "Request a child pointer or smaller limit. Data was not truncated."}
        count = len(page) if isinstance(page, (dict, list, str)) else 1
        return {"data": page, "total": total, "next_offset": offset + count if offset + count < total else None}

    def response(self, value, pointer="", offset=0, limit=20):
        if isinstance(value, bytes):
            return self.put(value, "bin")
        return {**self.put(value), **self.page(value, pointer, offset, limit)}
