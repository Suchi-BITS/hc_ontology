"""Unit tests for SPARQL / Cypher query validation layers."""

from core.cypher_validator import CypherQueryValidator
from core.query_validator import find_forbidden_keywords
from core.sparql_validator import SparqlQueryValidator

CLASSES = {"Patient", "Doctor", "Diagnosis", "Medication"}
OBJ = {"hasDiagnosis", "prescribedFor", "containsMedication"}
DATA = {"firstName", "diagnosisName", "bloodGroup"}


def _sparql_v():
    return SparqlQueryValidator(
        classes=CLASSES,
        object_properties=OBJ,
        data_properties=DATA,
        default_limit=50,
    )


def _cypher_v():
    return CypherQueryValidator(
        classes=CLASSES,
        object_properties=[p.upper() for p in OBJ],
        data_properties=DATA,
        default_limit=50,
        explain_fn=None,
    )


def test_tokenize_keywords_ignores_string_literals():
    hits = find_forbidden_keywords(
        'MATCH (n) WHERE n.name = "Created2020" RETURN n',
        {"CREATE"},
    )
    assert hits == []


def test_sparql_valid_select_passes_and_injects_limit():
    q = """
    PREFIX hc: <http://example.org/healthcare-hospital.owl#>
    SELECT ?p WHERE { ?p a hc:Patient }
    """
    result = _sparql_v().run_all_checks(q)
    assert result.valid
    assert "LIMIT" in result.query.upper()


def test_sparql_write_query_rejected():
    q = """
    PREFIX hc: <http://example.org/healthcare-hospital.owl#>
    DELETE { ?s ?p ?o } WHERE { ?s ?p ?o }
    SELECT * WHERE { ?s ?p ?o }
    """
    result = _sparql_v().run_all_checks(q)
    assert result.valid is False
    assert result.stage == "safety"
    assert "DELETE" in (result.error or "")


def test_sparql_hallucinated_property_rejected():
    q = """
    PREFIX hc: <http://example.org/healthcare-hospital.owl#>
    SELECT ?p WHERE { ?p hc:hasMagicPower ?x }
    """
    result = _sparql_v().run_all_checks(q)
    assert result.valid is False
    assert result.stage in ("schema", "syntax")


def test_cypher_valid_match_passes():
    q = "MATCH (p:Patient) RETURN p.name"
    result = _cypher_v().run_all_checks(q)
    assert result.valid
    assert "LIMIT" in result.query.upper()


def test_cypher_detach_delete_rejected():
    q = "MATCH (n) DETACH DELETE n RETURN n"
    result = _cypher_v().run_all_checks(q)
    assert result.valid is False
    assert result.stage == "safety"


def test_cypher_unknown_label_rejected():
    q = "MATCH (x:Spaceship) RETURN x"
    result = _cypher_v().run_all_checks(q)
    assert result.valid is False
    assert result.stage == "schema"


def test_execute_cypher_endpoint_blocks_delete(client):
    r = client.post(
        "/execute-cypher",
        json={"cypher": "MATCH (n) DETACH DELETE n"},
    )
    assert r.status_code == 400
    body = r.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        assert detail.get("stage") == "safety"
    else:
        assert "DELETE" in str(detail).upper() or "Forbidden" in str(detail)


def test_sparql_endpoint_blocks_delete(client):
    r = client.post(
        "/sparql",
        json={
            "query": (
                "PREFIX hc: <http://example.org/healthcare-hospital.owl#> "
                "DELETE { ?s ?p ?o } WHERE { ?s ?p ?o }"
            )
        },
    )
    assert r.status_code == 400


def test_metrics_endpoint(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "counters" in r.json()
