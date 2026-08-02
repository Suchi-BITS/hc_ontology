"""Response Agent — grounded natural-language answer + memory write."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_ollama import ChatOllama

from agents.memory import get_agent_memory
from agents.state import AgentState
from core.config import get_settings

logger = logging.getLogger("healthcare_ontology.agent")


def _fallback_answer(state: AgentState, *, failed: bool = False) -> str:
    if failed:
        err = state.get("validation_error") or state.get("execution_error") or "unknown error"
        return (
            f"I could not complete the request after validation/execution.\n"
            f"Reason: {err}"
        )
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


def response_node(state: AgentState) -> dict[str, Any]:
    return _compose_response(state, failed=False)


def respond_failed_node(state: AgentState) -> dict[str, Any]:
    return _compose_response(state, failed=True)


def rejected_node(state: AgentState) -> dict[str, Any]:
    trace = list(state.get("trace") or [])
    trace.append("response:rejected")
    answer = _fallback_answer(state)
    _persist(state, answer, status="rejected")
    return {
        "answer": answer,
        "citations": [],
        "status": "rejected",
        "trace": trace,
    }


def _compose_response(state: AgentState, *, failed: bool) -> dict[str, Any]:
    trace = list(state.get("trace") or [])
    errors = list(state.get("errors") or [])
    trace.append("response:start")
    settings = get_settings()

    citations: list[str] = []
    for item in (state.get("retrieved_concepts") or [])[:5]:
        if isinstance(item, dict):
            name = item.get("name") or item.get("concept")
            if name:
                citations.append(str(name))
        else:
            citations.append(str(item))

    answer = _fallback_answer(state, failed=failed)
    if not failed and state.get("human_decision") != "rejected":
        try:
            llm = ChatOllama(model=settings["ollama_model"], temperature=0.2)
            prompt = f"""You are the Response Agent for a healthcare ontology system.
Write a clear, concise answer grounded ONLY in the provided results.
Do not invent patients, diagnoses, or facts not present in results.
If results are empty, say so.

Question: {state.get('question')}
Query type: {state.get('query_type')}
Query used: {state.get('validated_query') or state.get('draft_query') or '(ontology lookup)'}
Plan: {state.get('plan')}
Results JSON:
{json.dumps((state.get('results') or [])[:25], default=str)[:4000]}

Answer:"""
            raw = llm.invoke(prompt)
            content = getattr(raw, "content", str(raw)).strip()
            if content:
                answer = content
        except Exception as exc:
            logger.warning("Response LLM failed, using fallback: %s", exc)
            errors.append(f"response_llm: {exc}")

    status = "failed" if failed else "completed"
    if state.get("execution_error") and not failed:
        status = "failed"
        answer = _fallback_answer({**state, "execution_error": state.get("execution_error")}, failed=True)

    _persist(state, answer, status=status)
    trace.append(f"response:{status}")
    return {
        "answer": answer,
        "citations": citations,
        "status": status,
        "errors": errors,
        "trace": trace,
    }


def _persist(state: AgentState, answer: str, *, status: str) -> None:
    session_id = state.get("session_id")
    if not session_id:
        return
    concepts = []
    for item in state.get("retrieved_concepts") or []:
        if isinstance(item, dict):
            name = item.get("name") or item.get("concept")
            if name:
                concepts.append(str(name))
    try:
        get_agent_memory().save_turn(
            session_id=session_id,
            thread_id=state.get("thread_id") or "",
            question=state.get("question") or "",
            answer=answer,
            query_type=state.get("query_type") or "",
            draft_query=state.get("validated_query") or state.get("draft_query") or "",
            status=status,
            concept_names=concepts,
            metadata={"trace": state.get("trace"), "plan": state.get("plan")},
        )
    except Exception as exc:
        logger.warning("Failed to persist agent turn: %s", exc)
