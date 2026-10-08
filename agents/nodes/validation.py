"""Validation Agent — safety / schema checks with retry signal."""

from __future__ import annotations

import logging
from typing import Any

from agents.memory.debug_context import log_memory_phase
from agents.state import AgentState
from core.cypher_validator import CypherQueryValidator
from core.dependencies import get_cypher_generator, get_ontology, get_sparql_generator
from core.sparql_validator import SparqlQueryValidator

logger = logging.getLogger("healthcare_ontology.agent")


def validation_node(state: AgentState) -> dict[str, Any]:
    query_type = state.get("query_type") or "cypher"
    draft = state.get("draft_query") or ""
    trace = list(state.get("trace") or [])
    errors = list(state.get("errors") or [])
    trace.append("validation:start")

    if query_type == "ontology_only":
        trace.append("validation:skip_ontology_only")
        return {
            "validation_ok": True,
            "validation_error": None,
            "validation_stage": None,
            "validated_query": "",
            "status": "validating",
            "errors": errors,
            "trace": trace,
        }

    if not draft.strip():
        trace.append("validation:empty_query")
        return {
            "validation_ok": False,
            "validation_error": "Empty query generated",
            "validation_stage": "empty",
            "validated_query": "",
            "status": "validating",
            "errors": errors + ["validation: empty query"],
            "trace": trace,
        }

    try:
        if query_type == "sparql":
            gen = get_sparql_generator()
            schema = gen.get_schema()
            validator = SparqlQueryValidator(
                classes=schema["classes"],
                object_properties=schema["object_properties"],
                data_properties=schema["data_properties"],
                namespace=gen.namespace,
            )
            result = validator.run_all_checks(draft)
            ok = result.valid
            err = result.error
            stage = result.stage
            validated = result.query if ok else draft
        else:
            gen = get_cypher_generator()
            ontology = get_ontology()
            validator = CypherQueryValidator(
                classes=ontology.get_classes(),
                object_properties=[p.upper() for p in ontology.get_object_properties()],
                data_properties=ontology.get_data_properties(),
                explain_fn=None,
            )
            result = validator.run_all_checks(draft)
            ok = result.valid
            err = result.error
            stage = result.stage
            validated = result.query if ok else draft
    except Exception as exc:
        logger.exception("Validation failed unexpectedly")
        ok, err, stage, validated = False, str(exc), "exception", draft
        errors.append(f"validation: {exc}")

    trace.append(f"validation:{'ok' if ok else 'fail'}:{stage or '-'}")
    if not ok:
        attempts = int(state.get("query_attempts") or 0)
        max_retries = int(state.get("max_retries") or 3)
        log_memory_phase(
            "validation (fail → retry)" if attempts < max_retries else "validation (fail → exhausted)",
            question=state.get("question") or "",
            after={
                "validation_error": err or "validation failed",
                "validation_stage": stage,
                "draft_query_preview": (draft or "")[:500],
                "query_attempts": attempts,
                "max_retries": max_retries,
                "will_retry": attempts < max_retries,
            },
        )
    return {
        "validation_ok": ok,
        "validation_error": None if ok else (err or "validation failed"),
        "validation_stage": stage,
        "validated_query": validated if ok else "",
        "draft_query": validated if ok else draft,
        "status": "validating",
        "errors": errors,
        "trace": trace,
    }


def route_after_validation(state: AgentState) -> str:
    """Conditional edge: retry | human_gate | respond_failed."""
    if state.get("validation_ok"):
        return "human_gate"
    attempts = int(state.get("query_attempts") or 0)
    max_retries = int(state.get("max_retries") or 3)
    if attempts < max_retries:
        return "retry_query"
    return "respond_failed"
