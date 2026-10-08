"""API tests: input handling, safe queries, error responses, rate limiting.

Authentication, authorization and tenant isolation are in test_security_architecture.py.

Tests marked ``xfail(strict=True)`` document KNOWN gaps. They assert the behavior the system SHOULD
have; they fail today, and strict mode turns them into a failure the day someone fixes the gap, so the
marker gets removed deliberately instead of rotting. (Seven such markers were removed when the gaps were
closed by the security hardening; none remain.)
"""

from __future__ import annotations

import pytest



# ---------------------------------------------------------------------------------------
# Invalid input and error responses
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method,path,body,field",
    [
        ("post", "/sparql", {}, "query"),
        ("post", "/execute-cypher", {}, "cypher"),
        ("post", "/llm-query", {"question": ""}, "question"),
        ("post", "/nl-to-cypher", {}, "question"),
        ("post", "/validate", {"format": "turtle"}, "data"),
        ("post", "/validate", {"data": "x", "format": "bogus"}, "format"),
    ],
)
def test_malformed_requests_are_rejected_with_a_field_level_422(client, method, path, body, field):
    response = getattr(client, method)(path, json=body)
    assert response.status_code == 422
    assert any(field in err["loc"] for err in response.json()["detail"])


def test_unparseable_rdf_is_a_client_error_not_a_server_error(client):
    response = client.post("/validate", json={"data": "this is not turtle", "format": "turtle"})
    assert response.status_code == 400 and "RDF" in response.json()["detail"]


def test_empty_upload_is_rejected(client):
    response = client.post("/validate/file", files={"file": ("empty.ttl", b"")})
    assert response.status_code == 400 and "empty" in response.json()["detail"].lower()


@pytest.mark.parametrize("path", ["/patients/Nobody", "/doctors/Nobody", "/instances/NoSuchClass"])
def test_unknown_resources_are_404_with_a_message(client, path):
    response = client.get(path)
    assert response.status_code == 404 and response.json()["detail"]


@pytest.mark.parametrize("method,path", [("delete", "/patients"), ("put", "/patients/PatientJohn"), ("post", "/classes")])
def test_write_methods_do_not_exist_on_read_resources(client, method, path):
    assert getattr(client, method)(path).status_code == 405


def test_validation_failure_shape_is_stable(client):
    detail = client.post("/sparql", json={"query": "PREFIX hc: <http://example.org/healthcare-hospital.owl#> "
                                                     "SELECT ?x WHERE { ?x hc:madeUpProperty ?y }"}).json()["detail"]
    assert set(detail) == {"message", "stage", "details"}
    assert detail["stage"] == "schema" and detail["details"]["unknown_terms"] == ["madeUpProperty"]


def test_server_errors_never_echo_credentials(client, configure):
    configure(NEO4J_PASSWORD="sentinel-secret-value", OPENAI_API_KEY="sentinel-openai-key", NEO4J_URI="bolt://127.0.0.1:1")
    for response in (client.get("/neo4j/health"), client.post("/execute-cypher", json={"cypher": "MATCH (n:Patient) RETURN n.name"})):
        assert "sentinel-secret-value" not in response.text and "sentinel-openai-key" not in response.text


# ---------------------------------------------------------------------------------------
# Forbidden operations and safe query handling
# ---------------------------------------------------------------------------------------

def test_the_whole_database_reset_endpoint_does_not_exist(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/neo4j/seed-demo" not in paths
    assert not [p for p in paths if "reset" in p or "clear" in p or "wipe" in p]


SPARQL_WRITES = [
    "INSERT DATA { <http://a> <http://b> <http://c> }",
    "DELETE WHERE { ?s ?p ?o }",
    "DROP ALL",
    "CLEAR GRAPH <http://a>",
    "LOAD <http://evil.example/data.ttl> INTO GRAPH <http://a>",
    "CREATE GRAPH <http://a>",
    "COPY DEFAULT TO <http://a>",
    "WITH <http://a> DELETE { ?s ?p ?o } WHERE { ?s ?p ?o }",
]


@pytest.mark.parametrize("update", SPARQL_WRITES)
def test_sparql_update_forms_are_rejected_before_execution(client, update):
    response = client.post("/sparql", json={"query": update})
    assert response.status_code == 400, response.text


CYPHER_WRITES = [
    "CREATE (n:Patient {name: 'x'}) RETURN n",
    "MATCH (n:Patient) SET n.name = 'x' RETURN n",
    "MATCH (n:Patient) DETACH DELETE n RETURN n",
    "MATCH (n:Patient) REMOVE n.name RETURN n",
    "MERGE (n:Patient {name: 'x'}) RETURN n",
    "MATCH (n:Patient) FOREACH (x IN [1] | SET n.a = x) RETURN n",
    "LOAD CSV FROM 'http://evil.example/x.csv' AS row MATCH (n:Patient) RETURN n",
    "MATCH (n:Patient) CALL dbms.security.listUsers() YIELD username RETURN username",
    "MATCH (n:Patient) DROP CONSTRAINT x RETURN n",
]


@pytest.mark.parametrize("cypher", CYPHER_WRITES)
def test_cypher_write_and_admin_forms_are_rejected_before_execution(client, cypher):
    response = client.post("/execute-cypher", json={"cypher": cypher})
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["stage"] in ("safety", "syntax", "schema")


def test_keywords_inside_string_values_are_not_mistaken_for_commands():
    from core.cypher_validator import CypherQueryValidator

    validator = CypherQueryValidator(classes={"Patient"}, object_properties=[], data_properties={"firstName"})
    result = validator.run_all_checks("MATCH (n:Patient) WHERE n.firstName = 'Create Delete Merge' RETURN n.name")
    assert result.valid is True


def test_cypher_procedure_calls_are_rejected():
    from core.cypher_validator import CypherQueryValidator

    validator = CypherQueryValidator(classes={"Patient"}, object_properties=[], data_properties=set())
    result = validator.run_all_checks("MATCH (n:Patient) CALL apoc.cypher.doIt('CREATE (x)', {}) YIELD value RETURN value")
    assert result.valid is False


def test_sparql_federated_service_calls_are_rejected():
    from core.sparql_validator import SparqlQueryValidator

    validator = SparqlQueryValidator(classes={"Patient"})
    result = validator.run_all_checks("SELECT ?s WHERE { SERVICE <http://evil.example/sparql> { ?s ?p ?o } }")
    assert result.valid is False


def test_validate_ontology_does_not_accept_arbitrary_server_paths(client, tmp_path):
    outside = tmp_path / "outside.owl"
    outside.write_text("not rdf", encoding="utf-8")
    response = client.post("/validate/ontology", json={"owl_path": str(outside)})
    # refused up front: the server must not even try to read (and parse) the supplied file
    assert response.status_code in (400, 403, 422) and "Failed to load RDF" not in response.text


# ---------------------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------------------

def test_rate_limiter_blocks_the_call_after_the_limit_and_recovers():
    import time

    from fastapi import HTTPException

    from core.rate_limit import SlidingWindowRateLimiter

    limiter = SlidingWindowRateLimiter(max_calls=2, window_seconds=0.2)
    limiter.check("a")
    limiter.check("a")
    with pytest.raises(HTTPException) as info:
        limiter.check("a")
    assert info.value.status_code == 429
    limiter.check("b")  # another client is unaffected
    time.sleep(0.25)
    limiter.check("a")  # the window has passed


def test_rate_limit_key_cannot_be_chosen_by_the_caller():
    from starlette.requests import Request

    from core.rate_limit import client_key

    request = Request({"type": "http", "headers": [(b"x-forwarded-for", b"1.2.3.4")], "client": ("9.9.9.9", 1)})
    assert client_key(request) == "9.9.9.9"


def test_forwarded_for_is_believed_only_from_a_trusted_proxy(configure):
    from starlette.requests import Request

    from core.rate_limit import client_key

    def request_from(peer):
        return Request({"type": "http", "headers": [(b"x-forwarded-for", b"1.2.3.4, 10.0.0.1")], "client": (peer, 1)})

    assert client_key(request_from("203.0.113.9")) == "203.0.113.9"  # untrusted peer: header ignored
    configure(TRUSTED_PROXIES="10.0.0.5, 10.0.0.6")
    assert client_key(request_from("10.0.0.5")) == "1.2.3.4"  # our proxy wrote it
    assert client_key(request_from("203.0.113.9")) == "203.0.113.9"  # still ignored from anyone else
