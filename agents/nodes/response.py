"""Response Agent — structured answer + mandatory provenance + memory write."""

from __future__ import annotations

import json
import logging
from typing import Any

from agents.memory import get_memory_orchestrator
from agents.state import AgentState
from core.config import get_settings
from core.llm import get_chat_llm
from enterprise.structured_response import (
    STRUCTURED_RESPONSE_PROMPT,
    build_structured_answer,
    parse_llm_structured,
)

logger = logging.getLogger("healthcare_ontology.agent")


def _refusal_message(state: AgentState) -> str:
    reason = state.get("refusal_reason") or "unknown"
    conf = state.get("confidence")
    prov = state.get("provenance") or {}
    path_count = prov.get("path_count", 0)
    return (
        "I cannot answer with sufficient confidence or traceable evidence.\n"
        f"Reason: {reason}\n"
        f"Confidence: {conf}\n"
        f"Provenance paths recorded: {path_count}\n"
        "See `provenance` and `structured_answer` in the API response for audit details."
    )


def _fallback_summary(state: AgentState, *, failed: bool = False) -> str:
    if state.get("refused"):
        return _refusal_message(state)
    if failed:
        err = state.get("validation_error") or state.get("execution_error") or "unknown error"
        return f"Request failed after validation/execution. Reason: {err}"
    if state.get("human_decision") == "rejected":
        return "Query execution was rejected by a human reviewer."

    results = state.get("results") or []
    qtype = state.get("query_type")
    query = state.get("validated_query") or state.get("draft_query") or ""
    preview = json.dumps(results[:10], default=str)[:1500]
    return (
        f"Question: {state.get('question')}\n"
        f"Path: {qtype}\n"
        f"Query:\n{query}\n\n"
        f"Results ({len(results)} rows):\n{preview}"
    )


def _citations_from_state(state: AgentState) -> list[str]:
    citations: list[str] = []
    prov = state.get("provenance") or {}
    for path in prov.get("paths") or []:
        if path.get("kind") == "ontology_concept" and path.get("name"):
            citations.append(str(path["name"]))
        elif path.get("kind") == "query" and path.get("text"):
            citations.append(f"{path.get('language', 'query')}:{str(path['text'])[:120]}")
    if not citations:
        for item in (state.get("retrieved_concepts") or [])[:5]:
            if isinstance(item, dict):
                name = item.get("name") or item.get("concept")
                if name:
                    citations.append(str(name))
    return citations


def _compose_response(state: AgentState, *, failed: bool) -> dict[str, Any]:
    trace = list(state.get("trace") or [])
    errors = list(state.get("errors") or [])
    trace.append("response:start")
    settings = get_settings()

    failed = failed or state.get("status") == "failed" or bool(
        state.get("validation_error") and not state.get("validation_ok")
    )
    refused = bool(state.get("refused"))
    confidence = float(state.get("confidence") or 0.0)
    provenance = state.get("provenance") or {}
    query_type = state.get("query_type") or "cypher"
    query = state.get("validated_query") or state.get("draft_query") or ""
    results = state.get("results") or []
    concepts = state.get("retrieved_concepts") or []

    summary = _fallback_summary(state, failed=failed)

    if not refused and not failed and state.get("human_decision") != "rejected":
        if settings.get("agent_structured_llm", True):
            try:
                llm = get_chat_llm(model=settings["llm_model"], temperature=0)
                prompt = STRUCTURED_RESPONSE_PROMPT.format(
                    question=state.get("question"),
                    query_type=query_type,
                    query=query or "(ontology lookup)",
                    confidence=confidence,
                    refused=False,
                    results_json=json.dumps(results[:25], default=str)[:4000],
                )
                raw = llm.invoke(prompt)
                content = getattr(raw, "content", str(raw)).strip()
                parsed = parse_llm_structured(content)
                if parsed and parsed.get("summary"):
                    summary = str(parsed["summary"]).strip()
            except Exception as exc:
                logger.warning("Structured response LLM failed, using fallback: %s", exc)
                errors.append(f"response_llm: {exc}")

    structured = build_structured_answer(
        question=state.get("question") or "",
        query_type=query_type,
        query=query,
        results=results,
        concepts=concepts,
        refused=refused,
        refusal_reason=state.get("refusal_reason"),
        confidence=confidence,
        summary=summary,
    )

    if refused:
        answer = _refusal_message(state)
        status = "refused"
    else:
        answer = structured.get("summary") or summary
        status = "failed" if failed else "completed"
        if state.get("execution_error") and not failed:
            status = "failed"
            answer = _fallback_summary({**state, "execution_error": state.get("execution_error")}, failed=True)
            structured["status"] = "failed"

    citations = _citations_from_state(state)
    _persist(state, answer, status=status)
    trace.append(f"response:{status}")
    return {
        "answer": answer,
        "citations": citations,
        "structured_answer": structured,
        "provenance": provenance,
        "refused": refused,
        "status": status,
        "errors": errors,
        "trace": trace,
    }


def response_node(state: AgentState) -> dict[str, Any]:
    return _compose_response(state, failed=False)


def respond_failed_node(state: AgentState) -> dict[str, Any]:
    """Mark validation exhaustion; abstention + response nodes finish the turn."""
    trace = list(state.get("trace") or [])
    errors = list(state.get("errors") or [])
    trace.append("validation:max_retries_exhausted")
    return {
        "status": "failed",
        "errors": errors,
        "trace": trace,
    }


def rejected_node(state: AgentState) -> dict[str, Any]:
    trace = list(state.get("trace") or [])
    trace.append("response:rejected")
    answer = _fallback_summary(state)
    structured = build_structured_answer(
        question=state.get("question") or "",
        query_type=state.get("query_type") or "cypher",
        query=state.get("validated_query") or state.get("draft_query") or "",
        results=[],
        concepts=state.get("retrieved_concepts") or [],
        refused=True,
        refusal_reason="human_rejected",
        confidence=0.0,
        summary=answer,
    )
    _persist(state, answer, status="rejected")
    return {
        "answer": answer,
        "citations": [],
        "structured_answer": structured,
        "refused": True,
        "refusal_reason": "human_rejected",
        "confidence": 0.0,
        "status": "rejected",
        "trace": trace,
    }


def _persist(state: AgentState, answer: str, *, status: str) -> None:
    try:
        get_memory_orchestrator().commit_turn(state, answer=answer, status=status)
    except Exception as exc:
        logger.warning("Failed to persist agent turn: %s", exc)
