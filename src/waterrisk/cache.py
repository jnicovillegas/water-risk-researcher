"""Minimal on-disk cache keyed by a stable hash.

Used for two things:
  1. Research responses (per location) — avoid re-paying for the LLM+search.
  2. Fetched page bodies (per URL) — avoid re-downloading sources shared across
     many locations (e.g. WRI Aqueduct, the same regulation page).

This directly serves the "avoid duplicate searches" bonus and the scalability
story: at 1,000 locations, source reuse makes the cache hit-rate high.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class DiskCache:
    def __init__(self, directory: str, enabled: bool = True):
        self.enabled = enabled
        self.dir = Path(directory)
        if self.enabled:
            self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(namespace: str, value: str) -> str:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
        return f"{namespace}_{digest}"

    def _path(self, namespace: str, value: str) -> Path:
        return self.dir / f"{self._key(namespace, value)}.json"

    def get(self, namespace: str, value: str) -> Any | None:
        if not self.enabled:
            return None
        p = self._path(namespace, value)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, namespace: str, value: str, payload: Any) -> None:
        if not self.enabled:
            return
        p = self._path(namespace, value)
        try:
            p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # cache is best-effort; never fail the run over it
