from fastapi import APIRouter, Depends, HTTPException

from core.auth import verify_api_key
from core.authz import Permission, require_permission
from core.security import Identity, authenticate_request
from core.dependencies import get_ontology
from core.job_store import job_store
from core.metrics import metrics

# "/" and "/health" are public on purpose (orchestrator probes carry no credentials and reveal nothing).
router = APIRouter(tags=["System"])
_AUTH = [Depends(verify_api_key)]


@router.get("/")
def home():
    return {
        "service": "Healthcare Ontology API",
        "status": "running",
        "ontology_loaded": True,
        "docs": "/docs",
    }


@router.get("/health")
def health():
    return {"status": "healthy"}


@router.get("/stats", dependencies=[*_AUTH, Depends(require_permission(Permission.ONTOLOGY_READ))])
def stats():
    ontology = get_ontology()
    return {
        "classes": len(ontology.get_classes()),
        "individuals": len(ontology.get_individuals()),
        "object_properties": len(ontology.get_object_properties()),
        "data_properties": len(ontology.get_data_properties()),
    }


@router.get("/metrics", dependencies=[*_AUTH, Depends(require_permission(Permission.METRICS_READ))])
def get_metrics():
    """Validation / LLM pipeline counters for demos and ops."""
    return metrics.snapshot()


@router.get("/jobs/{job_id}", dependencies=_AUTH)
def get_job(job_id: str, identity: Identity = Depends(authenticate_request)):
    job = job_store.get_for_tenant(job_id, identity.tenant_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()
