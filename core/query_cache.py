"""TTL cache for NL → query results (demo / repeated questions)."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: float = 300.0, max_entries: int = 256):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def make_key(*parts: str) -> str:
        raw = "|".join(parts).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def get(self, key: str) -> Any | None:
        if self.ttl_seconds <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            expires, value = item
            if now > expires:
                del self._data[key]
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        if self.ttl_seconds <= 0:
            return
        now = time.monotonic()
        with self._lock:
            if len(self._data) >= self.max_entries:
                # drop oldest
                oldest = min(self._data.items(), key=lambda kv: kv[1][0])[0]
                del self._data[oldest]
            self._data[key] = (now + self.ttl_seconds, value)


query_cache = TTLCache()
