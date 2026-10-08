"""SPARQL requests are bounded in time, and the bound is REAL: the work is stopped, not just abandoned.

Background: the first "timeout" ran the query on a thread inside `with ThreadPoolExecutor(...)`. On timeout the
`with` block still waited for the thread, so a four-way cartesian COUNT(*) held the request for ever. rdflib
cannot cancel a running query, so execution now happens in worker processes that are killed at the limit
(core/sparql_exec.py). These tests exercise that for real: they start workers, run a query that never ends on
its own, and check the process is gone.
"""

from __future__ import annotations

import os
import time

import pytest

from core.config import ConfigurationError, get_settings
from core.sparql_exec import SparqlBusy, SparqlTimeout, get_runner, shutdown_all
from services.load_ontology import HealthcareOntology

P = "PREFIX hc: <http://example.org/healthcare-hospital.owl#> "
NORMAL = P + "SELECT ?p WHERE { ?p a hc:Patient } ORDER BY ?p"
# Four unrelated triple patterns over ~1,900 triples: ~10^13 combinations. It never finishes on its own.
EXPENSIVE = "SELECT (COUNT(*) AS ?n) WHERE { ?a ?b ?c . ?d ?e ?f . ?g ?h ?i . ?j ?k ?l }"


@pytest.fixture(autouse=True)
def _clean_workers():
    shutdown_all()
    yield
    shutdown_all()


@pytest.fixture
def ontology():
    return HealthcareOntology()


def pid_alive(pid: int) -> bool:
    import subprocess
    import sys

    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ---- 1. normal queries still work ------------------------------------------------------------------

def test_a_normal_query_returns_its_rows(ontology, configure):
    configure(SPARQL_QUERY_TIMEOUT_SECONDS="20")
    rows = ontology.execute_sparql(NORMAL)
    assert [r[0].split("#")[-1] for r in rows] == ["PatientAlice", "PatientBob", "PatientDavid", "PatientEmma", "PatientJohn"]


def test_string_literals_still_match_after_the_move_to_a_worker(ontology, configure):
    """The xsd:string normalisation moved into the worker; the README's natural query must still work."""
    configure(SPARQL_QUERY_TIMEOUT_SECONDS="20")
    rows = ontology.execute_sparql(P + 'SELECT ?c WHERE { ?c hc:codeValue "E11" }')
    assert rows and rows[0][0].endswith("Icd10_E11")


def test_the_worker_reloads_when_the_ontology_file_changes(tmp_path, configure):
    configure(SPARQL_QUERY_TIMEOUT_SECONDS="20")
    import shutil

    copy = tmp_path / "o.owl"
    from core.dataset import Dataset

    Dataset.default().graph().serialize(copy, format="xml")  # one combined RDF/XML file used as a single-file dataset
    onto = HealthcareOntology(owl_file=str(copy))
    assert len(onto.execute_sparql(NORMAL)) == 5
    text = copy.read_text(encoding="utf-8")
    copy.write_text(text.replace("</rdf:RDF>", "") + '<owl:NamedIndividual rdf:about="http://example.org/healthcare-hospital.owl#PatientZed"><rdf:type rdf:resource="http://example.org/healthcare-hospital.owl#Patient"/></owl:NamedIndividual></rdf:RDF>', encoding="utf-8")
    assert len(onto.execute_sparql(NORMAL)) == 6


# ---- 2 + 4. an expensive query is terminated, and nothing is left running ------------------------------

def test_an_expensive_query_is_terminated_at_the_limit(ontology, configure):
    configure(SPARQL_QUERY_TIMEOUT_SECONDS="1")
    ontology.execute_sparql(NORMAL)  # warm: start-up must not be counted against the limit below
    started = time.monotonic()
    with pytest.raises(SparqlTimeout, match="1-second limit"):
        ontology.execute_sparql(EXPENSIVE)
    assert time.monotonic() - started < 4, "the limit did not bound the request"


def test_the_runaway_process_is_actually_killed(ontology, configure):
    configure(SPARQL_QUERY_TIMEOUT_SECONDS="1", SPARQL_WORKERS="1")
    runner = get_runner(ontology.owl_file, 1)
    ontology.execute_sparql(NORMAL)
    (pid,) = runner.worker_pids()
    with pytest.raises(SparqlTimeout):
        ontology.execute_sparql(EXPENSIVE)
    deadline = time.time() + 5
    while pid_alive(pid) and time.time() < deadline:
        time.sleep(0.1)
    assert not pid_alive(pid), "the worker that ran the query is still running: the timeout only stopped waiting"


def test_the_service_is_usable_immediately_after_a_timeout(ontology, configure):
    configure(SPARQL_QUERY_TIMEOUT_SECONDS="1", SPARQL_WORKERS="1")
    with pytest.raises(SparqlTimeout):
        ontology.execute_sparql(EXPENSIVE)
    assert len(ontology.execute_sparql(NORMAL)) == 5  # a fresh worker took over
    with pytest.raises(SparqlTimeout):
        ontology.execute_sparql(EXPENSIVE)
    assert len(ontology.execute_sparql(NORMAL)) == 5


def test_repeated_timeouts_do_not_accumulate_processes(ontology, configure):
    configure(SPARQL_QUERY_TIMEOUT_SECONDS="1", SPARQL_WORKERS="1")
    seen = []
    for _ in range(3):
        ontology.execute_sparql(NORMAL)
        seen += get_runner(ontology.owl_file, 1).worker_pids()
        with pytest.raises(SparqlTimeout):
            ontology.execute_sparql(EXPENSIVE)
    time.sleep(1)
    assert len(set(seen)) == 3 and not any(pid_alive(p) for p in set(seen))


def test_a_stuck_query_does_not_block_other_workers(ontology, configure):
    """One worker spinning on a runaway query leaves the other one free to answer."""
    import threading

    configure(SPARQL_QUERY_TIMEOUT_SECONDS="6", SPARQL_WORKERS="2")
    ontology.execute_sparql(NORMAL)
    ontology.execute_sparql(NORMAL)  # both workers warm
    outcome = {}

    def runaway():
        try:
            ontology.execute_sparql(EXPENSIVE)
        except SparqlTimeout:
            outcome["timeout"] = True

    t = threading.Thread(target=runaway)
    t.start()
    time.sleep(0.5)
    started = time.monotonic()
    assert len(ontology.execute_sparql(NORMAL)) == 5
    assert time.monotonic() - started < 3
    t.join(timeout=15)
    assert outcome == {"timeout": True}


def test_when_every_worker_is_busy_a_request_fails_fast_instead_of_queueing_for_ever(ontology, configure):
    configure(SPARQL_QUERY_TIMEOUT_SECONDS="1", SPARQL_WORKERS="1")
    runner = get_runner(ontology.owl_file, 1)
    held = runner._pool.get()  # a request is holding the only worker
    try:
        started = time.monotonic()
        with pytest.raises(SparqlBusy):
            ontology.execute_sparql(NORMAL)
        assert time.monotonic() - started < 3
    finally:
        runner._pool.put(held)


def _swallow(fn):
    try:
        fn()
    except Exception:  # noqa: BLE001
        pass


# ---- 3. the API answers with a controlled response ---------------------------------------------------------

def test_the_api_returns_504_with_a_short_message_and_no_internals(client, configure):
    configure(SPARQL_QUERY_TIMEOUT_SECONDS="1")
    client.post("/sparql", json={"query": NORMAL})  # warm
    started = time.monotonic()
    response = client.post("/sparql", json={"query": EXPENSIVE})
    assert response.status_code == 504
    assert time.monotonic() - started < 5
    body = response.text
    assert "exceeded the 1-second limit" in body
    for leak in ("Traceback", 'File "', "sparql_exec.py", "sparql_worker", "Popen"):
        assert leak not in body
    assert client.post("/sparql", json={"query": NORMAL}).status_code == 200  # and the API carries on


def test_the_api_reports_a_query_error_without_a_stack_trace(client, configure):
    configure(SPARQL_QUERY_TIMEOUT_SECONDS="20")
    response = client.post("/sparql", json={"query": "SELECT WHERE"})
    assert response.status_code == 400 and "Traceback" not in response.text


def test_generated_queries_use_the_same_bounded_path():
    """The natural-language path used to run `graph.query` in-process, unbounded."""
    import inspect

    from services import sparql_generator

    source = inspect.getsource(sparql_generator.SparqlGenerator.validate_execution)
    assert "execute_sparql" in source and ".query(" not in source


def test_there_is_no_unbounded_graph_query_on_any_request_path():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for rel in ("routers/sparql.py", "routers/neo4j.py", "services/sparql_generator.py", "core/sparql_validator.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "graph.query(" not in text, f"{rel} runs a query in-process without a bound"
        assert "execute_with_timeout" not in text.replace("There is deliberately no execute_with_timeout", "")


# ---- 5 + 6. configuration --------------------------------------------------------------------------------------

def test_the_default_is_bounded_and_documented(monkeypatch):
    monkeypatch.delenv("SPARQL_QUERY_TIMEOUT_SECONDS", raising=False)
    get_settings.cache_clear()
    value = get_settings()["sparql_query_timeout_seconds"]
    assert 0 < value <= 300 and value == 15.0
    assert "SPARQL_QUERY_TIMEOUT_SECONDS" in open(".env.example", encoding="utf-8").read()
    get_settings.cache_clear()


def test_the_timeout_is_configurable(ontology, configure):
    configure(SPARQL_QUERY_TIMEOUT_SECONDS="1", SPARQL_WORKERS="1")
    ontology.execute_sparql(NORMAL)
    t0 = time.monotonic()
    with pytest.raises(SparqlTimeout):
        ontology.execute_sparql(EXPENSIVE)
    short = time.monotonic() - t0
    configure(SPARQL_QUERY_TIMEOUT_SECONDS="3")
    t0 = time.monotonic()
    with pytest.raises(SparqlTimeout, match="3-second limit"):
        ontology.execute_sparql(EXPENSIVE)
    long = time.monotonic() - t0
    assert 0.8 < short < 2.5 and 2.8 < long < 6


@pytest.mark.parametrize("bad", ["abc", "0", "-5", "nan", "inf", "301", "0.01", "1e9", "ten"])
def test_an_invalid_timeout_fails_clearly(bad, configure):
    configure(SPARQL_QUERY_TIMEOUT_SECONDS=bad)
    with pytest.raises(ConfigurationError, match="SPARQL_QUERY_TIMEOUT_SECONDS must be a number between 0.1 and 300"):
        get_settings()


def test_there_is_no_way_to_ask_for_no_limit(configure):
    for unlimited in ("none", "unlimited", "off", "-1", "0", ""):
        configure(SPARQL_QUERY_TIMEOUT_SECONDS=unlimited)
        try:
            value = get_settings()["sparql_query_timeout_seconds"]
        except ConfigurationError:
            continue
        assert value == 15.0  # an empty value falls back to the bounded default, never to "unlimited"


@pytest.mark.parametrize("bad", ["0", "9", "-1", "1.5", "many"])
def test_an_invalid_worker_count_fails_clearly(bad, configure):
    configure(SPARQL_WORKERS=bad)
    with pytest.raises(ConfigurationError, match="SPARQL_WORKERS must be a whole number between 1 and 8"):
        get_settings()
