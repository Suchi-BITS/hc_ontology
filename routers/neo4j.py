from fastapi import APIRouter, Depends, HTTPException, Request

from core.auth import verify_api_key
from core.authz import Permission, require_permission
from core.security import request_identity
from core.config import get_settings
from core.cypher_validator import CypherQueryValidator
from core.dependencies import (
    get_cypher_generator,
    get_neo4j_exporter,
    get_ontology,
    get_sparql_to_cypher,
)
from core.errors import from_validation_result, map_query_exception
from core.job_store import job_store
from core.metrics import metrics
from core.rate_limit import SlidingWindowRateLimiter, client_key
from core.schemas import ExecuteCypherRequest, NLQueryRequest, SparqlCypherRequest
from core.sparql_validator import SparqlQueryValidator
from services.graph_projection import ProjectionError, to_cypher_script

router = APIRouter(
    tags=["Neo4j"],
    dependencies=[Depends(verify_api_key), Depends(require_permission(Permission.QUERY_EXECUTE))],
)

_llm_limiter: SlidingWindowRateLimiter | None = None


def _limiter() -> SlidingWindowRateLimiter:
    global _llm_limiter
    if _llm_limiter is None:
        n = get_settings()["llm_rate_limit_per_minute"]
        _llm_limiter = SlidingWindowRateLimiter(max_calls=n, window_seconds=60)
    return _llm_limiter


def _cypher_validator(explain: bool = True) -> CypherQueryValidator:
    settings = get_settings()
    ontology = get_ontology()
    explain_fn = None
    if explain:
        bridge = get_sparql_to_cypher()

        def _explain(q: str):
            bridge.execute_cypher(q)

        explain_fn = _explain

    return CypherQueryValidator(
        classes=ontology.get_classes(),
        object_properties=[
            p.upper() for p in ontology.get_object_properties()
        ],
        data_properties=ontology.get_data_properties(),
        default_limit=settings["query_default_limit"],
        timeout_seconds=settings["query_timeout_seconds"],
        explain_fn=explain_fn,
    )


def _projection_error(exc: ProjectionError) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"message": str(exc), "problems": exc.problems},
    )


@router.get("/neo4j/projection")
def neo4j_projection_preview():
    """What would be loaded: counts, fingerprint and anything not projected. Touches no database.

    RDF/OWL/SHACL is the authority; Neo4j is a derived projection of it. The RDF is
    SHACL-validated first; invalid RDF is rejected with 422.
    """
    try:
        return {"authority": "ontology/healthcare_schema.ttl + data/sample_data.ttl + shapes/", **get_neo4j_exporter().plan().summary()}
    except ProjectionError as e:
        raise _projection_error(e) from e


@router.get("/neo4j/export")
def neo4j_export():
    """The projection rendered as idempotent Cypher MERGE statements (for inspection)."""
    try:
        projection = get_neo4j_exporter().plan()
        return {"fingerprint": projection.fingerprint(), "cypher": to_cypher_script(projection)}
    except ProjectionError as e:
        raise _projection_error(e) from e


@router.post("/neo4j/load", dependencies=[Depends(require_permission(Permission.GRAPH_WRITE))])
def neo4j_load():
    """Synchronize the Neo4j projection from the authoritative RDF.

    Deterministic and idempotent. Scoped to the projection labels (Resource,
    OntologyClass, ProjectionMeta): agent memory, documents and embeddings are never
    touched. There is no endpoint that clears the database.
    """
    try:
        return get_neo4j_exporter().sync()
    except ProjectionError as e:
        raise _projection_error(e) from e
    except Exception as e:
        raise map_query_exception(e) from e


@router.get("/neo4j/health")
def neo4j_health():
    try:
        return get_sparql_to_cypher().health()
    except Exception as e:
        raise map_query_exception(e) from e


@router.post("/sparql-to-cypher")
def sparql_to_cypher(request: SparqlCypherRequest):
    ontology = get_ontology()
    settings = get_settings()
    sparql_v = SparqlQueryValidator(
        classes=ontology.get_classes(),
        object_properties=ontology.get_object_properties(),
        data_properties=ontology.get_data_properties(),
        default_limit=settings["query_default_limit"],
    )
    check = sparql_v.run_all_checks(request.query)
    if not check.valid:
        metrics.incr("sparql_to_cypher_rejected")
        raise from_validation_result(check)
    try:
        # Validate generated Cypher before execute (EXPLAIN may fail if Neo4j down —
        # structural/safety/schema still run when explain_fn errors only on EXPLAIN path)
        result = get_sparql_to_cypher().query(check.query)
        cypher = result.get("cypher", "")
        cypher_v = _cypher_validator(explain=False)
        cypher_check = cypher_v.run_all_checks(cypher)
        if not cypher_check.valid:
            raise from_validation_result(cypher_check)
        # Re-execute with limit-injected query if rewritten
        if cypher_check.query != cypher:
            result["cypher"] = cypher_check.query
            result["results"] = get_sparql_to_cypher().execute_cypher(
                cypher_check.query
            )
        return result
    except Exception as e:
        if hasattr(e, "status_code"):
            raise
        raise map_query_exception(e) from e


@router.post("/nl-to-cypher")
def nl_to_cypher(request: NLQueryRequest, http_request: Request):
    _limiter().check(client_key(http_request))
    try:
        from agents.memory.preview import run_memory_debug_preview

        run_memory_debug_preview(
            request.question,
            session_id=request.session_id or "",
            source="nl-to-cypher",
        )
        return get_cypher_generator().generate_and_validate(request.question)
    except Exception as e:
        raise map_query_exception(e) from e


@router.post(
    "/nl-to-cypher/async",
    summary="Enqueue NL→Cypher job (poll GET /jobs/{id})",
)
def nl_to_cypher_async(request: NLQueryRequest, http_request: Request):
    _limiter().check(client_key(http_request))
    gen = get_cypher_generator()
    job_id = job_store.submit(
        "nl-to-cypher",
        lambda: gen.generate_and_validate(request.question),
        meta={"question": request.question},
        tenant_id=request_identity(http_request).tenant_id,
    )
    return {"job_id": job_id, "status_url": f"/jobs/{job_id}"}


@router.post("/execute-cypher")
def execute_cypher(request: ExecuteCypherRequest):
    """Execute read-only Cypher after safety/schema/limit validation."""
    # Prefer structural validation without requiring Neo4j for EXPLAIN when offline;
    # still block writes. When Neo4j is up, EXPLAIN catches syntax errors.
    try:
        validator = _cypher_validator(explain=True)
    except Exception:
        validator = _cypher_validator(explain=False)

    check = validator.run_all_checks(request.cypher)
    if not check.valid:
        metrics.incr("cypher_execute_rejected")
        raise from_validation_result(check)
    try:
        results = get_sparql_to_cypher().execute_cypher(check.query)
        metrics.incr("cypher_execute_ok")
        return {"cypher": check.query, "results": results}
    except Exception as e:
        # If EXPLAIN path caused validator init issues, map Neo4j errors
        raise map_query_exception(e) from e
