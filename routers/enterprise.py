"""Enterprise API — tenancy, ontologies, hybrid retrieval, eval, monitoring, workflows."""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from core.job_store import job_store
from enterprise.cost import cost_tracker
from enterprise.evaluation import DEFAULT_CASES, push_to_langsmith, run_evaluation, run_governance_eval
from enterprise.guardrails import check_input
from enterprise.retrieval_pipeline import retrieve_with_rerank
from enterprise.monitoring import monitor
from enterprise.observability import configure_observability, langsmith_run_url
from enterprise.ontology_registry import ontology_registry
from enterprise.rbac import Permission, Principal, require_permission
from enterprise.tenancy import TenantContext, require_tenant, tenant_registry
from enterprise.workflows import WORKFLOWS, enqueue_workflow

router = APIRouter(prefix="/enterprise", tags=["Enterprise"])


class TenantCreate(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    display_name: str = ""
    ontology_ids: list[str] = Field(default_factory=lambda: ["hc-core"])
    neo4j_database: Optional[str] = None


class OntologyVersionPublish(BaseModel):
    version: str
    owl_path: str
    changelog: str = ""
    labels: list[str] = Field(default_factory=list)
    activate: bool = False


class HybridSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=8, ge=1, le=50)


class WorkflowRequest(BaseModel):
    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class GuardrailCheckRequest(BaseModel):
    text: str


@router.get("/health")
def enterprise_health():
    obs = configure_observability()
    return {
        "status": "ok",
        "capabilities": [
            "multi_tenancy",
            "multi_ontology",
            "knowledge_versioning",
            "hybrid_retrieval",
            "memory",
            "agent_evaluation",
            "langsmith",
            "opentelemetry",
            "guardrails",
            "rbac",
            "background_workflows",
            "async_execution",
            "cost_optimization",
            "monitoring",
        ],
        "observability": obs,
        "langsmith_url": langsmith_run_url(),
    }


@router.get("/tenants")
def list_tenants(principal: Principal = Depends(require_permission(Permission.ONTOLOGY_READ))):
    """A tenant sees only itself; the cross-tenant catalog needs the platform:admin permission."""
    visible = (
        tenant_registry.list()
        if principal.has(Permission.PLATFORM_ADMIN)
        else [t for t in tenant_registry.list() if t.tenant_id == principal.tenant_id]
    )
    return {
        "tenants": [
            {
                "tenant_id": t.tenant_id,
                "display_name": t.display_name,
                "ontology_ids": t.ontology_ids,
                "neo4j_database": t.neo4j_database,
                "active": t.active,
            }
            for t in visible
        ]
    }


@router.post("/tenants")
def create_tenant(
    body: TenantCreate,
    _: Principal = Depends(require_permission(Permission.PLATFORM_ADMIN)),
):
    tenant = TenantContext(
        tenant_id=body.tenant_id,
        display_name=body.display_name or body.tenant_id,
        ontology_ids=body.ontology_ids,
        neo4j_database=body.neo4j_database,
    )
    tenant_registry.upsert(tenant)
    return {"status": "ok", "tenant": tenant.tenant_id}


@router.get("/ontologies")
def list_ontologies(
    tenant: TenantContext = Depends(require_tenant),
    _: Principal = Depends(require_permission(Permission.ONTOLOGY_READ)),
):
    return {
        "tenant_id": tenant.tenant_id,
        "ontologies": [o.to_dict() for o in ontology_registry.list(tenant.tenant_id)],
    }


def _owned_ontology(ontology_id: str, tenant: TenantContext):
    """The ontology, only if the caller's tenant owns it. Someone else's looks like a missing one."""
    rec = ontology_registry.get(ontology_id)
    if not rec or tenant.tenant_id not in rec.tenant_ids:
        raise HTTPException(status_code=404, detail="Ontology not found")
    return rec


@router.get("/ontologies/{ontology_id}")
def get_ontology(
    ontology_id: str,
    tenant: TenantContext = Depends(require_tenant),
    _: Principal = Depends(require_permission(Permission.ONTOLOGY_READ)),
):
    return _owned_ontology(ontology_id, tenant).to_dict()


@router.post("/ontologies/{ontology_id}/versions")
def publish_ontology_version(
    ontology_id: str,
    body: OntologyVersionPublish,
    tenant: TenantContext = Depends(require_tenant),
    _: Principal = Depends(require_permission(Permission.ONTOLOGY_WRITE)),
):
    _owned_ontology(ontology_id, tenant)
    try:
        rec = ontology_registry.publish_version(
            ontology_id,
            version=body.version,
            owl_path=body.owl_path,
            changelog=body.changelog,
            labels=body.labels,
            activate=body.activate,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return rec.to_dict()


@router.post("/ontologies/{ontology_id}/activate/{version}")
def activate_ontology_version(
    ontology_id: str,
    version: str,
    tenant: TenantContext = Depends(require_tenant),
    _: Principal = Depends(require_permission(Permission.ONTOLOGY_WRITE)),
):
    _owned_ontology(ontology_id, tenant)
    try:
        return ontology_registry.set_active(ontology_id, version).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/hybrid-search")
def hybrid_search(
    body: HybridSearchRequest,
    tenant: TenantContext = Depends(require_tenant),
    _: Principal = Depends(require_permission(Permission.ONTOLOGY_READ)),
):
    started = time.perf_counter()
    try:
        result = retrieve_with_rerank(body.query, pool_size=16, top_k=body.top_k)
        cost_tracker.record(tenant.tenant_id, "embedding_call", units=1, meta={"hybrid": True})
        return {"tenant_id": tenant.tenant_id, **result}
    finally:
        monitor.record_latency((time.perf_counter() - started) * 1000)


@router.post("/guardrails/check")
def guardrails_check(
    body: GuardrailCheckRequest,
    _: Principal = Depends(require_permission(Permission.AGENT_RUN)),
):
    return check_input(body.text).__dict__


@router.get("/cost")
def cost_summary(
    tenant: TenantContext = Depends(require_tenant),
    _: Principal = Depends(require_permission(Permission.METRICS_READ)),
):
    from core.config import get_settings

    budget = float(get_settings().get("cost_budget_usd_per_day") or 25)
    summary = cost_tracker.summary(tenant.tenant_id)
    summary["budget_usd_per_day"] = budget
    summary["within_budget"] = cost_tracker.within_budget(tenant.tenant_id, budget)
    return summary


@router.get("/monitoring")
def monitoring_snapshot(_: Principal = Depends(require_permission(Permission.METRICS_READ))):
    return monitor.snapshot()


@router.get("/metrics")
def prometheus_metrics():
    return PlainTextResponse(monitor.prometheus_text(), media_type="text/plain; version=0.0.4")


@router.get("/workflows")
def list_workflows(_: Principal = Depends(require_permission(Permission.WORKFLOW_RUN))):
    return {"workflows": list(WORKFLOWS.keys())}


@router.post("/workflows/run")
def run_workflow(
    body: WorkflowRequest,
    tenant: TenantContext = Depends(require_tenant),
    _: Principal = Depends(require_permission(Permission.WORKFLOW_RUN)),
):
    params = dict(body.params)
    params["tenant_id"] = tenant.tenant_id  # never taken from the request body
    try:
        job_id = enqueue_workflow(body.name, **params)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job_id": job_id, "status_url": f"/jobs/{job_id}", "workflow": body.name}


@router.post("/eval/run")
def eval_run(_: Principal = Depends(require_permission(Permission.AGENT_EVAL))):
    """Run lightweight offline eval (planner heuristics + guardrails; no full LLM)."""
    from agents.nodes.planner import _heuristic_plan
    from enterprise.guardrails import check_input

    def runner(case):
        g = check_input(case.question)
        if not g.allowed:
            return {"status": "failed", "blocked": True, "answer": g.reason, "query_type": None}
        plan = _heuristic_plan(case.question)
        return {
            "status": "completed",
            "query_type": plan["query_type"],
            "answer": plan.get("reasoning", ""),
            "validated_query": "",
        }

    return run_evaluation(runner, DEFAULT_CASES)


@router.post("/eval/governance")
def eval_governance(
    split: str = "test",
    _: Principal = Depends(require_permission(Permission.AGENT_EVAL)),
):
    """Run governance eval: retrieval error budget + provenance + abstention metrics."""
    from agents.nodes.planner import _heuristic_plan
    from enterprise.abstention import decide_abstention
    from enterprise.guardrails import check_input
    from enterprise.provenance import build_provenance
    from enterprise.retrieval_pipeline import retrieve_with_rerank

    def runner(case: EvalCase):
        g = check_input(case.question)
        if not g.allowed:
            state = {
                "question": case.question,
                "blocked": True,
                "status": "failed",
                "refused": True,
                "refusal_reason": "guardrail",
            }
            state["provenance"] = build_provenance(state)
            return state

        plan = _heuristic_plan(case.question)
        pipeline = retrieve_with_rerank(case.question, pool_size=16, top_k=8)
        state = {
            "question": case.question,
            "status": "completed",
            "query_type": plan["query_type"],
            "answer": plan.get("reasoning", ""),
            "validated_query": "",
            "results": [],
            "retrieved_concepts": pipeline.get("results") or [],
            "retrieval_meta": {
                "error_budget": pipeline.get("error_budget"),
                "channels": pipeline.get("channels"),
            },
            "validation_ok": True,
        }
        abst = decide_abstention(state)
        state.update(
            {
                "refused": abst["refused"],
                "refusal_reason": abst.get("refusal_reason"),
                "confidence": abst.get("confidence"),
                "provenance": abst.get("provenance"),
            }
        )
        return state

    return run_governance_eval(runner, split=split)


@router.post("/eval/langsmith-dataset")
def eval_langsmith_dataset(
    name: str = "healthcare-agent-eval",
    _: Principal = Depends(require_permission(Permission.AGENT_EVAL)),
):
    return push_to_langsmith(name, DEFAULT_CASES)


@router.get("/jobs/{job_id}")
def enterprise_job(job_id: str, principal: Principal = Depends(require_permission(Permission.WORKFLOW_RUN))):
    rec = job_store.get_for_tenant(job_id, principal.tenant_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Job not found")
    return rec.to_dict()
