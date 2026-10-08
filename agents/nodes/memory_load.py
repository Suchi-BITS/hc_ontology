"""Memory load node — assemble episodic + procedural context before planning."""

from __future__ import annotations

import logging
from typing import Any

from agents.memory import get_memory_orchestrator
from agents.state import AgentState
from enterprise.observability import trace_span

logger = logging.getLogger("healthcare_ontology.agent")


def memory_load_node(state: AgentState) -> dict[str, Any]:
    trace = list(state.get("trace") or [])
    errors = list(state.get("errors") or [])
    trace.append("memory_load:start")

    orchestrator = get_memory_orchestrator()
    question = state.get("question") or ""
    session_id = state.get("session_id") or ""
    tenant_id = state.get("tenant_id") or "default"
    user_id = state.get("user_id") or ""
    query_type = state.get("query_type")

    with trace_span("memory.assemble", {"tenant_id": tenant_id, "session_id": session_id}):
        try:
            assembled = orchestrator.assemble_context(
                question=question,
                session_id=session_id,
                tenant_id=tenant_id,
                user_id=user_id,
                query_type=query_type,
                include_semantic=False,
            )
        except Exception as exc:
            logger.warning("Memory assemble failed: %s", exc)
            errors.append(f"memory_assemble: {exc}")
            assembled = {
                "memory_bundle": {},
                "memory_context": "",
                "working_context": "",
                "working_events": [],
                "matched_procedures": [],
                "meta_memory": {},
            }

    procedures = assembled.get("matched_procedures") or []
    trace.append(
        f"memory_load:procedures={len(procedures)}:"
        f"episodic={bool((assembled.get('memory_bundle') or {}).get('episodic', {}).get('recent_text'))}:"
        f"meta_recall={((assembled.get('meta_memory') or {}).get('recall_confidence'))}"
    )

    updates: dict[str, Any] = {
        "memory_bundle": assembled.get("memory_bundle") or {},
        "memory_context": assembled.get("memory_context") or "",
        "working_context": assembled.get("working_context") or "",
        "working_events": assembled.get("working_events") or [],
        "matched_procedures": procedures,
        "meta_memory": assembled.get("meta_memory") or {},
        "status": "pending",
        "errors": errors,
        "trace": trace,
    }

    # High-confidence procedure can seed query type and plan before planner runs
    if procedures and not state.get("query_type"):
        top = procedures[0]
        if float(top.get("match_score") or 0) >= 0.85 and top.get("query_type"):
            updates["query_type"] = top["query_type"]
            if top.get("plan_steps"):
                updates["plan"] = top["plan_steps"]
            trace.append("memory_load:procedure_seed")

    return updates
