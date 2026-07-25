"""Simple in-process rate limiter for expensive LLM endpoints."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request


class SlidingWindowRateLimiter:
    def __init__(self, max_calls: int, window_seconds: float):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> None:
        if self.max_calls <= 0:
            return
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window_seconds:
                q.popleft()
            if len(q) >= self.max_calls:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded: max {self.max_calls} "
                        f"requests per {int(self.window_seconds)}s"
                    ),
                )
            q.append(now)


def client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"
