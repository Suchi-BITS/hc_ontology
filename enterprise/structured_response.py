"""Structured agent answers — constrained JSON, not free-form prose."""

from __future__ import annotations

import json
import re
from typing import Any

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _facts_from_results(results: list[Any], *, limit: int = 12) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for row in results[:limit]:
        if isinstance(row, dict):
            facts.append({"type": "record", "fields": row})
        else:
            facts.append({"type": "value", "fields": {"value": str(row)}})
    return facts


def build_structured_answer(
    *,
    question: str,
    query_type: str,
    query: str,
    results: list[Any],
    concepts: list[dict[str, Any]],
    refused: bool,
    refusal_reason: str | None,
    confidence: float,
    summary: str,
) -> dict[str, Any]:
    """Rule-based structured envelope (always valid JSON-serializable)."""
    status = "refused" if refused else "answered"
    payload: dict[str, Any] = {
        "status": status,
        "confidence": round(confidence, 4),
        "refusal_reason": refusal_reason,
        "question": question,
        "query_type": query_type,
        "query": query or None,
        "summary": summary[:4000],
        "facts": [] if refused else _facts_from_results(results),
        "concepts": [
            {
                "name": c.get("name"),
                "score": c.get("rerank_score") or c.get("rrf_score") or c.get("score"),
                "source": c.get("source"),
            }
            for c in concepts[:8]
            if isinstance(c, dict) and c.get("name")
        ],
    }
    return payload


def parse_llm_structured(raw: str) -> dict[str, Any] | None:
    """Extract JSON object from model output; returns None on failure."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


STRUCTURED_RESPONSE_PROMPT = """You are a healthcare ontology response formatter.
Return ONLY valid JSON (no markdown) matching this schema:
{{
  "status": "answered" or "refused",
  "confidence": number between 0 and 1,
  "summary": "one short paragraph grounded ONLY in facts below",
  "facts": [{{"type": "record", "fields": {{...}}}}],
  "refusal_reason": null or string
}}

Question: {question}
Query type: {query_type}
Query: {query}
Confidence score: {confidence}
Refused: {refused}
Results JSON:
{results_json}

JSON:"""
