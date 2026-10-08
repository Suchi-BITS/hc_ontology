"""Graph + vector hybrid retrieval for ontology grounding."""

from __future__ import annotations

import logging
import re
from typing import Any

from core.dependencies import get_embedding_service, get_ontology, get_sparql_to_cypher
from enterprise.lexical_memory import expand_tokens, extract_tokens, overlap_score, split_name_tokens

logger = logging.getLogger("healthcare_ontology.enterprise")

_TOKEN = re.compile(r"[a-z0-9]+", re.I)


def _normalize_vector_hits(raw: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw or []:
        if isinstance(item, dict):
            name = item.get("name") or item.get("concept") or item.get("id") or ""
            score = float(item.get("score") or item.get("similarity") or 0.0)
            out.append(
                {
                    "name": str(name),
                    "score": score,
                    "source": "vector",
                    "description": item.get("description") or item.get("text") or "",
                    "raw": item,
                }
            )
        else:
            out.append({"name": str(item), "score": 0.0, "source": "vector"})
    return out


def _graph_keyword_hits(question: str, limit: int = 8) -> list[dict[str, Any]]:
    """Keyword / schema graph retrieval via ontology class/individual names."""
    tokens = extract_tokens(question)
    expanded = expand_tokens(tokens)
    if not expanded:
        return []
    hits: list[dict[str, Any]] = []
    try:
        onto = get_ontology()
        classes = onto.get_classes()
        individuals = onto.get_individuals() if hasattr(onto, "get_individuals") else []
        for name in list(classes) + list(individuals):
            nl = name.lower()
            name_tokens = split_name_tokens(name)
            score = overlap_score(tokens, name)
            # Extra boost when expanded alias token appears in entity name
            if any(t in nl or t in name_tokens for t in expanded):
                score = max(score, overlap_score(expanded, name))
            if score > 0:
                hits.append(
                    {
                        "name": name,
                        "score": round(min(1.0, score), 4),
                        "source": "graph",
                        "description": f"Ontology entity match: {name}",
                    }
                )
        hits.sort(key=lambda x: x["score"], reverse=True)
        return hits[:limit]
    except Exception as exc:
        logger.warning("Graph keyword retrieval failed: %s", exc)
        return []


def _graph_neighborhood(concept_names: list[str], limit: int = 10) -> list[dict[str, Any]]:
    """Optional Neo4j neighborhood expansion around retrieved concept names."""
    if not concept_names:
        return []
    names = [n.replace("'", "") for n in concept_names[:5] if n]
    if not names:
        return []
    try:
        bridge = get_sparql_to_cypher()
        or_clause = " OR ".join([f"n.name = '{n}'" for n in names])
        q = f"""
        MATCH (n)
        WHERE {or_clause}
        OPTIONAL MATCH (n)-[r]-(m)
        RETURN coalesce(n.name, n.concept) AS source,
               type(r) AS rel,
               coalesce(m.name, m.concept) AS neighbor
        LIMIT {int(limit)}
        """
        rows = bridge.execute_cypher(q)
    except Exception as exc:
        logger.debug("Neighborhood expansion skipped: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for row in rows or []:
        if hasattr(row, "data"):
            row = row.data()
        if not isinstance(row, dict):
            continue
        neighbor = row.get("neighbor")
        if neighbor:
            out.append(
                {
                    "name": str(neighbor),
                    "score": 0.35,
                    "source": "graph_neighborhood",
                    "description": f"{row.get('source')} -[{row.get('rel')}]-> {neighbor}",
                }
            )
    return out


def hybrid_retrieve(question: str, top_k: int = 8) -> dict[str, Any]:
    """Combine vector similarity + graph keyword/neighborhood retrieval with RRF-ish merge."""
    vector_hits: list[dict[str, Any]] = []
    try:
        emb = get_embedding_service()
        payload = emb.search_api(query=question, top_k=top_k)
        vector_hits = _normalize_vector_hits(payload.get("results") or [])
    except Exception as exc:
        logger.warning("Vector retrieval failed: %s", exc)

    graph_hits = _graph_keyword_hits(question, limit=top_k)
    seed_names = [h["name"] for h in (vector_hits + graph_hits) if h.get("name")]
    neighborhood = _graph_neighborhood(seed_names, limit=top_k)

    # Reciprocal rank fusion
    scores: dict[str, float] = {}
    meta: dict[str, dict[str, Any]] = {}
    for rank, hit in enumerate(vector_hits):
        name = hit["name"]
        scores[name] = scores.get(name, 0.0) + 1.0 / (60 + rank)
        meta[name] = hit
    for rank, hit in enumerate(graph_hits + neighborhood):
        name = hit["name"]
        scores[name] = scores.get(name, 0.0) + 1.0 / (60 + rank)
        if name not in meta:
            meta[name] = hit
        else:
            # Prefer keeping both sources noted
            src = {meta[name].get("source"), hit.get("source")}
            meta[name] = {**meta[name], "source": "+".join(sorted(s for s in src if s))}

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    fused = []
    for name, rrf in ranked:
        item = dict(meta.get(name) or {"name": name})
        channel = float(item.get("score") or 0.0)
        item["rrf_score"] = round(rrf, 6)
        item["channel_score"] = round(channel, 6)
        # Preserve strongest channel signal for downstream rerank/abstention
        if channel <= 0 and rrf > 0:
            item["score"] = round(rrf, 6)
        fused.append(item)

    return {
        "query": question,
        "vector_count": len(vector_hits),
        "graph_count": len(graph_hits) + len(neighborhood),
        "results": fused,
        "channels": {
            "vector": vector_hits[:top_k],
            "graph": graph_hits,
            "neighborhood": neighborhood,
        },
    }
