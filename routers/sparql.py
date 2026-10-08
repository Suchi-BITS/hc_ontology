from fastapi import APIRouter, Depends, HTTPException, Request, Response

from core.auth import verify_api_key
from core.authz import Permission, require_permission
from core.security import request_identity
from core.config import get_settings
from core.dependencies import get_ontology, get_sparql_generator
from core.errors import from_validation_result, map_query_exception
from core.job_store import job_store
from core.metrics import metrics
from core.rate_limit import SlidingWindowRateLimiter, client_key
from core.schemas import LLMQueryRequest, NLQueryRequest, SparqlRequest
from core.sparql_validator import SparqlQueryValidator

router = APIRouter(
    tags=["SPARQL"],
    dependencies=[Depends(verify_api_key), Depends(require_permission(Permission.QUERY_EXECUTE))],
)

_llm_limiter: SlidingWindowRateLimiter | None = None


def _limiter() -> SlidingWindowRateLimiter:
    global _llm_limiter
    if _llm_limiter is None:
        n = get_settings()["llm_rate_limit_per_minute"]
        _llm_limiter = SlidingWindowRateLimiter(max_calls=n, window_seconds=60)
    return _llm_limiter


def _sparql_validator_for_ontology(ontology) -> SparqlQueryValidator:
    settings = get_settings()
    return SparqlQueryValidator(
        classes=ontology.get_classes(),
        object_properties=ontology.get_object_properties(),
        data_properties=ontology.get_data_properties(),
        default_limit=settings["query_default_limit"],
        timeout_seconds=settings["query_timeout_seconds"],
    )


@router.post("/sparql")
def sparql_query(request: SparqlRequest):
    ontology = get_ontology()
    validator = _sparql_validator_for_ontology(ontology)
    check = validator.run_all_checks(request.query)
    if not check.valid:
        metrics.incr("sparql_api_rejected")
        raise from_validation_result(check)
    try:
        # execute_sparql enforces SPARQL_QUERY_TIMEOUT_SECONDS by terminating a worker process
        # (core/sparql_exec.py); SparqlTimeout is a TimeoutError and is mapped to 504 below.
        results = ontology.execute_sparql(check.query)
        metrics.incr("sparql_api_ok")
        return {"sparql": check.query, "results": results}
    except Exception as e:
        raise map_query_exception(e) from e


@router.post(
    "/llm-query",
    summary="Natural language to SPARQL (recommended)",
)
def llm_query(request: LLMQueryRequest, http_request: Request):
    _limiter().check(client_key(http_request))
    try:
        return get_sparql_generator().generate_and_validate(request.question)
    except Exception as e:
        raise map_query_exception(e) from e


@router.post(
    "/llm-query/async",
    summary="Enqueue NL→SPARQL job (poll GET /jobs/{id})",
)
def llm_query_async(request: LLMQueryRequest, http_request: Request):
    _limiter().check(client_key(http_request))
    gen = get_sparql_generator()
    job_id = job_store.submit(
        "llm-query",
        lambda: gen.generate_and_validate(request.question),
        meta={"question": request.question},
        tenant_id=request_identity(http_request).tenant_id,
    )
    return {"job_id": job_id, "status_url": f"/jobs/{job_id}"}


@router.post(
    "/nl-query",
    summary="Alias for /llm-query (legacy)",
    deprecated=True,
)
def nl_query(request: NLQueryRequest, http_request: Request, response: Response):
    """Deprecated: use POST /llm-query instead."""
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Sat, 01 Aug 2026 00:00:00 GMT"
    response.headers["Link"] = '</llm-query>; rel="successor-version"'
    _limiter().check(client_key(http_request))
    try:
        return get_sparql_generator().generate_and_validate(request.question)
    except Exception as e:
        raise map_query_exception(e) from e
