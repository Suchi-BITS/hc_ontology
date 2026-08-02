"""Monitoring, alerting thresholds, and Prometheus-style metrics export."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.metrics import metrics
from enterprise.cost import cost_tracker


@dataclass
class Alert:
    name: str
    severity: str
    message: str
    at: str


class Monitor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latencies: deque[float] = deque(maxlen=500)
        self._errors: deque[str] = deque(maxlen=200)
        self._alerts: list[Alert] = []
        self._counters: dict[str, int] = defaultdict(int)
        self.error_rate_threshold = 0.25
        self.latency_p95_threshold_ms = 120_000

    def record_latency(self, ms: float) -> None:
        with self._lock:
            self._latencies.append(ms)
            self._counters["requests"] += 1

    def record_error(self, message: str) -> None:
        with self._lock:
            self._errors.append(message)
            self._counters["errors"] += 1
            self._maybe_alert_unlocked()

    def incr(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._counters[name] += n

    def _p95_unlocked(self) -> float:
        if not self._latencies:
            return 0.0
        vals = sorted(self._latencies)
        idx = max(0, int(0.95 * (len(vals) - 1)))
        return vals[idx]

    def _maybe_alert_unlocked(self) -> None:
        req = self._counters["requests"] or 1
        err = self._counters["errors"]
        rate = err / req
        now = datetime.now(timezone.utc).isoformat()
        if rate >= self.error_rate_threshold:
            self._alerts.append(
                Alert(
                    name="high_error_rate",
                    severity="warning",
                    message=f"Error rate {rate:.2%} exceeds threshold",
                    at=now,
                )
            )
        p95 = self._p95_unlocked()
        if p95 >= self.latency_p95_threshold_ms:
            self._alerts.append(
                Alert(
                    name="high_latency",
                    severity="warning",
                    message=f"p95 latency {p95:.0f}ms exceeds threshold",
                    at=now,
                )
            )
        # Cap alerts
        if len(self._alerts) > 100:
            self._alerts = self._alerts[-50:]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            p95 = self._p95_unlocked()
            alerts = [
                {"name": a.name, "severity": a.severity, "message": a.message, "at": a.at}
                for a in self._alerts[-20:]
            ]
            counters = dict(self._counters)
        return {
            "counters": counters,
            "latency_p95_ms": round(p95, 2),
            "alerts": alerts,
            "pipeline_metrics": metrics.snapshot(),
            "cost": cost_tracker.summary(),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def prometheus_text(self) -> str:
        snap = self.snapshot()
        lines = [
            "# HELP hc_agent_requests_total Total agent/API monitored requests",
            "# TYPE hc_agent_requests_total counter",
            f'hc_agent_requests_total {snap["counters"].get("requests", 0)}',
            "# HELP hc_agent_errors_total Total monitored errors",
            "# TYPE hc_agent_errors_total counter",
            f'hc_agent_errors_total {snap["counters"].get("errors", 0)}',
            "# HELP hc_agent_latency_p95_ms Approximate p95 latency",
            "# TYPE hc_agent_latency_p95_ms gauge",
            f'hc_agent_latency_p95_ms {snap["latency_p95_ms"]}',
            "# HELP hc_agent_cost_usd_total Estimated cumulative cost USD",
            "# TYPE hc_agent_cost_usd_total counter",
            f'hc_agent_cost_usd_total {snap["cost"].get("total_usd", 0)}',
        ]
        for k, v in (snap.get("pipeline_metrics") or {}).get("counters", {}).items():
            safe = k.replace(".", "_").replace("-", "_")
            lines.append(f'hc_pipeline_{safe} {int(v)}')
        return "\n".join(lines) + "\n"


monitor = Monitor()


def timed_call(fn, *args, **kwargs):
    start = time.perf_counter()
    try:
        return fn(*args, **kwargs)
    finally:
        monitor.record_latency((time.perf_counter() - start) * 1000)
