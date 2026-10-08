"""Calibrated abstention — decide whether the agent may answer."""

from __future__ import annotations

from typing import Any

from core.config import get_settings
from enterprise.provenance import build_provenance


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def compute_confidence(state: dict[str, Any], *, provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fuse retrieval, validation, execution, and provenance into one score."""
    prov = provenance or build_provenance(state)
    signals: dict[str, float] = {}

    concepts = state.get("retrieved_concepts") or []
    top_retrieval = 0.0
    for item in concepts[:3]:
        if isinstance(item, dict):
            top_retrieval = max(
                top_retrieval,
                float(item.get("rerank_score") or 0.0),
                float(item.get("fusion_base") or 0.0),
                float(item.get("channel_score") or item.get("score") or 0.0),
                float(item.get("lexical_score") or 0.0),
                float(item.get("rrf_score") or 0.0),
            )
    signals["retrieval"] = _clamp(top_retrieval)

    retrieval_meta = state.get("retrieval_meta") or {}
    budget = retrieval_meta.get("error_budget") or {}
    pool_hit = float(budget.get("concept_pool_hit_rate") or 0.0)
    signals["retrieval_pool"] = _clamp(pool_hit)

    memory_bundle = state.get("memory_bundle") or {}
    episodic = memory_bundle.get("episodic") or {}
    has_episodic = bool(episodic.get("recent_text")) or bool(episodic.get("similar_episodes"))
    has_procedural = bool(memory_bundle.get("procedural"))
    base_coverage = (0.5 if has_episodic else 0.0) + (0.5 if has_procedural else 0.0)
    meta = state.get("meta_memory") or {}
    recall_conf = meta.get("recall_confidence")
    if recall_conf is not None and meta.get("signals", {}).get("enabled", True):
        signals["memory_coverage"] = _clamp(0.7 * base_coverage + 0.3 * float(recall_conf))
    else:
        signals["memory_coverage"] = _clamp(base_coverage)

    if state.get("validation_ok"):
        signals["validation"] = 1.0
    elif state.get("validation_error"):
        signals["validation"] = 0.0
    else:
        signals["validation"] = 0.5

    exec_err = state.get("execution_error")
    results = state.get("results") or []
    if exec_err:
        signals["execution"] = 0.0
    elif results:
        signals["execution"] = _clamp(min(1.0, 0.4 + len(results) * 0.06))
    else:
        signals["execution"] = 0.15

    signals["provenance"] = 1.0 if prov.get("mandatory_satisfied") else 0.0

    weights = {
        "retrieval": 0.18,
        "retrieval_pool": 0.08,
        "memory_coverage": 0.04,
        "validation": 0.25,
        "execution": 0.25,
        "provenance": 0.20,
    }
    confidence = sum(signals[k] * weights[k] for k in weights)
    confidence = round(_clamp(confidence), 4)

    return {
        "confidence": confidence,
        "signals": {k: round(v, 4) for k, v in signals.items()},
        "weights": weights,
    }


def decide_abstention(
    state: dict[str, Any],
    *,
    threshold: float | None = None,
    force_failed: bool = False,
) -> dict[str, Any]:
    """Return refusal decision + reason. Answering requires provenance + confidence."""
    settings = get_settings()
    threshold = (
        threshold
        if threshold is not None
        else float(settings.get("agent_abstention_threshold", 0.45))
    )

    provenance = build_provenance(state)
    scored = compute_confidence(state, provenance=provenance)
    confidence = scored["confidence"]

    refused = False
    refusal_reason: str | None = None

    if force_failed or state.get("human_decision") == "rejected":
        refused = True
        refusal_reason = "human_rejected" if state.get("human_decision") == "rejected" else "pipeline_failed"
    elif state.get("execution_error"):
        refused = True
        refusal_reason = "execution_failed"
    elif not provenance.get("mandatory_satisfied"):
        refused = True
        refusal_reason = "missing_provenance"
    elif confidence < threshold:
        refused = True
        refusal_reason = "low_confidence"

    query_type = state.get("query_type") or "cypher"
    if query_type == "ontology_only":
        # An ontology-only answer rests on retrieval alone: there is no query or result set to vouch for it. Found by
        # the live AI verification: "What is the capital of France?" was answered as `completed` at confidence 0.76
        # because validation and execution count as success for this path, although the best concept match scored
        # 0.25. Retrieval that is not actually about the question is not evidence.
        floor = float(settings.get("agent_ontology_min_relevance", 0.30))
        if not (state.get("retrieved_concepts") or []):
            refused = True
            refusal_reason = refusal_reason or "no_evidence"
        elif scored["signals"]["retrieval"] < floor:
            refused = True
            refusal_reason = refusal_reason or "no_evidence"

    return {
        "refused": refused,
        "refusal_reason": refusal_reason,
        "confidence": confidence,
        "threshold": threshold,
        "signals": scored["signals"],
        "provenance": provenance,
    }
