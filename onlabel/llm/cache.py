"""Committed, content-addressed cache of LLM responses (the mandate-retry-sequencer pattern).

Each response is stored under sha256(model | prompt version | schema | system | user) and
committed, so a clone with no API keys replays every eval run and reproduces the
reported numbers. The prompt version is part of the key: editing a prompt invalidates its
old entries instead of silently replaying answers to a different question. A damaged
entry is a miss, never a crash.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

DEFAULT_DIR = Path("cache/llm")


def cache_key(model_key: str, prompt_version: str, schema_name: str, system: str, user: str) -> str:
    material = json.dumps([model_key, prompt_version, schema_name, system, user], separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, directory: Path | str = DEFAULT_DIR) -> None:
        self.directory = Path(directory)
        self.hits = self.misses = self.writes = 0

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict | None:
        path = self._path(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            response = payload["response"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
            self.misses += 1
            return None
        self.hits += 1
        return {"response": response, "usage": payload.get("usage", {}), "model_key": payload.get("model_key")}

    def put(self, key: str, *, model_key: str, prompt_version: str, schema_name: str,
            response: dict, usage: dict) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"key": key, "model_key": model_key, "prompt_version": prompt_version,
                   "schema": schema_name, "response": response, "usage": usage}
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, indent=1, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
        self.writes += 1
