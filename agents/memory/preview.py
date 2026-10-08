"""Run memory assembly + semantic enrichment for terminal debug (no agent graph)."""

from __future__ import annotations

from typing import Any

from agents.memory.debug_context import (
    log_memory_phase,
    memory_debug_enabled,
    snapshot_from_state,
    snapshot_query_grounding,
)
from agents.memory.orchestrator import get_memory_orchestrator
from agents.memory.working import compact_working_context
from core.config import get_settings


def run_memory_debug_preview(
    question: str,
    *,
    session_id: str = "",
    tenant_id: str = "default",
    source: str = "preview",
) -> dict[str, Any]:
    """Assemble + enrich memory and print debug blocks when MEMORY_DEBUG_CONTEXT=true."""
    if not memory_debug_enabled():
        return {}

    settings = get_settings()
    orch = get_memory_orchestrator()

    log_memory_phase(
        f"{source} (start)",
        question=question,
        before={"session_id": session_id, "tenant_id": tenant_id, "source": source},
    )

    assembled = orch.assemble_context(
        question=question,
        session_id=session_id,
        tenant_id=tenant_id,
        query_type="cypher",
        include_semantic=False,
    )

    state: dict[str, Any] = {
        "question": question,
        "session_id": session_id,
        "tenant_id": tenant_id,
        "ontology_id": "hc-core",
        "query_type": "cypher",
        **assembled,
    }

    enriched = orch.enrich_semantic(state)
    merged = {**state, **enriched}

    max_chars = int(settings.get("working_memory_max_chars", 6000))
    meta = merged.get("meta_memory") or {}
    if meta.get("max_chars"):
        max_chars = int(meta["max_chars"])
    grounded = compact_working_context(
        question=question,
        memory_bundle=merged.get("memory_bundle"),
        ontology_context=merged.get("ontology_context") or "",
        max_chars=max_chars,
    )

    log_memory_phase(
        f"{source} (grounded_context)",
        question=question,
        after=snapshot_query_grounding(merged, grounded=grounded, procedure_reused=False),
    )

    log_memory_phase(
        f"{source} (complete)",
        question=question,
        after=snapshot_from_state(merged),
    )

    return merged
