from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from core.dependencies import get_embedding_service
from enterprise.ontology_registry import ontology_registry
from enterprise.rbac import Permission, Principal, require_permission
from enterprise.tenancy import TenantContext, require_tenant
from core.config import get_settings

from services.document_ingestor import (
    UploadGroundingConfig,
    ingest_uploaded_text_document,
    retrieve_grounded_document_sections,
)


router = APIRouter(prefix="/documents", tags=["Documents"])


class GraphragRetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k_concepts: int = Field(default=5, ge=1, le=20)
    top_k_sections: int = Field(default=10, ge=1, le=50)


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    ontology_id: str = Form("hc-core"),
    ontology_version: Optional[str] = Form(None),
    source_type: str = Form("uploaded"),
    chunk_size: int = Query(1500, ge=200, le=8000),
    chunk_overlap: int = Query(200, ge=0, le=2000),
    max_chunks: int = Query(20, ge=1, le=200),
    grounding_top_k: int = Query(3, ge=1, le=25),
    grounding_min_score: float = Query(0.0, ge=0.0, le=1.0),
    tenant: TenantContext = Depends(require_tenant),
    _: Principal = Depends(require_permission(Permission.ONTOLOGY_WRITE)),
):
    """Upload a healthcare document (txt/md, .docx, or best-effort .pdf) and ground it to `OntologyConcept`s."""
    settings = get_settings()
    if not file:
        raise HTTPException(status_code=400, detail="Missing file")
    if not tenant:
        raise HTTPException(status_code=400, detail="Missing tenant context")

    if ontology_id not in (tenant.ontology_ids or []):
        raise HTTPException(
            status_code=403,
            detail=f"Tenant '{tenant.tenant_id}' is not allowed to use ontology '{ontology_id}'",
        )

    if ontology_version is None:
        rec = ontology_registry.get(ontology_id)
        ontology_version = rec.active_version if rec else ""

    # Ensure ontology vector index exists (GraphRAG grounding depends on it).
    try:
        emb = get_embedding_service()
        if hasattr(emb, "ensure_vector_index"):
            emb.ensure_vector_index()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Embedding index not available. Run POST /embedding/sync first. ({exc})",
        ) from exc

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    cfg = UploadGroundingConfig(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        max_chunks=max_chunks,
        grounding_top_k=grounding_top_k,
        grounding_min_score=grounding_min_score,
    )

    try:
        result = ingest_uploaded_text_document(
            file_bytes=content,
            filename=file.filename or f"upload-{uuid.uuid4()}",
            content_type=file.content_type or "",
            title=title or "",
            tenant_id=tenant.tenant_id,
            ontology_id=ontology_id,
            ontology_version=ontology_version or "",
            source_type=source_type,
            config=cfg,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return result


@router.post("/graphrag/retrieve")
def graphrag_retrieve(
    body: GraphragRetrieveRequest,
    tenant: TenantContext = Depends(require_tenant),
    _: Principal = Depends(require_permission(Permission.ONTOLOGY_READ)),
):
    """Retrieve document sections grounded to ontology concepts for this tenant."""
    try:
        return retrieve_grounded_document_sections(
            query=body.query,
            tenant_id=tenant.tenant_id,
            top_k_concepts=body.top_k_concepts,
            top_k_sections=body.top_k_sections,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

