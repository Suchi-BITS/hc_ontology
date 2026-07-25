from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import verify_api_key
from core.dependencies import get_embedding_service

router = APIRouter(prefix="/embedding", tags=["Embeddings"], dependencies=[Depends(verify_api_key)])


@router.post("/sync")
def embedding_sync(
    force: bool = Query(
        False,
        description="If false (default), skip concepts that already have embeddings",
    ),
):
    try:
        result = get_embedding_service().synchronize_embeddings(
            incremental=not force
        )
        status = "success" if result["failed"] == 0 else "completed_with_errors"
        return {
            "status": status,
            "processed": result["successful"],
            "failed": result["failed"],
            "skipped": result.get("skipped", 0),
            "incremental": result.get("incremental", True),
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/health")
def embedding_health():
    try:
        health = get_embedding_service().health()
        if health.get("status") != "healthy":
            raise HTTPException(
                status_code=503,
                detail=health.get("error", "Embedding service unhealthy"),
            )
        return {
            "status": health["status"],
            "model": health["model"],
            "dimensions": health["dimensions"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/search")
def embedding_search(
    query: str = Query(..., description="Semantic search over ontology concepts"),
    top_k: int = Query(5, ge=1, le=100),
):
    try:
        response = get_embedding_service().handle_search_request(
            query=query,
            top_k=top_k,
        )
        if response.get("status") == "error":
            raise HTTPException(
                status_code=503,
                detail=response.get("error", "Search failed"),
            )
        return response["results"]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/similar/{concept}")
def embedding_similar(
    concept: str,
    top_k: int = Query(5, ge=1, le=100),
):
    try:
        return get_embedding_service().find_similar_concepts(
            node_name=concept,
            top_k=top_k,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
