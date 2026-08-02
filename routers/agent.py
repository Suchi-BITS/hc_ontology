"""Multi-agent LangGraph API routes (sync + async, tenancy, guardrails, RBAC)."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from langgraph.types import Command
from pydantic import BaseModel, Field

from agents.graph import get_agent_graph, serialize_state
from agents.memory import get_agent_memory
from core.config import get_settings
from core.job_store import job_store
from core.rate_limit import SlidingWindowRateLimiter
from enterprise.cost import cost_tracker
from enterprise.guardrails import check_input, check_output
from enterprise.monitoring import monitor
from enterprise.observability import trace_span
from enterprise.rbac import Permission, Principal, require_permission
from enterprise.tenancy import TenantContext, require_tenant

logger = logging.getLogger("healthcare_ontology.agent")

router = APIRouter(prefix="/agent", tags=["Multi-Agent"])

_limiter: SlidingWindowRateLimiter | None = None


def _rate_limiter() -> SlidingWindowRateLimiter:
    global _limiter
    if _limiter is None:
        n = get_settings()["llm_rate_limit_per_minute"]
        _limiter = SlidingWindowRateLimiter(max_calls=n, window_seconds=60)
    return _limiter


class AgentQueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_id: Optional[str] = None
    thread_id: Optional[str] = None
    require_human_approval: Optional[bool] = None
    max_retries: int = Field(default=3, ge=1, le=5)
    query_type: Optional[Literal["cypher", "sparql", "ontology_only"]] = None
    ontology_id: Optional[str] = Field(default="hc-core")
    ontology_version: Optional[str] = None


class AgentResumeRequest(BaseModel):
    thread_id: str = Field(..., min_length=1)
    decision: Literal["approved", "rejected"] = "approved"
    feedback: Optional[str] = None


def _interrupt_payload(result: Any) -> Optional[dict[str, Any]]:
    interrupts = getattr(result, "__interrupt__", None)
    if interrupts:
        first = interrupts[0]
        value = getattr(first, "value", first)
        return value if isinstance(value, dict) else {"payload": value}
    if isinstance(result, dict) and "__interrupt__" in result:
        items = result["__interrupt__"]
        if items:
            first = items[0]
            value = getattr(first, "value", first)
            return value if isinstance(value, dict) else {"payload": value}
    return None


def _build_inputs(
    request: AgentQueryRequest,
    *,
    tenant: TenantContext,
    principal: Principal,
    thread_id: str,
    session_id: str,
) -> dict[str, Any]:
    settings = get_settings()
    question = request.question.strip()
    if settings.get("guardrails_enabled", True):
        g = check_input(question)
        if not g.allowed:
            monitor.incr("guardrail_blocks")
            raise HTTPException(status_code=400, detail={"blocked": True, "reason": g.reason, "flags": g.flags})
        question = g.redacted_text or question
        guardrail_flags = g.flags or []
    else:
        guardrail_flags = []

    budget = float(settings.get("cost_budget_usd_per_day") or 25)
    if not cost_tracker.within_budget(tenant.tenant_id, budget):
        raise HTTPException(
            status_code=429,
            detail=f"Daily cost budget ${budget} exceeded for tenant {tenant.tenant_id}",
        )

    inputs: dict[str, Any] = {
        "question": question,
        "thread_id": thread_id,
        "session_id": session_id,
        "tenant_id": tenant.tenant_id,
        "user_id": principal.subject,
        "ontology_id": request.ontology_id or "hc-core",
        "ontology_version": request.ontology_version or "",
        "max_retries": request.max_retries,
        "status": "pending",
        "errors": [],
        "trace": [],
        "results": [],
        "citations": [],
        "guardrail_flags": guardrail_flags,
        "blocked": False,
        "cost_usd": 0.0,
    }
    if request.require_human_approval is not None:
        inputs["require_human_approval"] = request.require_human_approval
    if request.query_type:
        inputs["query_type"] = request.query_type
    if settings.get("agent_force_hitl") and request.require_human_approval is not False:
        inputs["require_human_approval"] = True
    return inputs


def _finalize_payload(values: dict[str, Any], *, interrupted: bool = False, interrupt: Any = None) -> dict[str, Any]:
    answer = values.get("answer") or ""
    if answer and get_settings().get("guardrails_enabled", True):
        out = check_output(answer)
        if out.allowed and out.redacted_text:
            answer = out.redacted_text
        elif not out.allowed:
            answer = "Response blocked by output guardrails."
            values["status"] = "failed"
            values["blocked"] = True

    base = {
        "status": values.get("status") or ("awaiting_approval" if interrupted else "completed"),
        "interrupted": interrupted,
        "thread_id": values.get("thread_id"),
        "session_id": values.get("session_id"),
        "tenant_id": values.get("tenant_id"),
        "answer": answer,
        "citations": values.get("citations") or [],
        "query_type": values.get("query_type"),
        "plan": values.get("plan"),
        "validated_query": values.get("validated_query") or values.get("draft_query"),
        "results": values.get("results") or [],
        "trace": values.get("trace") or [],
        "errors": values.get("errors") or [],
        "cost_usd": values.get("cost_usd"),
        "state": values,
    }
    if interrupt is not None:
        base["interrupt"] = interrupt
    return base


def _invoke_graph(inputs: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    graph = get_agent_graph()
    tenant_id = inputs.get("tenant_id") or "default"
    started = time.perf_counter()
    with trace_span("agent.invoke", {"tenant_id": tenant_id, "thread_id": config["configurable"]["thread_id"]}):
        try:
            result = graph.invoke(inputs, config=config)
            cost_tracker.record(tenant_id, "agent_run", units=1, meta={"path": "sync"})
            cost_tracker.record(tenant_id, "llm_call", units=3, meta={"estimated": True})
        except Exception:
            monitor.record_error("agent.invoke failed")
            raise
        finally:
            monitor.record_latency((time.perf_counter() - started) * 1000)

    snap = graph.get_state(config)
    interrupted = _interrupt_payload(result)
    next_nodes = list(snap.next) if snap and snap.next else []
    waiting = bool(interrupted) or ("human_gate" in next_nodes)

    if waiting:
        values = serialize_state(dict(snap.values) if snap else {})
        payload = interrupted or {
            "message": "Human approval required before query execution.",
            "question": values.get("question"),
            "query_type": values.get("query_type"),
            "validated_query": values.get("validated_query") or values.get("draft_query"),
            "plan": values.get("plan"),
            "next": next_nodes,
        }
        return _finalize_payload(values, interrupted=True, interrupt=payload)

    values = serialize_state(result if isinstance(result, dict) else {})
    values["cost_usd"] = cost_tracker.day_spend(tenant_id)
    return _finalize_payload(values)


@router.get("/health")
def agent_health():
    return {
        "status": "ok",
        "graph": "healthcare_multi_agent",
        "nodes": [
            "planner",
            "ontology",
            "query",
            "validation",
            "human_gate",
            "execution",
            "response",
        ],
        "features": [
            "shared_state",
            "conditional_routing",
            "retry_loops",
            "human_in_the_loop",
            "kg_memory",
            "multi_tenancy",
            "hybrid_retrieval",
            "guardrails",
            "rbac",
            "async_execution",
            "langsmith",
        ],
    }


@router.post("/query")
def agent_query(
    request: AgentQueryRequest,
    tenant: TenantContext = Depends(require_tenant),
    principal: Principal = Depends(require_permission(Permission.AGENT_RUN)),
):
    """Run the full multi-agent pipeline (may pause for HITL approval)."""
    _rate_limiter().check(f"agent:{tenant.tenant_id}")
    thread_id = request.thread_id or str(uuid.uuid4())
    session_id = request.session_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    try:
        get_agent_memory().ensure_schema()
    except Exception as exc:
        logger.warning("Could not ensure agent memory schema: %s", exc)

    inputs = _build_inputs(
        request, tenant=tenant, principal=principal, thread_id=thread_id, session_id=session_id
    )
    try:
        return _invoke_graph(inputs, config)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Agent query failed")
        monitor.record_error(str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/query/async")
def agent_query_async(
    request: AgentQueryRequest,
    tenant: TenantContext = Depends(require_tenant),
    principal: Principal = Depends(require_permission(Permission.AGENT_RUN)),
):
    """Enqueue multi-agent run; poll GET /agent/jobs/{id} or /enterprise/jobs/{id}."""
    _rate_limiter().check(f"agent:{tenant.tenant_id}")
    thread_id = request.thread_id or str(uuid.uuid4())
    session_id = request.session_id or str(uuid.uuid4())
    inputs = _build_inputs(
        request, tenant=tenant, principal=principal, thread_id=thread_id, session_id=session_id
    )
    config = {"configurable": {"thread_id": thread_id}}

    job_id = job_store.submit(
        "agent-query",
        lambda: _invoke_graph(inputs, config),
        meta={
            "tenant_id": tenant.tenant_id,
            "thread_id": thread_id,
            "session_id": session_id,
            "question": request.question[:200],
        },
    )
    return {
        "job_id": job_id,
        "thread_id": thread_id,
        "session_id": session_id,
        "status": "queued",
        "status_url": f"/agent/jobs/{job_id}",
    }


@router.get("/jobs/{job_id}")
def agent_job(
    job_id: str,
    _: Principal = Depends(require_permission(Permission.AGENT_RUN)),
):
    rec = job_store.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Job not found")
    return rec.to_dict()


@router.post("/resume")
def agent_resume(
    request: AgentResumeRequest,
    principal: Principal = Depends(require_permission(Permission.AGENT_APPROVE)),
):
    """Resume a graph paused at the human-in-the-loop gate."""
    _rate_limiter().check(f"agent-resume:{principal.subject}")
    config = {"configurable": {"thread_id": request.thread_id}}
    graph = get_agent_graph()

    snap = graph.get_state(config)
    if not snap or not snap.values:
        raise HTTPException(status_code=404, detail="Unknown thread_id / no checkpoint")
    if not snap.next:
        raise HTTPException(status_code=400, detail="Thread is not awaiting approval")

    resume_value = {"decision": request.decision, "feedback": request.feedback}
    try:
        result = graph.invoke(Command(resume=resume_value), config=config)
    except Exception as exc:
        logger.exception("Agent resume failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    interrupted = _interrupt_payload(result)
    if interrupted:
        values = serialize_state(dict(graph.get_state(config).values))
        return _finalize_payload(values, interrupted=True, interrupt=interrupted)

    values = serialize_state(result if isinstance(result, dict) else {})
    return _finalize_payload(values)


@router.get("/state/{thread_id}")
def agent_state(
    thread_id: str,
    _: Principal = Depends(require_permission(Permission.AGENT_RUN)),
):
    graph = get_agent_graph()
    config = {"configurable": {"thread_id": thread_id}}
    snap = graph.get_state(config)
    if not snap or not snap.values:
        raise HTTPException(status_code=404, detail="Unknown thread_id / no checkpoint")
    return {
        "thread_id": thread_id,
        "next": list(snap.next) if snap.next else [],
        "state": serialize_state(dict(snap.values)),
    }


@router.get("/memory/{session_id}")
def agent_memory(
    session_id: str,
    limit: int = 5,
    _: Principal = Depends(require_permission(Permission.AGENT_RUN)),
):
    ctx = get_agent_memory().load_context(session_id, limit=limit)
    return {"session_id": session_id, "context": ctx}
