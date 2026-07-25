from fastapi import APIRouter, Depends, HTTPException

from core.auth import verify_api_key
from core.dependencies import get_ontology
from core.job_store import job_store
from core.metrics import metrics

router = APIRouter(tags=["System"], dependencies=[Depends(verify_api_key)])


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


@router.get("/stats")
def stats():
    ontology = get_ontology()
    return {
        "classes": len(ontology.get_classes()),
        "individuals": len(ontology.get_individuals()),
        "object_properties": len(ontology.get_object_properties()),
        "data_properties": len(ontology.get_data_properties()),
    }


@router.get("/metrics")
def get_metrics():
    """Validation / LLM pipeline counters for demos and ops."""
    return metrics.snapshot()


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()
