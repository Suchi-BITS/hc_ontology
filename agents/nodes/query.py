"""Query Agent — NL → Cypher / SPARQL with ontology grounding + repair."""

from __future__ import annotations

import logging
from typing import Any

from agents.memory.debug_context import log_memory_phase, snapshot_query_grounding
from agents.memory.working import compact_working_context
from agents.state import AgentState
from core.config import get_settings
from core.dependencies import get_cypher_generator, get_sparql_generator

logger = logging.getLogger("healthcare_ontology.agent")


def _grounded_question(state: AgentState) -> str:
    settings = get_settings()
    max_chars = int(settings.get("working_memory_max_chars", 6000))
    working = compact_working_context(
        question=state.get("question") or "",
        memory_bundle=state.get("memory_bundle"),
        ontology_context=state.get("ontology_context") or "",
        validation_error=state.get("validation_error"),
        draft_query=state.get("draft_query") or "",
        max_chars=max_chars,
    )
    if working:
        return working
    parts = [state.get("question") or ""]
    ctx = state.get("ontology_context") or ""
    if ctx:
        parts.append("\n\nOntology grounding:\n" + ctx[:2500])
    return "\n".join(parts)


def _procedure_template(state: AgentState) -> str | None:
    """Use a high-confidence matched procedure as the query draft."""
    procedures = state.get("matched_procedures") or []
    if not procedures or state.get("validation_error"):
        return None
    top = procedures[0]
    if float(top.get("match_score") or 0) < 0.85:
        return None
    template = (top.get("template_query") or "").strip()
    if not template:
        return None
    qtype = state.get("query_type") or "cypher"
    if top.get("query_type") and top.get("query_type") != qtype:
        return None
    return template


def query_node(state: AgentState) -> dict[str, Any]:
    query_type = state.get("query_type") or "cypher"
    attempts = int(state.get("query_attempts") or 0) + 1
    trace = list(state.get("trace") or [])
    errors = list(state.get("errors") or [])
    trace.append(f"query:attempt={attempts}:type={query_type}")

    if query_type == "ontology_only":
        return {
            "draft_query": "",
            "validated_query": "",
            "query_attempts": attempts,
            "validation_ok": True,
            "validation_error": None,
            "status": "generating",
            "errors": errors,
            "trace": trace,
        }

    procedure_query = _procedure_template(state)
    if procedure_query:
        trace.append("query:procedure_template")
        log_memory_phase(
            "query (procedure_template)",
            question=state.get("question") or "",
            after=snapshot_query_grounding(
                state,
                grounded=procedure_query,
                procedure_reused=True,
            ),
        )
        return {
            "draft_query": procedure_query,
            "query_attempts": attempts,
            "validation_ok": False,
            "validation_error": None,
            "status": "generating",
            "errors": errors,
            "trace": trace,
        }

    grounded = _grounded_question(state)
    log_memory_phase(
        "query (grounded_context)",
        question=state.get("question") or "",
        after=snapshot_query_grounding(
            state,
            grounded=grounded,
            procedure_reused=False,
        ),
    )
    draft = ""
    try:
        if query_type == "sparql":
            gen = get_sparql_generator()
            if state.get("validation_error") and state.get("draft_query"):
                draft = gen.repair(
                    state.get("question") or "",
                    state.get("draft_query") or "",
                    state.get("validation_error") or "invalid",
                )
            else:
                draft = gen.generate(grounded)
        else:
            gen = get_cypher_generator()
            if state.get("validation_error") and state.get("draft_query"):
                draft = gen.repair(
                    state.get("question") or "",
                    state.get("draft_query") or "",
                    state.get("validation_error") or "invalid",
                )
            else:
                draft = gen.generate(grounded)
    except Exception as exc:
        logger.exception("Query generation failed")
        errors.append(f"query_generate: {exc}")
        draft = state.get("draft_query") or ""

    return {
        "draft_query": draft,
        "query_attempts": attempts,
        "validation_ok": False,
        "validation_error": None,
        "status": "generating",
        "errors": errors,
        "trace": trace,
    }
