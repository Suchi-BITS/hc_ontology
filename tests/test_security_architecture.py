"""Security architecture tests: identity, authorization, tenancy, query execution, destructive operations.

The scenario used throughout: tenant "Abhigya AI Lab" (`abhigya-ai-lab`) and its user Suchismita (admin),
plus a read-only colleague, an analyst, a user of a different tenant, a platform operator, and a user
whose tenant does not exist. Their credentials live in a server-side file created by the `secure`
fixture; nothing a request sends can create or change them.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

import routers.neo4j as neo4j_router
from core.authz import ROLE_PERMISSIONS, Permission, principal_for
from core.cypher_policy import CypherPolicyViolation, check_read_only
from core.security import (
    ApiKeyAuthenticator,
    CredentialStore,
    Identity,
    SecurityConfigurationError,
    hash_key,
    security_mode,
    validate_security_configuration,
)
from enterprise.tenancy import tenant_registry
from services.neo4j_exporter import Neo4jExporter
from tests.fakes import FakeDriver, Validator

ROOT = Path(__file__).resolve().parent.parent
from core.dataset import Dataset  # noqa: E402

OWL_FILE = Dataset.default()  # schema + sample data


# ---------------------------------------------------------------------------------------------
# 1. Authentication: identity comes from a server-side credential, nothing else
# ---------------------------------------------------------------------------------------------

AUTHENTICATED = [
    ("get", "/patients", None),
    ("get", "/classes", None),
    ("get", "/stats", None),
    ("get", "/metrics", None),
    ("post", "/sparql", {"query": "SELECT ?s WHERE { ?s ?p ?o }"}),
    ("post", "/validate", {"data": "@prefix a: <http://a#> .", "format": "turtle"}),
    ("get", "/neo4j/projection", None),
    ("post", "/neo4j/load", None),
    ("post", "/execute-cypher", {"cypher": "MATCH (n) RETURN n"}),
    ("get", "/enterprise/ontologies", None),
    ("get", "/agent/memory/episodes/search?q=x", None),
]


@pytest.mark.parametrize("method,path,body", AUTHENTICATED, ids=[f"{m} {p}" for m, p, _ in AUTHENTICATED])
def test_every_data_endpoint_refuses_anonymous_and_unknown_callers(client, secure, method, path, body):
    call = getattr(client, method)
    kwargs = {"json": body} if body is not None else {}
    assert call(path, **kwargs).status_code == 401
    assert call(path, headers={"X-API-Key": "hck_not-a-real-key"}, **kwargs).status_code == 401
    assert call(path, headers={"Authorization": "Bearer hck_not-a-real-key"}, **kwargs).status_code == 401


def test_health_probes_are_public_and_reveal_nothing(client, secure):
    assert client.get("/health").json() == {"status": "healthy"}
    assert client.get("/").status_code == 200
    assert "patients" not in client.get("/").text.lower()


def test_a_valid_key_works_as_header_or_bearer_token(client, secure):
    key = secure.keys["suchismita"]
    assert client.get("/patients", headers={"X-API-Key": key}).status_code == 200
    assert client.get("/patients", headers={"Authorization": f"Bearer {key}"}).status_code == 200


def test_the_response_to_a_bad_key_does_not_help_the_attacker(client, secure):
    response = client.get("/patients", headers={"X-API-Key": "hck_guess"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing credentials"}
    assert response.headers["www-authenticate"] == "Bearer"
    for key in secure.keys.values():
        assert key not in response.text


def test_only_hashes_are_stored_server_side(secure):
    stored = json.loads(secure.path.read_text(encoding="utf-8"))["credentials"]
    text = secure.path.read_text(encoding="utf-8")
    for user, key in secure.keys.items():
        assert key not in text
        assert any(r["key_sha256"] == hash_key(key) for r in stored)


def test_authentication_resolves_identity_tenant_and_role_from_the_credential(secure):
    from starlette.requests import Request

    store = CredentialStore.load()
    auth = ApiKeyAuthenticator(store)

    def request_with(key):
        return Request({"type": "http", "headers": [(b"x-api-key", key.encode())], "client": ("127.0.0.1", 1)})

    me = auth.authenticate(request_with(secure.keys["suchismita"]))
    assert (me.subject, me.tenant_id, me.role, me.display_name) == ("suchismita", "abhigya-ai-lab", "admin", "Suchismita")
    assert auth.authenticate(Request({"type": "http", "headers": [], "client": None})) is None


def test_a_credential_cannot_be_forged_by_editing_the_hash_it_does_not_know(secure):
    store = CredentialStore.load()
    assert store.find(secure.keys["suchismita"]).credential_id == "suchismita"
    assert store.find(hash_key(secure.keys["suchismita"])) is None  # the hash itself is not a key


def test_the_shared_api_key_maps_to_one_least_privilege_server_side_identity(client, configure):
    configure(API_CREDENTIALS_FILE="", API_KEY="shared-secret", API_KEY_ROLE="viewer", DEFAULT_TENANT_ID="abhigya-ai-lab")
    assert security_mode() == "enforced"
    assert client.get("/patients").status_code == 401
    ok = {"X-API-Key": "shared-secret", "X-Role": "admin"}  # the forged role is ignored
    assert client.get("/patients", headers=ok).status_code == 200
    assert client.post("/neo4j/load", headers=ok).status_code == 403  # a viewer cannot write


# ---------------------------------------------------------------------------------------------
# 2. Forged X-Role: the role comes from the credential, never from the request
# ---------------------------------------------------------------------------------------------

def test_a_forged_admin_role_header_grants_nothing(client, secure):
    forged = secure.h("reader", X_Role="admin")
    assert client.post("/neo4j/load", headers=forged).status_code == 403
    assert client.post("/embedding/sync", headers=forged).status_code == 403
    assert client.post("/enterprise/tenants", json={"tenant_id": "taken-over"}, headers=forged).status_code == 403
    assert tenant_registry.get("taken-over") is None


def test_a_forged_role_cannot_even_elevate_a_real_admin_to_platform_admin(client, secure):
    response = client.post("/enterprise/tenants", json={"tenant_id": "grab"}, headers=secure.h("suchismita", X_Role="platform_admin"))
    assert response.status_code == 403
    assert tenant_registry.get("grab") is None


def test_the_role_header_is_ignored_in_both_directions(client, secure):
    """A header cannot demote a real admin either: the credential alone decides."""
    assert client.get("/enterprise/workflows", headers=secure.h("suchismita", X_Role="viewer")).status_code == 200
    assert client.get("/enterprise/workflows", headers=secure.h("reader", X_Role="admin")).status_code == 403


def test_a_forged_role_is_logged_for_investigation(client, secure, caplog):
    with caplog.at_level(logging.WARNING, logger="healthcare_ontology.security"):
        client.get("/patients", headers=secure.h("reader", X_Role="admin"))
    assert any("ignored untrusted X-Role header 'admin'" in r.message and "reader" in r.message for r in caplog.records)


def test_a_role_name_the_server_does_not_know_gets_least_privilege():
    principal = principal_for(Identity(subject="x", tenant_id="t", role="superuser"))
    assert principal.role == "viewer" and principal.permissions == ROLE_PERMISSIONS["viewer"]


def test_permissions_are_a_server_side_table_with_the_expected_shape():
    assert Permission.GRAPH_WRITE not in ROLE_PERMISSIONS["analyst"] | ROLE_PERMISSIONS["viewer"]
    assert Permission.QUERY_EXECUTE not in ROLE_PERMISSIONS["viewer"]
    assert Permission.PLATFORM_ADMIN in ROLE_PERMISSIONS["platform_admin"]
    assert Permission.PLATFORM_ADMIN not in ROLE_PERMISSIONS["admin"]


# ---------------------------------------------------------------------------------------------
# 3. Forged tenant: the tenant is the identity's, never the request's
# ---------------------------------------------------------------------------------------------

def test_the_tenant_comes_from_the_identity_when_the_request_names_none(client, secure):
    body = client.get("/enterprise/ontologies", headers=secure.h("suchismita")).json()
    assert body["tenant_id"] == "abhigya-ai-lab"
    assert [o["ontology_id"] for o in body["ontologies"]] == ["hc-core"]


def test_a_forged_tenant_header_is_refused_not_obeyed(client, secure):
    response = client.get("/enterprise/ontologies", headers=secure.h("suchismita", X_Tenant_ID="research"))
    assert response.status_code == 403
    assert "hc-research" not in response.text


def test_a_forged_tenant_query_parameter_is_refused_too(client, secure):
    response = client.get("/enterprise/ontologies", params={"tenant_id": "research"}, headers=secure.h("suchismita"))
    assert response.status_code == 403


def test_naming_your_own_tenant_is_harmless(client, secure):
    response = client.get("/enterprise/ontologies", headers=secure.h("suchismita", X_Tenant_ID="abhigya-ai-lab"))
    assert response.status_code == 200 and response.json()["tenant_id"] == "abhigya-ai-lab"


def test_a_forged_tenant_is_refused_on_agent_and_document_endpoints(client, secure):
    forged = secure.h("suchismita", X_Tenant_ID="research")
    assert client.get("/agent/memory/episodes/search", params={"q": "x"}, headers=forged).status_code == 403
    assert client.post("/documents/graphrag/retrieve", json={"query": "diabetes"}, headers=forged).status_code == 403


def test_a_tenant_mismatch_is_logged(client, secure, caplog):
    with caplog.at_level(logging.WARNING, logger="healthcare_ontology.security"):
        client.get("/enterprise/ontologies", headers=secure.h("suchismita", X_Tenant_ID="research"))
    assert any("tenant mismatch refused" in r.message and "suchismita" in r.message for r in caplog.records)


def test_an_identity_whose_tenant_does_not_exist_gets_nothing(client, secure):
    assert client.get("/enterprise/ontologies", headers=secure.h("ghost")).status_code == 403


def test_a_deactivated_tenant_locks_out_its_users(client, secure):
    tenant = tenant_registry.get("abhigya-ai-lab")
    tenant.active = False
    try:
        assert client.get("/enterprise/ontologies", headers=secure.h("suchismita")).status_code == 403
    finally:
        tenant.active = True


# ---------------------------------------------------------------------------------------------
# 4. Cross-tenant access
# ---------------------------------------------------------------------------------------------

def test_one_tenant_cannot_read_anothers_ontology_by_id(client, secure):
    assert client.get("/enterprise/ontologies/hc-research", headers=secure.h("suchismita")).status_code == 404
    assert client.get("/enterprise/ontologies/hc-research", headers=secure.h("outsider")).status_code == 200
    assert client.get("/enterprise/ontologies/hc-core", headers=secure.h("suchismita")).status_code == 200


def test_one_tenants_admin_cannot_publish_or_activate_another_tenants_ontology(client, secure):
    body = {"version": "9.9.9", "owl_path": "ontology/healthcare_schema.ttl", "changelog": "hostile", "activate": True}
    assert client.post("/enterprise/ontologies/hc-research/versions", json=body, headers=secure.h("suchismita")).status_code == 404
    assert client.post("/enterprise/ontologies/hc-research/activate/1.0.0", headers=secure.h("suchismita")).status_code == 404


def test_a_tenant_sees_only_itself_in_the_tenant_catalog(client, secure):
    mine = client.get("/enterprise/tenants", headers=secure.h("suchismita")).json()["tenants"]
    assert [t["tenant_id"] for t in mine] == ["abhigya-ai-lab"]
    everything = client.get("/enterprise/tenants", headers=secure.h("operator")).json()["tenants"]
    assert {"abhigya-ai-lab", "research", "default", "clinic-a"} <= {t["tenant_id"] for t in everything}


def test_only_a_platform_operator_can_create_tenants(client, secure):
    body = {"tenant_id": "new-lab", "display_name": "New Lab", "ontology_ids": ["hc-core"]}
    assert client.post("/enterprise/tenants", json=body, headers=secure.h("suchismita")).status_code == 403  # tenant admin
    try:
        assert client.post("/enterprise/tenants", json=body, headers=secure.h("operator")).status_code == 200
    finally:
        tenant_registry._tenants.pop("new-lab", None)


def test_jobs_belong_to_the_tenant_that_started_them(client, secure):
    from core.job_store import job_store

    job_id = job_store.submit("test", lambda: {"secret": "abhigya-only"}, tenant_id="abhigya-ai-lab")
    for _ in range(50):
        if job_store.get(job_id).status == "completed":
            break
    mine = client.get(f"/jobs/{job_id}", headers=secure.h("suchismita"))
    theirs = client.get(f"/jobs/{job_id}", headers=secure.h("outsider"))
    assert mine.status_code == 200 and mine.json()["result"] == {"secret": "abhigya-only"}
    assert theirs.status_code == 404 and "abhigya-only" not in theirs.text  # looks like a missing job


def test_a_workflow_runs_for_the_callers_tenant_whatever_the_body_says(client, secure):
    response = client.post(
        "/enterprise/workflows/run",
        json={"name": "ontology_health", "params": {"tenant_id": "research"}},
        headers=secure.h("suchismita"),
    )
    assert response.status_code == 200, response.text
    from core.job_store import job_store

    job = job_store.get(response.json()["job_id"])
    assert job.tenant_id == "abhigya-ai-lab" and job.meta["tenant_id"] == "abhigya-ai-lab"
    assert client.get(response.json()["status_url"].replace("/jobs/", "/enterprise/jobs/"), headers=secure.h("research-admin")).status_code == 404


def test_the_ontology_catalog_of_each_tenant_is_disjoint_where_it_should_be(client, secure):
    abhigya = {o["ontology_id"] for o in client.get("/enterprise/ontologies", headers=secure.h("suchismita")).json()["ontologies"]}
    research = {o["ontology_id"] for o in client.get("/enterprise/ontologies", headers=secure.h("outsider")).json()["ontologies"]}
    assert abhigya == {"hc-core"} and research == {"hc-core", "hc-research"}


# ---------------------------------------------------------------------------------------------
# 5. Unauthorized writes
# ---------------------------------------------------------------------------------------------

WRITES = [
    ("post", "/neo4j/load", None),
    ("post", "/embedding/sync", None),
    ("post", "/enterprise/tenants", {"tenant_id": "x"}),
    ("post", "/enterprise/ontologies/hc-core/versions", {"version": "9.9.9", "changelog": "x"}),
    ("post", "/enterprise/workflows/run", {"name": "ontology_health"}),
]


@pytest.mark.parametrize("user", ["reader", "analyst"])
@pytest.mark.parametrize("method,path,body", WRITES, ids=[p for _, p, _ in WRITES])
def test_viewers_and_analysts_cannot_perform_write_operations(client, secure, user, method, path, body):
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(path, headers=secure.h(user), **kwargs)
    assert response.status_code == 403
    assert response.json()["detail"].startswith(f"Role '{'viewer' if user == 'reader' else 'analyst'}' lacks permission")


def test_a_viewer_can_read_clinical_data_but_cannot_run_queries(client, secure):
    reader = secure.h("reader")
    assert client.get("/patients", headers=reader).status_code == 200
    assert client.post("/sparql", json={"query": "SELECT ?s WHERE { ?s ?p ?o }"}, headers=reader).status_code == 403
    assert client.post("/execute-cypher", json={"cypher": "MATCH (n) RETURN n"}, headers=reader).status_code == 403


def test_an_analyst_can_query_but_not_write(client, secure):
    analyst = secure.h("analyst")
    assert client.post("/sparql", json={"query": "SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"}, headers=analyst).status_code == 200
    assert client.post("/neo4j/load", headers=analyst).status_code == 403


def test_an_admin_is_authorized_to_load_the_projection(client, secure, monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(neo4j_router, "get_neo4j_exporter",
                        lambda: Neo4jExporter(owl_file=OWL_FILE, driver=driver, database="hc", validator=Validator()))
    response = client.post("/neo4j/load", headers=secure.h("suchismita"))
    assert response.status_code == 200 and driver.log


def test_authorization_is_enforced_before_any_work_is_done(client, secure, monkeypatch):
    called = []
    monkeypatch.setattr(neo4j_router, "get_neo4j_exporter", lambda: called.append("exporter") or None)
    assert client.post("/neo4j/load", headers=secure.h("reader")).status_code == 403
    assert called == []


def test_switching_rbac_off_works_only_in_development(client, secure, configure):
    configure(RBAC_ENABLED="false", ENVIRONMENT="development")
    assert client.post("/enterprise/tenants", json={"tenant_id": "t1"}, headers=secure.h("reader")).status_code in (200, 422)
    tenant_registry._tenants.pop("t1", None)
    configure(RBAC_ENABLED="false", ENVIRONMENT="production")  # ignored: authorization still applies
    assert client.post("/enterprise/tenants", json={"tenant_id": "t2"}, headers=secure.h("reader")).status_code == 403


# ---------------------------------------------------------------------------------------------
# 6. Cypher injection and procedure invocation
# ---------------------------------------------------------------------------------------------

INJECTIONS = [
    "MATCH (n:Patient) WHERE n.name = 'x' RETURN n UNION MATCH (m) DETACH DELETE m",
    "MATCH (n:Patient) WHERE n.name = '' OR true WITH n MATCH (m) SET m.pwned = true RETURN n",
    "MATCH (n:`Patient`) RETURN n; MATCH (m) DETACH DELETE m",
    "MATCH (n) RETURN n // ; DETACH DELETE n",
    "MATCH (n) RETURN n /* */ UNION MATCH (m) DELETE m",
    "MATCH (n:Patient {name: 'x'}) RETURN n\nCREATE (z:Pwned)",
    "MATCH (n) WHERE n.name = $name RETURN n",
    "ＭＡＴＣＨ (n) ＤＥＬＥＴＥ n",
    "MATCH (n) RETURN n LIMIT 1 SET n.x = 1",
    "MATCH (n) WITH n LIMIT 1 FOREACH (x IN [1] | SET n.x = x) RETURN n",
]

PROCEDURES = [
    "CALL db.labels() YIELD label RETURN label",
    "CALL dbms.security.listUsers() YIELD username RETURN username",
    "MATCH (n) CALL apoc.cypher.doIt('CREATE (x)', {}) YIELD value RETURN value",
    "MATCH (n) RETURN apoc.text.join(['a','b'], ',')",
    "MATCH (n) RETURN dbms.listConfig()",
    "MATCH (n) CALL { MATCH (m) RETURN m } RETURN n",
    "MATCH (n) CALL db.index.vector.queryNodes('i', 5, [0.1]) YIELD node RETURN node",
    "LOAD CSV FROM 'http://evil.example/x.csv' AS row MATCH (n) RETURN n",
    "USE system MATCH (n) RETURN n",
    "SHOW USERS",
    "MATCH (n) RETURN n.name, apoc.load.json('http://evil.example/x')",
]


@pytest.mark.parametrize("cypher", INJECTIONS)
def test_injection_payloads_are_refused_by_the_policy_and_the_endpoint(client, secure, cypher):
    assert check_read_only(cypher).allowed is False
    response = client.post("/execute-cypher", json={"cypher": cypher}, headers=secure.h("analyst"))
    assert response.status_code == 400
    assert response.json()["detail"]["stage"] in ("safety", "schema", "syntax")


@pytest.mark.parametrize("cypher", PROCEDURES)
def test_no_procedure_or_admin_command_can_be_invoked_from_a_user_query(client, secure, cypher):
    result = check_read_only(cypher)
    assert result.allowed is False and result.violations
    response = client.post("/execute-cypher", json={"cypher": cypher}, headers=secure.h("analyst"))
    assert response.status_code == 400


READ_QUERIES = [
    "MATCH (p:Patient)-[:HASCONDITION]->(c:Condition) RETURN p.name, c.diagnosisName",
    "MATCH (d:Doctor) WHERE d.name CONTAINS 'Smith' RETURN count(d) AS n",
    "MATCH (a)-[:CONTAINSWARD|CONTAINSROOM*1..3]->(b) RETURN DISTINCT b.name ORDER BY b.name LIMIT 10",
    "EXPLAIN MATCH (n:Patient) RETURN n",
]


@pytest.mark.parametrize("cypher", READ_QUERIES)
def test_legitimate_read_queries_are_not_blocked(cypher):
    assert check_read_only(cypher).allowed, check_read_only(cypher).violations


def test_string_literals_with_statement_separators_are_refused_by_design():
    """A checker and the database lexer must agree on where a string ends; ambiguity fails closed."""
    assert check_read_only("MATCH (n) WHERE n.x = 'a; b' RETURN n").allowed is False


def test_unbounded_traversals_are_refused():
    for q in ("MATCH (a)-[*]->(b) RETURN b", "MATCH (a)-[:R*]->(b) RETURN b", "MATCH (a)-[:R*1..99]->(b) RETURN b"):
        assert check_read_only(q).allowed is False
    assert check_read_only("MATCH (a)-[:R*1..3]->(b) RETURN b").allowed


def test_property_and_label_names_that_look_like_keywords_are_fine():
    assert check_read_only("MATCH (n:Set) WHERE n.delete = 1 AND n.create = 2 RETURN n.merge").allowed


# ---------------------------------------------------------------------------------------------
# 7. Destructive database operations: the DATABASE refuses writes, not just the text filter
# ---------------------------------------------------------------------------------------------

class _Tx:
    def __init__(self, log):
        self.log = log

    def run(self, query, **params):
        # The real driver accepts only str here: a Query object (used for timeouts) is session.run-only and fails
        # against a live server. A fake that tolerated it hid exactly that bug until the Neo4j Desktop verification.
        assert isinstance(query, str), f"tx.run received {type(query).__name__}; use unit_of_work(timeout=...) instead"
        self.log.append(("tx.run", query))
        return []


class _Session:
    def __init__(self, log, kwargs):
        self.log, self.kwargs = log, kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute_read(self, fn):
        self.log.append(("execute_read", getattr(fn, "timeout", None)))  # unit_of_work stores the transaction timeout here
        return fn(_Tx(self.log))

    def execute_write(self, fn):
        self.log.append(("execute_write",))
        raise AssertionError("a user query must never run in a write transaction")

    def run(self, *a, **k):
        self.log.append(("session.run",))
        raise AssertionError("a user query must never run in an auto-commit (write-capable) transaction")


class _Driver:
    def __init__(self):
        self.log, self.session_kwargs = [], {}

    def session(self, **kwargs):
        self.session_kwargs = kwargs
        return _Session(self.log, kwargs)

    def close(self):
        self.log.append(("close",))


def test_user_queries_run_in_a_read_transaction_on_a_read_access_session(monkeypatch, configure):
    from neo4j import READ_ACCESS

    from services.sparql_to_cypher import SparqlToCypher

    configure(QUERY_TIMEOUT_SECONDS="7")
    driver = _Driver()
    bridge = SparqlToCypher()
    monkeypatch.setattr(bridge, "connect", lambda: driver)
    bridge.execute_cypher("MATCH (p:Patient) RETURN p.name LIMIT 5")
    assert driver.session_kwargs["default_access_mode"] == READ_ACCESS
    kinds = [entry[0] for entry in driver.log]
    assert "execute_read" in kinds and "execute_write" not in kinds and "session.run" not in kinds
    assert ("execute_read", 7.0) in driver.log                                   # the transaction carries the timeout
    assert ("tx.run", "MATCH (p:Patient) RETURN p.name LIMIT 5") in driver.log   # and the text goes through unchanged


def test_a_write_never_reaches_the_driver(monkeypatch):
    from services.sparql_to_cypher import SparqlToCypher

    bridge = SparqlToCypher()
    reached = []
    monkeypatch.setattr(bridge, "connect", lambda: reached.append("connect"))
    for cypher in ("MATCH (n) DETACH DELETE n", "CREATE (n:X)", "CALL apoc.cypher.doIt('x', {})"):
        with pytest.raises(CypherPolicyViolation):
            bridge.execute_cypher(cypher)
    assert reached == []


def test_no_user_facing_query_path_can_write_to_neo4j():
    """Static guarantee: the only code that runs user/LLM-authored Cypher has no write-capable call."""
    source = (ROOT / "services" / "sparql_to_cypher.py").read_text(encoding="utf-8")
    start = source.index("    def execute_cypher(")
    body = source[start: source.index("    # =================================================\n    # SPARQL", start)]
    assert "execute_read" in body and "READ_ACCESS" in body and "require_read_only" in body
    for forbidden in ("execute_write", "session.run(", "write_transaction"):
        assert forbidden not in body


def test_the_database_server_is_configured_to_refuse_other_procedures():
    compose = (ROOT / "docker_compose.yaml").read_text(encoding="utf-8")
    assert "NEO4J_dbms_security_procedures_allowlist" in compose
    allowlist = compose.split("NEO4J_dbms_security_procedures_allowlist:")[1].splitlines()[0]
    assert "apoc" not in allowlist and "dbms." not in allowlist and "db.index.vector.queryNodes" in allowlist
    assert "NEO4J_PLUGINS" not in compose, "APOC is not required and must not be installed"


def test_apoc_is_not_used_anywhere_in_the_application():
    for folder in ("core", "services", "routers", "agents", "enterprise"):
        for path in (ROOT / folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8-sig").lower()
            if path.name in ("cypher_policy.py", "cypher_validator.py", "cypher_generator.py"):
                continue  # these mention it only to refuse it
            assert "apoc." not in text, path


def test_the_projection_writer_cannot_be_reached_by_the_query_endpoints():
    router = (ROOT / "routers" / "sparql.py").read_text(encoding="utf-8")
    assert "Neo4jExporter" not in router and "get_neo4j_exporter" not in router


# ---------------------------------------------------------------------------------------------
# 8. The demo seed: absent from HTTP, impossible in production, never destructive
# ---------------------------------------------------------------------------------------------

def test_there_is_no_seed_or_reset_endpoint_in_any_environment(client, secure, configure):
    for env in ("development", "production"):
        configure(ENVIRONMENT=env)
        paths = client.get("/openapi.json").json()["paths"]
        assert not [p for p in paths if "seed" in p or "reset" in p or "wipe" in p or "clear" in p]
        response = client.post("/neo4j/seed-demo", headers=secure.h("suchismita"))
        assert response.status_code in (404, 405), env  # authenticated admin: still no such route


def test_seeding_is_refused_in_production_even_if_enabled(configure):
    from core.graph_domains import ResetNotAllowed, require_demo_allowed

    configure(ENVIRONMENT="production", ALLOW_DEMO_SEED="true")
    with pytest.raises(ResetNotAllowed, match="disabled in ENVIRONMENT='production'"):
        require_demo_allowed()


def test_seeding_needs_an_explicit_development_opt_in(configure):
    from core.graph_domains import ResetNotAllowed, require_demo_allowed

    configure(ENVIRONMENT="development", ALLOW_DEMO_SEED="false")
    with pytest.raises(ResetNotAllowed, match="ALLOW_DEMO_SEED=true"):
        require_demo_allowed()
    configure(ENVIRONMENT="development", ALLOW_DEMO_SEED="true")
    require_demo_allowed()  # no exception


def test_the_seed_pipeline_stops_before_touching_anything_in_production(configure, monkeypatch):
    import services.seed_demo_data as seed
    from core.graph_domains import ResetNotAllowed

    configure(ENVIRONMENT="production", ALLOW_DEMO_SEED="true")
    monkeypatch.setattr(seed, "Neo4jExporter", lambda *a, **k: pytest.fail("the exporter must not be constructed"))
    monkeypatch.setattr(seed, "HealthcareOntology", lambda *a, **k: pytest.fail("the ontology must not be loaded"))
    with pytest.raises(ResetNotAllowed):
        seed.seed_demo_ontology_and_neo4j()


def test_the_seed_script_refuses_in_production(tmp_path):
    import os

    env = dict(os.environ, ENVIRONMENT="production", ALLOW_DEMO_SEED="true", NEO4J_PASSWORD="x" * 12,
               API_CREDENTIALS_FILE="")
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "seed_neo4j_demo.py"), "--yes"],
                          capture_output=True, text=True, cwd=ROOT, env=env, timeout=120)
    assert done.returncode == 2 and "Refused" in done.stderr and "production" in done.stderr


def test_resetting_the_projection_is_scoped_and_guarded(configure):
    from core.graph_domains import PROJECTION_LABELS, ResetNotAllowed
    from services.neo4j_exporter import reset_statements

    assert all(label in st.cypher for st, label in zip(reset_statements(), PROJECTION_LABELS))
    configure(ENVIRONMENT="production", ALLOW_PROJECTION_RESET="true")
    with pytest.raises(ResetNotAllowed):
        Neo4jExporter(owl_file=OWL_FILE, driver=FakeDriver(), database="hc").reset_projection()


# ---------------------------------------------------------------------------------------------
# 9. Startup: unsafe configuration is refused, not served
# ---------------------------------------------------------------------------------------------

def test_production_without_credentials_refuses_to_start(configure):
    configure(ENVIRONMENT="production", API_CREDENTIALS_FILE="", API_KEY="")
    assert security_mode() == "unconfigured"
    with pytest.raises(SecurityConfigurationError, match="requires authentication"):
        validate_security_configuration()


def test_production_without_credentials_serves_nothing(client, configure):
    configure(ENVIRONMENT="production", API_CREDENTIALS_FILE="", API_KEY="")
    assert client.get("/patients").status_code == 503
    assert client.get("/patients", headers={"X-Role": "admin", "X-API-Key": "anything"}).status_code == 503


def test_production_with_credentials_starts(secure, configure):
    configure(ENVIRONMENT="production", ALLOW_OPEN_DEVELOPMENT_MODE="false")
    assert security_mode() == "enforced"
    assert validate_security_configuration() == []
    configure(ALLOW_OPEN_DEVELOPMENT_MODE="true")  # a stray opt-in in production is reported, never obeyed
    assert security_mode() == "enforced"
    assert any("ignored outside development" in w for w in validate_security_configuration())


def test_development_without_credentials_is_open_only_with_the_explicit_opt_in(configure):
    configure(ENVIRONMENT="development", API_CREDENTIALS_FILE="", API_KEY="", ALLOW_OPEN_DEVELOPMENT_MODE="false")
    assert security_mode() == "unconfigured"
    configure(ALLOW_OPEN_DEVELOPMENT_MODE="true")
    assert security_mode() == "development-open"
    warnings = validate_security_configuration()
    assert any("AUTHENTICATION IS DISABLED" in w for w in warnings)


def test_open_development_mode_ignores_forged_headers(client, configure):
    configure(ENVIRONMENT="development", API_CREDENTIALS_FILE="", API_KEY="")
    response = client.get("/enterprise/ontologies", headers={"X-Tenant-ID": "research"})
    assert response.status_code == 403  # even in development a forged tenant is refused, not obeyed


def test_any_credential_switches_development_to_enforced_mode(secure, client):
    assert security_mode() == "enforced"
    assert client.get("/patients").status_code == 401


def test_the_api_refuses_to_start_through_its_startup_hook(configure):
    import api

    configure(ENVIRONMENT="production", API_CREDENTIALS_FILE="", API_KEY="")
    with pytest.raises(SecurityConfigurationError):
        api.on_startup()
