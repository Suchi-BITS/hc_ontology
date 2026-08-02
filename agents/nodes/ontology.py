"""Ontology Agent — hybrid graph+vector retrieval + KG memory context."""

from __future__ import annotations

import logging
from typing import Any

from agents.memory import get_agent_memory
from agents.state import AgentState
from core.dependencies import get_ontology
from enterprise.cost import cost_tracker
from enterprise.hybrid_retrieval import hybrid_retrieve
from enterprise.observability import trace_span

logger = logging.getLogger("healthcare_ontology.agent")


def ontology_node(state: AgentState) -> dict[str, Any]:
    question = state.get("question") or ""
    session_id = state.get("session_id") or ""
    tenant_id = state.get("tenant_id") or "default"
    trace = list(state.get("trace") or [])
    errors = list(state.get("errors") or [])
    trace.append("ontology:start")

    memory_context = state.get("memory_context") or ""
    if session_id and not memory_context:
        try:
            memory_context = get_agent_memory().load_context(session_id)
        except Exception as exc:
            errors.append(f"memory_load: {exc}")
            logger.warning("Memory load failed: %s", exc)

    retrieved: list[dict[str, Any]] = []
    hybrid_meta: dict[str, Any] = {}
    with trace_span("ontology.hybrid_retrieve", {"tenant_id": tenant_id}):
        try:
            hybrid = hybrid_retrieve(question, top_k=8)
            retrieved = hybrid.get("results") or []
            hybrid_meta = {
                "vector_count": hybrid.get("vector_count"),
                "graph_count": hybrid.get("graph_count"),
            }
            cost_tracker.record(tenant_id, "embedding_call", units=1, meta={"node": "ontology"})
        except Exception as exc:
            errors.append(f"hybrid_retrieve: {exc}")
            logger.warning("Hybrid retrieval failed: %s", exc)

    try:
        onto = get_ontology()
        classes = onto.get_classes()[:40]
        obj_props = onto.get_object_properties()[:40]
        data_props = onto.get_data_properties()[:40]
    except Exception as exc:
        classes, obj_props, data_props = [], [], []
        errors.append(f"schema: {exc}")

    ontology_id = state.get("ontology_id") or "hc-core"
    ontology_version = state.get("ontology_version") or ""
    concept_lines = []
    for item in retrieved[:8]:
        if isinstance(item, dict):
            name = item.get("name") or ""
            score = item.get("rrf_score") or item.get("score")
            src = item.get("source") or ""
            desc = item.get("description") or ""
            line = f"- {name}"
            if score is not None:
                line += f" (score={score}"
                if src:
                    line += f", src={src}"
                line += ")"
            if desc:
                line += f": {str(desc)[:160]}"
            concept_lines.append(line)
        else:
            concept_lines.append(f"- {item}")

    ontology_context = "\n".join(
        [
            f"Ontology: {ontology_id} version={ontology_version or 'active'}",
            "Relevant concepts (hybrid graph+vector):",
            *(concept_lines or ["- (none retrieved)"]),
            "",
            "Schema excerpt — classes:",
            ", ".join(classes) if classes else "(unavailable)",
            "Object properties:",
            ", ".join(obj_props) if obj_props else "(unavailable)",
            "Data properties:",
            ", ".join(data_props) if data_props else "(unavailable)",
        ]
    )

    trace.append(f"ontology:hybrid={len(retrieved)}")
    return {
        "ontology_context": ontology_context,
        "retrieved_concepts": retrieved,
        "hybrid_meta": hybrid_meta,
        "memory_context": memory_context,
        "status": "retrieving",
        "errors": errors,
        "trace": trace,
    }
