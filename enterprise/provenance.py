"""Mandatory provenance paths for agent answers."""

from __future__ import annotations

from typing import Any


def build_provenance(state: dict[str, Any]) -> dict[str, Any]:
    """Build a traceable evidence envelope from agent state."""
    query_type = state.get("query_type") or "cypher"
    query = (state.get("validated_query") or state.get("draft_query") or "").strip()
    results = state.get("results") or []
    concepts = state.get("retrieved_concepts") or []
    retrieval = state.get("retrieval_meta") or {}
    hybrid = state.get("hybrid_meta") or {}

    paths: list[dict[str, Any]] = []

    if query:
        paths.append(
            {
                "kind": "query",
                "language": query_type,
                "text": query[:4000],
            }
        )

    for rank, item in enumerate(concepts[:10]):
        if not isinstance(item, dict):
            continue
        paths.append(
            {
                "kind": "ontology_concept",
                "rank": rank + 1,
                "name": item.get("name"),
                "source": item.get("source"),
                "score": item.get("rerank_score")
                or item.get("rrf_score")
                or item.get("score"),
                "description": (item.get("description") or "")[:240],
            }
        )

    for idx, row in enumerate(results[:15]):
        if isinstance(row, dict):
            paths.append({"kind": "result_row", "index": idx, "data": row})
        else:
            paths.append({"kind": "result_row", "index": idx, "data": str(row)[:500]})

    if retrieval.get("channels"):
        paths.append(
            {
                "kind": "retrieval_trace",
                "channels": retrieval.get("channels"),
                "error_budget": retrieval.get("error_budget"),
            }
        )

    query_path = any(p["kind"] == "query" for p in paths)
    concept_paths = [p for p in paths if p["kind"] == "ontology_concept"]
    result_paths = [p for p in paths if p["kind"] == "result_row"]

    if query_type == "ontology_only":
        evidence_ok = len(concept_paths) > 0
    elif query_type in ("cypher", "sparql"):
        evidence_ok = query_path and len(result_paths) > 0
    else:
        evidence_ok = len(paths) > 0

    return {
        "paths": paths,
        "path_count": len(paths),
        "query_type": query_type,
        "has_query_path": query_path,
        "concept_count": len(concept_paths),
        "result_count": len(result_paths),
        "hybrid_meta": hybrid,
        "retrieval_meta": retrieval,
        "mandatory_satisfied": evidence_ok,
    }
