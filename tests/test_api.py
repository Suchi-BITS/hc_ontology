import pytest
from fastapi.testclient import TestClient

import api
from services.sparql_to_cypher import SparqlToCypher


@pytest.fixture
def client():
    return TestClient(api.app)


def test_home(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["status"] == "running"


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_classes(client):
    r = client.get("/classes")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert "Patient" in r.json()


def test_patients(client):
    r = client.get("/patients")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_ontology_search(client):
    r = client.get("/search", params={"q": "patient"})
    assert r.status_code == 200
    assert "results" in r.json()


def test_sparql_rdf_type_to_cypher():
    t = SparqlToCypher()
    cypher = t.generate_cypher(
        "SELECT ?patient WHERE { ?patient rdf:type :Patient }"
    )["cypher"]
    assert "MATCH (patient:Patient)" in cypher
    assert "RETURN patient" in cypher


def test_sparql_empty_where_raises():
    t = SparqlToCypher()
    with pytest.raises(ValueError, match="No triple patterns"):
        t.generate_cypher("SELECT ?patient WHERE { }")


def test_openapi_has_embedding_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/embedding/sync" in paths
    assert "/embedding/search" in paths
    assert "/nl-to-cypher" in paths
