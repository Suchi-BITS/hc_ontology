"""Cost tracking and optimization helpers for LLM/agent runs."""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any


# Rough local/Ollama cost model (USD) — configurable for cloud models
DEFAULT_UNIT_COSTS = {
    "llm_call": 0.002,
    "embedding_call": 0.0001,
    "neo4j_query": 0.00005,
    "agent_run": 0.01,
}


@dataclass
class CostEvent:
    tenant_id: str
    kind: str
    units: float
    usd: float
    at: str
    meta: dict[str, Any] = field(default_factory=dict)


class CostTracker:
    def __init__(self, unit_costs: dict[str, float] | None = None) -> None:
        self._lock = threading.Lock()
        self._events: list[CostEvent] = []
        self._by_tenant_day: dict[tuple[str, str], float] = defaultdict(float)
        self.unit_costs = unit_costs or dict(DEFAULT_UNIT_COSTS)

    def record(
        self,
        tenant_id: str,
        kind: str,
        units: float = 1.0,
        meta: dict[str, Any] | None = None,
    ) -> CostEvent:
        usd = self.unit_costs.get(kind, 0.001) * units
        ev = CostEvent(
            tenant_id=tenant_id or "default",
            kind=kind,
            units=units,
            usd=round(usd, 6),
            at=datetime.now(timezone.utc).isoformat(),
            meta=meta or {},
        )
        day = date.today().isoformat()
        with self._lock:
            self._events.append(ev)
            self._by_tenant_day[(ev.tenant_id, day)] += ev.usd
            # Cap memory
            if len(self._events) > 5000:
                self._events = self._events[-3000:]
        return ev

    def day_spend(self, tenant_id: str, day: str | None = None) -> float:
        day = day or date.today().isoformat()
        with self._lock:
            return round(self._by_tenant_day.get((tenant_id, day), 0.0), 6)

    def within_budget(self, tenant_id: str, budget_usd: float) -> bool:
        return self.day_spend(tenant_id) < budget_usd

    def summary(self, tenant_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            events = list(self._events)
        if tenant_id:
            events = [e for e in events if e.tenant_id == tenant_id]
        by_kind: dict[str, float] = defaultdict(float)
        for e in events:
            by_kind[e.kind] += e.usd
        return {
            "event_count": len(events),
            "total_usd": round(sum(e.usd for e in events), 6),
            "by_kind_usd": {k: round(v, 6) for k, v in by_kind.items()},
            "today_usd": self.day_spend(tenant_id or "default"),
        }


cost_tracker = CostTracker()


def should_use_cache(question: str) -> bool:
    """Cheap heuristic: prefer cache for short factual lookups."""
    q = question.strip().lower()
    return len(q) < 120 or q.startswith(("what is", "define", "list"))
