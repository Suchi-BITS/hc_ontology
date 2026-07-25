from fastapi import APIRouter, Depends, Request

from core.auth import verify_api_key
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

router = APIRouter(tags=["Neo4j"], dependencies=[Depends(verify_api_key)])

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


@router.get("/neo4j/export")
def neo4j_export():
    return {"cypher": get_ontology().export_neo4j_cypher()}


@router.post("/neo4j/load")
def neo4j_load():
    """Load OWL individuals, properties, and relationships into Neo4j."""
    try:
        return get_neo4j_exporter().export()
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
