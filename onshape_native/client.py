"""Browser-session transport. No Onshape keys, cookies, or HMAC in this package."""
from dataclasses import dataclass, field
from pathlib import Path
import base64

import httpx

from .config import load_config, runtime_dir


class OnshapeError(Exception):
    pass


@dataclass
class Settings:
    base_url: str = "https://cad.onshape.com"
    cache_dir: Path = field(default_factory=lambda: runtime_dir() / "artifacts")

    @classmethod
    def load(cls):
        return cls()


class Client:
    def __init__(self, settings=None, transport=None):
        self.settings = settings or Settings.load()
        config = load_config()
        self.http = httpx.AsyncClient(base_url=f"http://127.0.0.1:{config['port']}",
                                      headers={"Authorization": "Bearer " + config["token"]},
                                      timeout=110, follow_redirects=False, trust_env=False, transport=transport)
        self.calls = 0
        self.rate = {}

    async def close(self):
        await self.http.aclose()

    async def command(self, job):
        try:
            response = await self.http.post("/command", json=job)
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise OnshapeError("Local bridge unavailable or command outcome unknown. Inspect state before retrying.") from None
        if not isinstance(data, dict):
            raise OnshapeError("Page returned no structured result; outcome unknown. Inspect state before retrying.")
        if response.status_code != 200 or data.get("error"):
            raise OnshapeError(data.get("error", "Bridge rejected the command."))
        return data

    async def status(self):
        try:
            response = await self.http.get("/health")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError:
            return {"bridge_connected": False, "extension_connected": False}

    async def request(self, method, path, query=None, body=None, *, read_only=False):
        self.calls += 1
        data = await self.command({"kind": "rest", "method": method, "path": path,
                                   "query": query or {}, "body": body})
        status = data.get("status", 0)
        if not 200 <= status < 300:
            raise OnshapeError(f"Onshape browser HTTP {status}. Inspect state before retrying writes.")
        if data.get("encoding") == "base64":
            return base64.b64decode(data["body"])
        return data.get("body", {})
