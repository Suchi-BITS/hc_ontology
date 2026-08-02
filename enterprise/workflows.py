"""Background workflow definitions (multi-step async jobs)."""

from __future__ import annotations

import logging
from typing import Any, Callable

from core.job_store import job_store
from enterprise.cost import cost_tracker
from enterprise.hybrid_retrieval import hybrid_retrieve
from enterprise.monitoring import monitor

logger = logging.getLogger("healthcare_ontology.workflows")


def workflow_embedding_refresh(tenant_id: str = "default") -> dict[str, Any]:
    from core.dependencies import get_embedding_service

    monitor.incr("workflow_embedding_refresh")
    cost_tracker.record(tenant_id, "embedding_call", units=10, meta={"workflow": "embedding_refresh"})
    svc = get_embedding_service()
    if hasattr(svc, "sync"):
        result = svc.sync()
    elif hasattr(svc, "sync_embeddings"):
        result = svc.sync_embeddings()
    else:
        # Best-effort common method names
        for name in ("sync_to_neo4j", "index_ontology", "run_sync"):
            if hasattr(svc, name):
                result = getattr(svc, name)()
                break
        else:
            result = {"status": "skipped", "reason": "No sync method on EmbeddingService"}
    return {"tenant_id": tenant_id, "result": result}


def workflow_hybrid_warmup(question: str, tenant_id: str = "default") -> dict[str, Any]:
    monitor.incr("workflow_hybrid_warmup")
    cost_tracker.record(tenant_id, "embedding_call", units=1, meta={"workflow": "hybrid_warmup"})
    return hybrid_retrieve(question, top_k=5)


def workflow_ontology_health(tenant_id: str = "default") -> dict[str, Any]:
    from enterprise.ontology_registry import ontology_registry
    from enterprise.tenancy import tenant_registry

    tenant = tenant_registry.get(tenant_id)
    ontologies = ontology_registry.list(tenant_id=tenant_id)
    return {
        "tenant": tenant.tenant_id if tenant else tenant_id,
        "ontology_count": len(ontologies),
        "ontologies": [
            {
                "id": o.ontology_id,
                "active_version": o.active_version,
                "versions": len(o.versions),
            }
            for o in ontologies
        ],
    }


WORKFLOWS: dict[str, Callable[..., dict[str, Any]]] = {
    "embedding_refresh": workflow_embedding_refresh,
    "hybrid_warmup": workflow_hybrid_warmup,
    "ontology_health": workflow_ontology_health,
}


def enqueue_workflow(name: str, **kwargs: Any) -> str:
    if name not in WORKFLOWS:
        raise KeyError(f"Unknown workflow: {name}")
    fn = WORKFLOWS[name]
    return job_store.submit(f"workflow:{name}", lambda: fn(**kwargs), meta={"workflow": name, **kwargs})
