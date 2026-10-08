"""End-to-end: generator -> SHACL gate -> projection -> Neo4j (recording driver) -> API.

These tests run the real pipeline stages in order, with no stubs on the semantic side (real
generator, real shapes, real pySHACL, real projection). Only Neo4j itself is replaced by a
recording driver.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import XSD, Graph, Literal, Namespace
from rdflib.compare import isomorphic

import routers.neo4j as neo4j_router
from core.dataset import Dataset
from core.dependencies import get_shacl_validator
from services.graph_projection import build_projection
from services.neo4j_exporter import Neo4jExporter, ProjectionRejected
from tests.fakes import FakeDriver

ROOT = Path(__file__).resolve().parent.parent
HC = Namespace("http://example.org/healthcare-hospital.owl#")


def generate(target_dir: Path) -> "Dataset":
    """Run both generators into target_dir and return the resulting dataset."""
    target_dir.mkdir(parents=True, exist_ok=True)
    schema, data = target_dir / "schema.ttl", target_dir / "data.ttl"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_hc_ontology.py"), "--output", str(schema)],
                   check=True, capture_output=True, cwd=ROOT)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_sample_data.py"), "--output", str(data),
                    "--schema", str(schema)], check=True, capture_output=True, cwd=ROOT)
    return Dataset(schema, data)


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("pipeline"))


def test_generator_is_deterministic(generated, tmp_path):
    again = generate(tmp_path / "again")
    assert isomorphic(generated.graph(), again.graph())
    assert generated.schema.read_bytes() == again.schema.read_bytes()  # byte-for-byte, not just isomorphic
    assert generated.data.read_bytes() == again.data.read_bytes()


def test_generated_ontology_passes_the_real_shacl_gate_and_projects(generated):
    driver = FakeDriver()
    exporter = Neo4jExporter(owl_file=generated, driver=driver, database="hc", validator=get_shacl_validator())
    result = exporter.sync()
    assert result["shacl_validated"] is True and result["nodes"] == 124
    assert any("MERGE (n:Resource" in c for kind, c, _ in driver.log if kind == "tx")


def test_generated_and_committed_ontologies_project_identically(generated):
    committed = build_projection(Dataset.default())
    assert build_projection(generated).fingerprint() == committed.fingerprint()


def test_corrupt_data_is_stopped_by_the_real_gate_before_neo4j(generated, tmp_path):
    g = generated.graph()
    g.remove((HC.PatientJohn, HC.dateOfBirth, None))  # a required field disappears
    corrupt = tmp_path / "corrupt.owl"
    g.serialize(corrupt, format="xml")
    driver = FakeDriver()
    exporter = Neo4jExporter(owl_file=corrupt, driver=driver, database="hc", validator=get_shacl_validator())
    with pytest.raises(ProjectionRejected) as info:
        exporter.sync()
    assert any("PatientJohn" in p and "dateOfBirth" in p for p in info.value.problems)
    assert driver.sessions == 0, "nothing may reach the database when validation fails"


def test_wrongly_typed_value_is_stopped_by_the_real_gate(generated, tmp_path):
    g = generated.graph()
    g.remove((HC.PatientJohn, HC.dateOfBirth, None))
    g.add((HC.PatientJohn, HC.dateOfBirth, Literal("14 March 1985", datatype=XSD.string)))
    bad = tmp_path / "bad.owl"
    g.serialize(bad, format="xml")
    exporter = Neo4jExporter(owl_file=bad, driver=FakeDriver(), database="hc", validator=get_shacl_validator())
    with pytest.raises(ProjectionRejected):
        exporter.sync()


def test_rdf_answers_and_graph_answers_agree(generated):
    """Cross-layer check: the SPARQL answer and the projected graph must tell the same story."""
    rdf = generated.graph()
    sparql = {
        str(r[0]).split("#")[-1]
        for r in rdf.query(
            """PREFIX hc: <http://example.org/healthcare-hospital.owl#>
               SELECT DISTINCT ?p WHERE {
                 ?p hc:hasDiagnosis/hc:hasCode ?c . ?c hc:codeValue "E11"^^<http://www.w3.org/2001/XMLSchema#string> }"""
        )
    }
    projection = build_projection(generated)
    e11 = next(n.iri for n in projection.nodes if n.properties["name"] == "Icd10_E11")
    coded = {e.source for e in projection.edges_of("HASCODE") if e.target == e11}
    graph_side = {
        projection.node(e.source).properties["name"]
        for e in projection.edges_of("HASDIAGNOSIS") if e.target in coded
    }
    assert sparql == graph_side == {"PatientAlice", "PatientBob"}


def test_api_pipeline_validate_preview_load_agree(client, monkeypatch):
    """The three API steps describe the same data: validation, projection preview, and load."""
    validation = client.post("/validate/ontology", json={}).json()
    assert validation["summary"]["conforms"] is True and validation["summary"]["violation_count"] == 0
    assert client.get("/validation/report").json()["summary"]["data_source"] == validation["summary"]["data_source"]

    preview = client.get("/neo4j/projection").json()
    driver = FakeDriver()
    monkeypatch.setattr(
        neo4j_router, "get_neo4j_exporter",
        lambda: Neo4jExporter(owl_file=Dataset.default(), driver=driver, database="hc",
                              validator=get_shacl_validator()),
    )
    loaded = client.post("/neo4j/load").json()
    assert loaded["fingerprint"] == preview["fingerprint"]
    assert loaded["nodes"] == preview["nodes"] and loaded["relationships"] == preview["relationships"]
    # the data the API reports through the Owlready2 route matches what was projected
    assert len(client.get("/instances/Patient").json()) == 5
    assert sum(1 for k, c, p in driver.log if k == "tx" and "MERGE (n:Resource" in c) >= 1
