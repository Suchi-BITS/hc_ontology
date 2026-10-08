"""Multi-stage ontology retrieval: pool → rerank → error budget."""

from __future__ import annotations

from typing import Any

from enterprise.hybrid_retrieval import hybrid_retrieve
from enterprise.lexical_memory import expand_tokens, extract_tokens, overlap_score


def _lexical_score(question: str, name: str, description: str = "") -> float:
    tokens = extract_tokens(question)
    if not tokens:
        return 0.0
    haystack = f"{name} {description}"
    return overlap_score(tokens, haystack)


def _fusion_base(item: dict[str, Any]) -> float:
    """Best available retrieval signal before rerank (vector cosine, graph, or RRF)."""
    return max(
        float(item.get("channel_score") or 0.0),
        float(item.get("score") or 0.0),
        float(item.get("rrf_score") or 0.0),
    )


def rerank_candidates(
    question: str,
    candidates: list[dict[str, Any]],
    *,
    top_k: int = 8,
) -> list[dict[str, Any]]:
    """Second-stage rerank: fuse channel score, RRF rank, and alias-aware lexical overlap."""
    ranked: list[tuple[float, dict[str, Any]]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        desc = str(item.get("description") or "")
        base = _fusion_base(item)
        lex = _lexical_score(question, name, desc)
        rerank = 0.40 * base + 0.60 * lex
        enriched = dict(item)
        enriched["lexical_score"] = round(lex, 4)
        enriched["fusion_base"] = round(base, 4)
        enriched["rerank_score"] = round(rerank, 6)
        ranked.append((rerank, enriched))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in ranked[:top_k]]


def compute_error_budget(
    question: str,
    *,
    pool: list[dict[str, Any]],
    reranked: list[dict[str, Any]],
    channels: dict[str, Any] | None,
) -> dict[str, Any]:
    """Decompose retrieval quality for observability (agentic-KG-style error budget)."""
    q_tokens = expand_tokens(extract_tokens(question))
    pool_names = {str(c.get("name") or "").lower() for c in pool if isinstance(c, dict)}

    lexical_hits = 0
    for t in q_tokens:
        if any(t in n or n in t for n in pool_names if n):
            lexical_hits += 1
    lexical_recall = lexical_hits / max(len(q_tokens), 1)

    vector_n = len((channels or {}).get("vector") or [])
    graph_n = len((channels or {}).get("graph") or [])
    neighborhood_n = len((channels or {}).get("neighborhood") or [])

    top = reranked[0] if reranked else {}
    top_score = float(top.get("rerank_score") or top.get("rrf_score") or 0.0)

    return {
        "pool_size": len(pool),
        "rerank_size": len(reranked),
        "concept_pool_hit_rate": round(lexical_recall, 4),
        "top_rerank_score": round(top_score, 4),
        "channel_counts": {
            "vector": vector_n,
            "graph": graph_n,
            "neighborhood": neighborhood_n,
        },
        "residual_retrieval_risk": round(max(0.0, 1.0 - top_score), 4),
    }


def retrieve_with_rerank(
    question: str,
    *,
    pool_size: int = 16,
    top_k: int = 8,
) -> dict[str, Any]:
    """Stage-1 hybrid pool → stage-2 rerank → error budget metadata."""
    hybrid = hybrid_retrieve(question, top_k=pool_size)
    pool = hybrid.get("results") or []
    channels = hybrid.get("channels") or {}
    reranked = rerank_candidates(question, pool, top_k=top_k)
    budget = compute_error_budget(
        question,
        pool=pool,
        reranked=reranked,
        channels=channels,
    )
    return {
        "query": question,
        "results": reranked,
        "pool": pool,
        "channels": channels,
        "vector_count": hybrid.get("vector_count"),
        "graph_count": hybrid.get("graph_count"),
        "error_budget": budget,
    }
