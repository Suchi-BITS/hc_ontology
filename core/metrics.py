"""In-memory metrics for query validation / LLM pipeline."""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timezone


class MetricsStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._started = datetime.now(timezone.utc).isoformat()

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "started_at": self._started,
                "counters": dict(self._counters),
            }


metrics = MetricsStore()
