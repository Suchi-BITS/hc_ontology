"""LIVE verification against a real Neo4j (for example Neo4j Desktop). OPT-IN: skipped unless RUN_LIVE_NEO4J=1.

    RUN_LIVE_NEO4J=1 NEO4J_DATABASE=neo4j python -m pytest tests/test_neo4j_live.py -v

Safety, because these tests WRITE the projection:
  * they run only when RUN_LIVE_NEO4J=1;
  * they SKIP (do not write) if the target database holds nodes outside this project's graph domains, which is
    what `Neo4jExporter.foreign_nodes()` reports; so a database already used for something else is never touched;
  * the projection is scoped to its own labels and never deletes anything else; nothing here runs DETACH DELETE.

These tests exist because a recording fake driver accepted things a real server rejects (a `Query` object passed to
`tx.run`), which made `/execute-cypher` fail against a live database.
"""

from __future__ import annotations

import os

import pytest

from core.config import get_settings
from core.dataset import Dataset
from services.graph_projection import build_projection
from services.neo4j_exporter import Neo4jExporter
from services.neo4j_verify import census, compare_projection, connection_report

pytestmark = pytest.mark.live

HC = "http://example.org/healthcare-hospital.owl#"


@pytest.fixture(scope="module")
def live():
    if os.getenv("RUN_LIVE_NEO4J") != "1":
        pytest.skip("live Neo4j tests are opt-in: set RUN_LIVE_NEO4J=1 (and NEO4J_DATABASE to an EMPTY database)")
    from core.dependencies import get_shacl_validator

    exporter = Neo4jExporter(validator=get_shacl_validator())
    try:
        exporter.driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Neo4j is not reachable: {type(exc).__name__}")
    foreign = exporter.foreign_nodes()
    if foreign["count"]:
        exporter.driver.close()
        pytest.skip(f"database '{exporter.database}' holds {foreign['count']} node(s) outside this project's graph domains; "
                    "set NEO4J_DATABASE to an empty database")
    exporter.sync()
    yield exporter
    exporter.driver.close()


@pytest.fixture(scope="module")
def projection():
    return build_projection(Dataset.default())


def rows(live, cypher, **params):
    from services.neo4j_verify import _read

    return _read(live.driver, live.database, cypher, **params)


# ---- connection --------------------------------------------------------------------------------------------------

def test_the_server_is_reachable_online_and_reports_its_version(live):
    report = connection_report(live.driver, live.database)
    assert report["problems"] == [] and report["status"] == "online"
    assert report["version"].count(".") >= 1 and report["database"] == get_settings()["neo4j_database"]


# ---- the database equals the projection ------------------------------------------------------------------------

def test_the_live_graph_equals_the_projection_of_the_rdf(live, projection):
    result = compare_projection(live.driver, live.database, projection)
    assert result["problems"] == []
    assert (result["live_nodes"], result["live_classes"], result["live_relationships"]) == (
        len(projection.nodes), len(projection.classes), len(projection.edges))


def test_loading_twice_changes_nothing(live, projection):
    before = census(live.driver, live.database)
    result = live.sync()
    assert result["fingerprint"] == projection.fingerprint()
    assert census(live.driver, live.database) == before
    assert compare_projection(live.driver, live.database, projection)["problems"] == []


def test_the_metadata_node_records_the_fingerprint_of_the_load(live, projection):
    (meta,) = rows(live, "MATCH (m:ProjectionMeta) RETURN m.fingerprint AS fp, m.shaclValidated AS validated")
    assert meta == {"fp": projection.fingerprint(), "validated": True}


# ---- identity -------------------------------------------------------------------------------------------------------

def test_identity_is_the_iri_with_a_uniqueness_constraint(live):
    constraints = {(c["labelsOrTypes"][0], tuple(c["properties"]), c["type"]) for c in
                   rows(live, "SHOW CONSTRAINTS YIELD type, labelsOrTypes, properties RETURN type, labelsOrTypes, properties")}
    assert ("Resource", ("iri",), "UNIQUENESS") in constraints
    assert rows(live, "MATCH (n:Resource) WITH n.iri AS iri, count(*) AS c WHERE c > 1 RETURN iri") == []
    assert rows(live, "MATCH (n:Resource) WHERE n.iri IS NULL RETURN n") == []


def test_one_node_per_entity_and_equal_display_names_stay_distinct(live):
    names = rows(live, "MATCH (d:Diagnosis) RETURN d.diagnosisName AS name, count(*) AS nodes, collect(d.iri) AS iris ORDER BY name")
    diabetes = next(r for r in names if r["name"] == "Diabetes")
    assert diabetes["nodes"] == 2 and sorted(diabetes["iris"]) == [HC + "DiagnosisDiabetesAlice", HC + "DiagnosisDiabetesBob"]
    (john,) = rows(live, "MATCH (n:Resource {iri: $i}) RETURN n.name AS name, labels(n) AS labels", i=HC + "PatientJohn")
    assert john["name"] == "PatientJohn" and {"Resource", "Person", "Patient"} <= set(john["labels"])


# ---- nothing collapsed -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("iri,relationship,expected", [
    ("Aspirin", "MEDICATIONCATEGORY", {"MedCategoryAnalgesic", "MedCategoryAntiplatelet"}),
    ("DiagnosisHypertension", "HASCODE", {"Icd10_I10", "Snomed_38341003"}),
    ("Prescription002", "CONTAINSMEDICATION", {"Paracetamol", "Amoxicillin"}),
])
def test_multi_valued_relationships_are_not_collapsed(live, iri, relationship, expected):
    found = rows(live, f"MATCH (:Resource {{iri: $i}})-[:{relationship}]->(t) RETURN t.name AS name", i=HC + iri)
    assert {r["name"] for r in found} == expected and len(found) == len(expected)


def test_participants_and_identifiers_survive(live):
    assert {r["who"] for r in rows(live, "MATCH (p)-[:PARTICIPATESIN]->(:Resource {iri: $i}) RETURN p.name AS who", i=HC + "Encounter001")} == {"DrSmith", "NurseMary"}
    assert {r["v"] for r in rows(live, "MATCH (:Doctor)-[:HASIDENTIFIER]->(i) RETURN i.identifierValue AS v")} == {"DOC1001", "DOC1002", "DOC1003", "DOC1004"}
    assert rows(live, "MATCH (p:Patient)-[:HASALLERGY]->()-[:ALLERGYTOMEDICATION]->(m) RETURN p.name AS p, m.name AS m") == [{"p": "PatientBob", "m": "Amoxicillin"}]


# ---- semantics ---------------------------------------------------------------------------------------------------------

def test_the_class_hierarchy_is_projected(live):
    assert rows(live, "MATCH (p:Person) RETURN count(p) AS c") == [{"c": 11}]          # 5 patients + 4 doctors + 2 nurses
    chain = rows(live, "MATCH p=(c:OntologyClass {name:'Doctor'})-[:SUBCLASS_OF*]->(s) RETURN [x IN nodes(p) | x.name] AS chain ORDER BY length(p) DESC LIMIT 1")
    assert chain == [{"chain": ["Doctor", "Practitioner", "Person"]}]
    assert rows(live, "MATCH (:Resource {iri:$i})-[:INSTANCE_OF]->(c) RETURN c.name AS c", i=HC + "PatientJohn") == [{"c": "Patient"}]


def test_inverse_edges_are_projected_and_marked_inferred(live):
    (row,) = rows(live, "MATCH (p:Resource {iri:$p})-[a:HASALLERGY]->(al)-[b:ALLERGYFORPATIENT]->(p) RETURN a.inferred AS fwd, b.inferred AS inv", p=HC + "PatientBob")
    assert row == {"fwd": None, "inv": True}


def test_datatype_properties_keep_their_types(live):
    (row,) = rows(live, "MATCH (p:Resource {iri:$p}), (e:Resource {iri:$e}), (o:Resource {iri:$o}) "
                        "RETURN valueType(p.dateOfBirth) AS dob, valueType(e.encounterStart) AS start, valueType(o.observationValue) AS val",
                  p=HC + "PatientJohn", e=HC + "Encounter001", o=HC + "Observation001")
    assert row == {"dob": "DATE NOT NULL", "start": "ZONED DATETIME NOT NULL", "val": "FLOAT NOT NULL"}


def test_rdf_remains_the_authority_the_database_is_derived(live, projection):
    """Destroy nothing, but show the relationship: the fingerprint in Neo4j is the RDF's, not the other way round."""
    (meta,) = rows(live, "MATCH (m:ProjectionMeta) RETURN m.fingerprint AS fp")
    assert meta["fp"] == projection.fingerprint() == build_projection(Dataset.default()).fingerprint()


# ---- domain boundary -------------------------------------------------------------------------------------------------------

def test_the_projection_shares_no_edge_with_any_other_graph_domain(live):
    assert rows(live, "MATCH (a)-[r]-(b) WHERE (a:Resource OR a:OntologyClass) AND NOT (b:Resource OR b:OntologyClass) RETURN count(r) AS c") == [{"c": 0}]


# ---- the database itself enforces read-only ----------------------------------------------------------------------------------

def test_a_read_access_session_cannot_write_whatever_the_application_checks_say(live):
    from neo4j import READ_ACCESS
    from neo4j.exceptions import ClientError

    with live.driver.session(database=live.database, default_access_mode=READ_ACCESS) as session:
        with pytest.raises(ClientError):
            session.run("CREATE (:LiveTestMustNeverExist)").consume()
    assert rows(live, "MATCH (n:LiveTestMustNeverExist) RETURN count(n) AS c") == [{"c": 0}]


# ---- API -> live Neo4j, and the security controls ------------------------------------------------------------------------------

def first_value(response):
    return int(next(iter(response.json()["results"][0].values())))


def test_the_api_reads_the_live_graph(live, client, secure):
    health = client.get("/neo4j/health", headers=secure.h("operator"))
    assert health.status_code == 200 and health.json()["database"] == live.database
    assert health.json()["nodes"] == connection_report(live.driver, live.database)["nodes"]
    response = client.post("/execute-cypher", json={"cypher": "MATCH (p:Patient) RETURN count(p) AS patients"}, headers=secure.h("operator"))
    assert response.status_code == 200 and first_value(response) == 5


def test_authentication_and_authorization_hold_against_the_live_database(live, client, secure):
    assert client.get("/neo4j/health").status_code == 401
    assert client.post("/neo4j/load").status_code == 401
    assert client.post("/neo4j/load", headers=secure.h("reader")).status_code == 403
    assert client.post("/neo4j/load", headers={**secure.h("reader"), "X-Role": "platform_admin"}).status_code == 403
    assert client.post("/execute-cypher", json={"cypher": "MATCH (p:Patient) RETURN count(p)"}, headers=secure.h("reader")).status_code == 403


@pytest.mark.parametrize("cypher", [
    "MATCH (n) DETACH DELETE n",
    "MATCH (n) RETURN n LIMIT 1; MATCH (m) DETACH DELETE m",
    "MATCH (n:Patient) SET n.pwned = true RETURN n",
    "MATCH p=(a:Patient)-[*]->(b) RETURN p",
    "CALL dbms.listConfig() YIELD name RETURN name",
    "LOAD CSV FROM 'http://example.com/x.csv' AS row RETURN row",
])
def test_destructive_and_unsafe_cypher_is_refused_before_it_reaches_the_database(live, client, secure, cypher):
    before = connection_report(live.driver, live.database)["nodes"]
    response = client.post("/execute-cypher", json={"cypher": cypher}, headers=secure.h("operator"))   # even a platform admin
    assert response.status_code in (400, 422)
    assert connection_report(live.driver, live.database)["nodes"] == before


def test_an_expensive_query_is_terminated_by_the_database_and_the_api_carries_on(live, client, secure, configure):
    configure(QUERY_TIMEOUT_SECONDS="1")
    heavy = "MATCH (a),(b),(c),(d) WHERE a.iri < b.iri AND b.iri < c.iri AND c.iri < d.iri RETURN count(*) AS n"
    response = client.post("/execute-cypher", json={"cypher": heavy}, headers=secure.h("operator"))
    assert response.status_code == 504 and "terminated by the database" in response.text
    for leak in ("Neo.ClientError", "neo4j_code", "Traceback"):
        assert leak not in response.text
    configure(QUERY_TIMEOUT_SECONDS="30")
    again = client.post("/execute-cypher", json={"cypher": "MATCH (p:Patient) RETURN count(p) AS patients"}, headers=secure.h("operator"))
    assert again.status_code == 200 and first_value(again) == 5


def test_sparql_is_answered_from_the_rdf_not_from_neo4j(live, client, secure):
    response = client.post("/sparql", json={"query": "PREFIX hc: <http://example.org/healthcare-hospital.owl#> SELECT ?p WHERE { ?p a hc:Patient }"},
                           headers=secure.h("operator"))
    assert response.status_code == 200 and len(response.json()["results"]) == 5
