"""Execution Agent — run validated Cypher / SPARQL (or ontology-only skip)."""

from __future__ import annotations

import logging
from typing import Any

from agents.state import AgentState
from core.dependencies import get_ontology, get_sparql_to_cypher

logger = logging.getLogger("healthcare_ontology.agent")


def execution_node(state: AgentState) -> dict[str, Any]:
    query_type = state.get("query_type") or "cypher"
    query = state.get("validated_query") or state.get("draft_query") or ""
    trace = list(state.get("trace") or [])
    errors = list(state.get("errors") or [])
    trace.append(f"execution:start:{query_type}")

    if query_type == "ontology_only":
        # Results are the retrieved concepts from Ontology Agent
        results = state.get("retrieved_concepts") or []
        trace.append(f"execution:ontology_only:n={len(results)}")
        return {
            "results": results,
            "execution_error": None,
            "status": "executing",
            "errors": errors,
            "trace": trace,
        }

    results: list[Any] = []
    exec_error = None
    try:
        if query_type == "sparql":
            results = get_ontology().execute_sparql(query)
        else:
            results = get_sparql_to_cypher().execute_cypher(query)
        # Normalize Neo4j records to plain dicts/lists when needed
        if results and hasattr(results[0], "data"):
            results = [r.data() for r in results]
        trace.append(f"execution:ok:n={len(results) if isinstance(results, list) else 1}")
    except Exception as exc:
        logger.exception("Execution failed")
        exec_error = str(exc)
        errors.append(f"execution: {exc}")
        trace.append("execution:error")

    return {
        "results": results if isinstance(results, list) else [results],
        "execution_error": exec_error,
        "status": "executing",
        "errors": errors,
        "trace": trace,
    }
