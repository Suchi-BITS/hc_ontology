"""The Neo4j writer, the SHACL gate, the reset guards, and the HTTP surface.

Neo4j is replaced by a recording fake driver, so these tests run anywhere and prove
what *would* be sent to the database.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
import core.graph_domains as graph_domains
import routers.neo4j as neo4j_router
from services.graph_projection import ProjectionError
from services.neo4j_exporter import Neo4jExporter, ProjectionRejected
from tests.fakes import FakeDriver, Validator

ROOT = Path(__file__).resolve().parent.parent
from core.dataset import Dataset  # noqa: E402

OWL_FILE = Dataset.default()  # schema + sample data


def exporter(driver=None, validator=None, owl=OWL_FILE):
    return Neo4jExporter(owl_file=owl, driver=driver or FakeDriver(), database="hc", validator=validator or Validator())


def tx_statements(driver):
    return [(c, p) for kind, c, p in driver.log if kind == "tx"]


# ---------------------------------------------------------------------------
# Synchronization
# ---------------------------------------------------------------------------

def test_sync_writes_everything_in_one_transaction_after_schema():
    driver = FakeDriver()
    result = exporter(driver).sync()
    preflight, *rest = driver.log
    assert preflight[0] == "auto" and "none(l IN labels(n)" in preflight[1], "the first thing sent is the read-only foreign-data check"
    kinds = [k for k, _, _ in rest]
    assert kinds[:4] == ["auto"] * 4 and set(kinds[4:]) == {"tx"}   # four schema statements, then one transaction
    assert result["status"] == "success" and result["nodes"] == 124 and result["classes"] > 50
    assert result["scope"] == ["Resource", "OntologyClass", "ProjectionMeta"]
    assert re.fullmatch(r"[0-9a-f]{64}", result["fingerprint"])


def test_sync_twice_sends_the_same_logical_graph():
    def run():
        driver = FakeDriver()
        exporter(driver).sync()
        statements = tx_statements(driver)
        # the last statement is operational metadata (timestamp); everything else must match
        return [(c, p) for c, p in statements if "ProjectionMeta" not in c]

    assert run() == run()


def test_metadata_records_fingerprint_and_gate_but_data_does_not_depend_on_time():
    driver = FakeDriver()
    result = exporter(driver).sync()
    meta = next(p for c, p in tx_statements(driver) if "ProjectionMeta" in c)["meta"]
    assert meta["fingerprint"] == result["fingerprint"] and meta["shaclValidated"] is True
    assert meta["nodes"] == 124


def test_sync_only_touches_projection_labels():
    driver = FakeDriver()
    exporter(driver).sync()
    text = "\n".join(c for _, c, _ in driver.log)
    for foreign in ("AgentSession", "AgentTurn", "AgentEvent", "AgentProcedure", "OntologyConcept", "Document"):
        assert foreign not in text, foreign
    assert not re.search(r"MATCH \(n\)\s+DETACH DELETE", text)


def test_nodes_are_merged_on_iri_not_on_name():
    driver = FakeDriver()
    exporter(driver).sync()
    merges = [c for c, _ in tx_statements(driver) if "MERGE (n:Resource" in c]
    assert merges and all("{iri: row.iri}" in c and "name" not in c for c in merges)


def test_stale_labels_are_removed_and_stale_nodes_pruned():
    driver = FakeDriver()
    exporter(driver).sync()
    statements = tx_statements(driver)
    assert any("REMOVE n:" in c for c, _ in statements)
    prune = [c for c, _ in statements if "NOT n.iri IN $iris" in c]
    assert len(prune) == 2


# ---------------------------------------------------------------------------
# SHACL gate: the RDF is validated before anything reaches Neo4j
# ---------------------------------------------------------------------------

def test_rdf_that_violates_shapes_is_rejected_before_any_database_call():
    driver = FakeDriver()
    bad = Validator(violations=[("PatientX", "Patient must have a dateOfBirth.")])
    with pytest.raises(ProjectionRejected) as info:
        exporter(driver, bad).sync()
    assert "PatientX: Patient must have a dateOfBirth." in info.value.problems
    assert driver.sessions == 0 and driver.log == []


def test_validation_can_be_skipped_only_by_explicit_argument():
    driver = FakeDriver()
    validator = Validator(violations=[("PatientX", "bad")])
    exporter(driver, validator).sync(validate=False)
    assert validator.calls == 0 and driver.log


def test_real_shapes_accept_the_shipped_ontology():
    """The default gate (real pySHACL, real shapes) lets the sample ontology through."""
    from core.dependencies import get_shacl_validator

    projection = Neo4jExporter(owl_file=OWL_FILE, validator=get_shacl_validator()).plan()
    assert len(projection.nodes) == 124


def test_unparseable_rdf_is_rejected_and_nothing_is_written(tmp_path):
    bad = tmp_path / "bad.owl"
    bad.write_text("not rdf at all", encoding="utf-8")
    driver = FakeDriver()
    with pytest.raises(ProjectionError):
        exporter(driver, owl=bad).sync()
    assert driver.log == []


# ---------------------------------------------------------------------------
# Destructive operations
# ---------------------------------------------------------------------------

def _settings(env, flag):
    return lambda: {"environment": env, "allow_projection_reset": flag}


@pytest.mark.parametrize("env,flag", [("production", True), ("production", False), ("staging", True), ("development", False)])
def test_reset_is_refused_unless_development_and_explicitly_enabled(monkeypatch, env, flag):
    monkeypatch.setattr(graph_domains, "get_settings", _settings(env, flag))
    driver = FakeDriver()
    with pytest.raises(graph_domains.ResetNotAllowed):
        exporter(driver).reset_projection()
    assert driver.log == []
    assert graph_domains.reset_allowed() is False


def test_reset_in_development_removes_only_projection_labels(monkeypatch):
    monkeypatch.setattr(graph_domains, "get_settings", _settings("development", True))
    driver = FakeDriver()
    exporter(driver).reset_projection()
    statements = [c for _, c, _ in driver.log]
    assert len(statements) == 3
    assert all(re.fullmatch(r"MATCH \(n:(Resource|OntologyClass|ProjectionMeta)\) DETACH DELETE n", c) for c in statements)


def test_no_application_code_can_delete_the_whole_database():
    unscoped = re.compile(r"MATCH\s*\(\s*\w*\s*\)\s*(?:WHERE[^\n]*)?DETACH\s+DELETE", re.I)
    offenders = []
    for folder in ("services", "routers", "core", "agents", "enterprise", "scripts"):
        for path in (ROOT / folder).rglob("*.py"):
            if unscoped.search(path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(path.relative_to(ROOT)))
    # the validator's own blocklist text is a string constant, not an operation
    assert [o for o in offenders if not o.endswith(("cypher_validator.py",))] == []


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(api.app)


def test_seed_demo_endpoint_no_longer_exists(client):
    assert "/neo4j/seed-demo" not in client.get("/openapi.json").json()["paths"]
    assert client.post("/neo4j/seed-demo").status_code in (404, 405)


def test_projection_preview_touches_no_database(client):
    r = client.get("/neo4j/projection")
    assert r.status_code == 200
    body = r.json()
    assert body["nodes"] == 124 and body["authority"].startswith("ontology/healthcare_schema.ttl")
    assert body["relationship_types"]["HASDIAGNOSIS"] == 5 and body["fingerprint"]


def test_export_endpoint_returns_merge_statements_only(client):
    r = client.get("/neo4j/export")
    assert r.status_code == 200
    script = r.json()["cypher"]
    assert script and not any("DELETE" in s for s in script)


def test_load_endpoint_syncs_through_the_exporter(client, monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(neo4j_router, "get_neo4j_exporter", lambda: exporter(driver))
    r = client.post("/neo4j/load")
    assert r.status_code == 200 and r.json()["nodes"] == 124
    assert any("MERGE (n:Resource" in c for _, c, _ in driver.log)


def test_load_endpoint_returns_422_with_problems_for_invalid_rdf(client, monkeypatch):
    driver = FakeDriver()
    bad = Validator(violations=[("PatientX", "Patient must have a dateOfBirth.")])
    monkeypatch.setattr(neo4j_router, "get_neo4j_exporter", lambda: exporter(driver, bad))
    r = client.post("/neo4j/load")
    assert r.status_code == 422
    assert r.json()["detail"]["problems"] == ["PatientX: Patient must have a dateOfBirth."]
    assert driver.log == []
