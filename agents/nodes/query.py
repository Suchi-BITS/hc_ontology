"""Query Agent — NL → Cypher / SPARQL with ontology grounding + repair."""

from __future__ import annotations

import logging
from typing import Any

from agents.state import AgentState
from core.dependencies import get_cypher_generator, get_sparql_generator

logger = logging.getLogger("healthcare_ontology.agent")


def _grounded_question(state: AgentState) -> str:
    parts = [state.get("question") or ""]
    ctx = state.get("ontology_context") or ""
    mem = state.get("memory_context") or ""
    if ctx:
        parts.append("\n\nOntology grounding:\n" + ctx[:2500])
    if mem:
        parts.append("\n\n" + mem[:1500])
    err = state.get("validation_error")
    if err and state.get("draft_query"):
        parts.append(
            "\n\nPrevious query failed validation:\n"
            f"{state.get('draft_query')}\nError: {err}\n"
            "Generate a corrected query."
        )
    return "\n".join(parts)


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

    grounded = _grounded_question(state)
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
