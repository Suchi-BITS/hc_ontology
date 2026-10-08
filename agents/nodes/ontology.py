"""Ontology Agent — semantic memory enrichment via hybrid retrieval."""

from __future__ import annotations

import logging
from typing import Any

from agents.memory import get_memory_orchestrator
from agents.state import AgentState
from enterprise.cost import cost_tracker
from enterprise.observability import trace_span

logger = logging.getLogger("healthcare_ontology.agent")


def ontology_node(state: AgentState) -> dict[str, Any]:
    question = state.get("question") or ""
    tenant_id = state.get("tenant_id") or "default"
    trace = list(state.get("trace") or [])
    errors = list(state.get("errors") or [])
    trace.append("ontology:start")

    orchestrator = get_memory_orchestrator()
    enriched: dict[str, Any] = {}
    with trace_span("ontology.semantic_memory", {"tenant_id": tenant_id}):
        try:
            enriched = orchestrator.enrich_semantic(state)
            cost_tracker.record(tenant_id, "embedding_call", units=1, meta={"node": "ontology"})
        except Exception as exc:
            errors.append(f"semantic_memory: {exc}")
            logger.warning("Semantic memory enrichment failed: %s", exc)
            enriched = {
                "ontology_context": state.get("ontology_context") or "",
                "retrieved_concepts": state.get("retrieved_concepts") or [],
                "hybrid_meta": state.get("hybrid_meta") or {},
                "retrieval_meta": state.get("retrieval_meta") or {},
                "working_context": state.get("working_context") or state.get("memory_context") or "",
                "memory_context": state.get("memory_context") or "",
                "memory_bundle": state.get("memory_bundle") or {},
                "working_events": state.get("working_events") or [],
            }

    retrieved = enriched.get("retrieved_concepts") or []
    retrieval_meta = enriched.get("retrieval_meta") or {}
    trace.append(f"ontology:semantic={len(retrieved)}")
    if retrieval_meta.get("error_budget"):
        eb = retrieval_meta["error_budget"]
        trace.append(
            f"ontology:error_budget:top={eb.get('top_rerank_score')}:"
            f"residual={eb.get('residual_retrieval_risk')}"
        )

    return {
        "ontology_context": enriched.get("ontology_context") or "",
        "retrieved_concepts": retrieved,
        "hybrid_meta": enriched.get("hybrid_meta") or {},
        "retrieval_meta": retrieval_meta,
        "memory_bundle": enriched.get("memory_bundle") or state.get("memory_bundle") or {},
        "working_context": enriched.get("working_context") or "",
        "memory_context": enriched.get("memory_context") or enriched.get("working_context") or "",
        "working_events": enriched.get("working_events") or state.get("working_events") or [],
        "status": "retrieving",
        "errors": errors,
        "trace": trace,
    }
