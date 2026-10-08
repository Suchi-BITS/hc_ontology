"""Neo4j configuration, the foreign-data guard and the Cypher timeout: tests that need NO database.

These cover what the live Neo4j Desktop verification found or changed (docs/NEO4J_DESKTOP_LIVE_VERIFICATION.md). The
behaviour against a real server is in tests/test_neo4j_live.py (opt-in).
"""

from __future__ import annotations

import pytest

from core.config import get_settings
from services.neo4j_exporter import ForeignDataPresent, Neo4jExporter
from tests.fakes import FakeDriver, Validator


# ---- one configuration mechanism -----------------------------------------------------------------------------

def test_the_connection_comes_from_configuration_not_from_code(configure):
    configure(NEO4J_URI="bolt://db.example.internal:7999", NEO4J_USERNAME="alice", NEO4J_DATABASE="clinical")
    s = get_settings()
    assert (s["neo4j_uri"], s["neo4j_username"], s["neo4j_database"]) == ("bolt://db.example.internal:7999", "alice", "clinical")


def test_neo4j_user_is_accepted_as_an_alias_and_the_project_name_wins(monkeypatch, configure):
    monkeypatch.delenv("NEO4J_USERNAME", raising=False)
    configure(NEO4J_USER="desktop-user")
    assert get_settings()["neo4j_username"] == "desktop-user"
    configure(NEO4J_USERNAME="project-user")
    assert get_settings()["neo4j_username"] == "project-user"


def test_every_driver_in_the_code_base_takes_its_connection_from_settings():
    """No module may read NEO4J_URI / NEO4J_USERNAME / NEO4J_DATABASE on its own: that would be a second mechanism."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    offenders = []
    for folder in ("core", "services", "agents", "enterprise", "routers", "scripts"):
        for path in (root / folder).rglob("*.py"):
            if path.name == "config.py" or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for var in ('"NEO4J_URI"', '"NEO4J_USERNAME"', '"NEO4J_DATABASE"', '"NEO4J_USER"'):
                if f"getenv({var}" in text.replace("\n", "").replace(" ", ""):
                    offenders.append(f"{path.relative_to(root)} reads {var}")
    assert offenders == []


def test_the_password_is_never_in_the_example_file():
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / ".env.example").read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if l.startswith("NEO4J_PASSWORD="))
    assert line == "NEO4J_PASSWORD=<your-neo4j-password>"


def test_the_verification_command_never_prints_the_password():
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "scripts" / "verify_neo4j.py").read_text(encoding="utf-8")
    printed = [l for l in text.splitlines() if "print(" in l]
    assert printed, "the script prints its report"
    assert not any("neo4j_password" in l or "require_neo4j_password" in l for l in printed), "a print statement reads the password"
    assert 'replace(s["neo4j_password"]' in text, "driver error text is scrubbed of the password before it is shown"


# ---- the foreign-data guard ---------------------------------------------------------------------------------------

class _Result:
    def __init__(self, row):
        self._row = row

    def single(self):
        return self._row


class _ForeignSession:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, **params):
        self.driver.log.append(("auto", cypher, params))
        if "none(l IN labels(n)" in cypher:
            return _Result({"c": self.driver.foreign, "sample": [["Patient"], ["Neurologist"]]})
        return _Result({"c": 0})

    def execute_write(self, fn):
        raise AssertionError("nothing may be written when foreign data is present")


class _ForeignDriver(FakeDriver):
    def __init__(self, foreign):
        super().__init__()
        self.foreign = foreign

    def session(self, database=None):
        self.sessions += 1
        return _ForeignSession(self)


def exporter(driver):
    return Neo4jExporter(driver=driver, database="hc", validator=Validator())


def test_a_database_holding_other_domains_nodes_is_refused_and_nothing_is_written():
    driver = _ForeignDriver(foreign=65)
    with pytest.raises(ForeignDataPresent) as err:
        exporter(driver).sync()
    message = " ".join(err.value.problems)
    assert "65 node(s)" in message and "Nothing was written" in message and "NEO4J_DATABASE" in message
    assert not any("MERGE" in entry[1] for entry in driver.log)        # not even the schema statements ran
    assert [entry for entry in driver.log if entry[0] != "auto"] == []


def test_an_empty_or_projection_only_database_is_accepted():
    driver = _ForeignDriver(foreign=0)
    driver.session = lambda database=None: FakeDriver.session(driver, database)   # normal recording fake
    assert exporter(driver).sync()["status"] == "success"


def test_the_guard_can_be_overridden_deliberately():
    class Mixed(_ForeignDriver):
        def session(self, database=None):
            self.sessions += 1
            return _MixedSession(self)

    class _MixedSession(_ForeignSession):
        def execute_write(self, fn):
            return fn(type("Tx", (), {"run": lambda tx, c, **p: self.driver.log.append(("tx", c, p))})())

    driver = Mixed(foreign=3)
    assert exporter(driver).sync(allow_foreign=True)["status"] == "success"


def test_the_guard_looks_only_at_nodes_outside_every_known_domain():
    driver = _ForeignDriver(foreign=1)
    exporter(driver).foreign_nodes()
    sent, params = driver.log[0][1], driver.log[0][2]
    from core.graph_domains import AGENT_MEMORY_LABELS, APPLICATION_LABELS, PROJECTION_LABELS, SEMANTIC_INDEX_LABELS

    assert set(params["known"]) == set(PROJECTION_LABELS) | set(AGENT_MEMORY_LABELS) | set(APPLICATION_LABELS) | set(SEMANTIC_INDEX_LABELS)
    assert sent.startswith("MATCH (n) WHERE none(l IN labels(n) WHERE l IN $known)") and "DELETE" not in sent and "SET" not in sent


def test_the_api_reports_foreign_data_as_a_controlled_422(client, secure, monkeypatch):
    import routers.neo4j as neo4j_router

    driver = _ForeignDriver(foreign=65)
    monkeypatch.setattr(neo4j_router, "get_neo4j_exporter", lambda: exporter(driver))
    response = client.post("/neo4j/load", headers=secure.h("operator"))
    assert response.status_code == 422
    assert "outside this project's graph domains" in response.text and "Traceback" not in response.text


# ---- the Cypher timeout belongs to the transaction ----------------------------------------------------------------

def test_a_database_timeout_becomes_a_controlled_timeout_error(monkeypatch, configure):
    from neo4j.exceptions import ClientError

    from services.sparql_to_cypher import SparqlToCypher

    configure(QUERY_TIMEOUT_SECONDS="2")

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute_read(self, fn):
            raise ClientError._hydrate_neo4j(code="Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration", message="terminated")

    class Driver:
        def session(self, **kw):
            return Session()

        def close(self):
            pass

    bridge = SparqlToCypher()
    monkeypatch.setattr(bridge, "connect", lambda: Driver())
    with pytest.raises(TimeoutError) as err:
        bridge.execute_cypher("MATCH (p:Patient) RETURN p.name LIMIT 5")
    assert "2-second limit" in str(err.value) and "Neo.ClientError" not in str(err.value)


def test_other_database_errors_are_not_disguised_as_timeouts(monkeypatch, configure):
    from neo4j.exceptions import ClientError

    from services.sparql_to_cypher import SparqlToCypher

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute_read(self, fn):
            raise ClientError._hydrate_neo4j(code="Neo.ClientError.Statement.SyntaxError", message="bad")

    class Driver:
        def session(self, **kw):
            return Session()

        def close(self):
            pass

    bridge = SparqlToCypher()
    monkeypatch.setattr(bridge, "connect", lambda: Driver())
    with pytest.raises(ClientError):
        bridge.execute_cypher("MATCH (p:Patient) RETURN p.name LIMIT 5")
