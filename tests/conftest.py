"""Shared pytest fixtures for SHACL and API tests."""

from __future__ import annotations

import os

# The suite makes NO network calls to OpenAI or LangSmith, but several components build an OpenAI
# client object when they are constructed, and that fails without any key. So tests always run with
# an obviously fake key and with tracing off. This also means a developer's real keys in .env are
# never used (or spent, or sent anywhere) by the tests. Must happen before the app is imported.
if os.environ.get("RUN_LIVE_AI") != "1":      # the only way a test run can spend money or reach OpenAI is this explicit opt-in
    os.environ["OPENAI_API_KEY"] = "sk-test-placeholder-no-network-calls-are-made"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["OTEL_ENABLED"] = "false"
# Tests are hermetic with respect to authentication too: a developer's real .credentials.json or API_KEY
# must not switch the suite into enforced mode. Security tests create their own credentials.
os.environ["API_CREDENTIALS_FILE"] = ""
os.environ["API_KEY"] = ""
os.environ["ENVIRONMENT"] = "development"
# Open mode is an explicit opt-in; the suite opts in so that ordinary tests can call the API without a key.
# Security tests switch it off (configure(ALLOW_OPEN_DEVELOPMENT_MODE="false")) to prove the default is closed.
os.environ["ALLOW_OPEN_DEVELOPMENT_MODE"] = "true"

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph

import api
import routers.shacl as shacl_routes
from core.config import get_settings
from core.dataset import Dataset
from core.shacl_loader import ShaclLoader, load_all_shapes
from core.shacl_validator import ShaclValidator

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "sample_instances"


@pytest.fixture(scope="session")
def project_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def sample_instances_dir() -> Path:
    return SAMPLES


@pytest.fixture(scope="session")
def shapes_graph() -> Graph:
    """Full merged SHACL shapes graph (loaded once per test session)."""
    return load_all_shapes(ROOT / "shapes")


@pytest.fixture(scope="session")
def shacl_loader() -> ShaclLoader:
    return ShaclLoader(shapes_dir=ROOT / "shapes")


@pytest.fixture
def validator() -> ShaclValidator:
    settings = get_settings()
    return ShaclValidator(
        loader=ShaclLoader(shapes_dir=ROOT / "shapes"),
        owl_file=Dataset.default(),
        validation_mode=settings.get("shacl_validation_mode", "warn"),
        data_dir=ROOT / "data",
    )


@pytest.fixture
def client():
    shacl_routes._last_report = None
    return TestClient(api.app)


@pytest.fixture(scope="session")
def tbox_triples(project_root):
    """The ontology's schema (everything except named individuals), for validating instance data.

    Real deployments validate data together with the schema, which is what lets RDFS inference
    connect subclasses (VitalSign -> Observation) and sub-properties (hasDiagnosis -> hasCondition).
    """
    from rdflib import OWL, RDF

    graph = Dataset.default().graph()
    individuals = set(graph.subjects(RDF.type, OWL.NamedIndividual))
    return [t for t in graph if t[0] not in individuals]


@pytest.fixture
def check(validator, tbox_triples):
    """check(turtle, shapes=None) -> ValidationResult, with the ontology schema merged in."""

    def _check(ttl, shapes=None):
        data = Graph()
        data.parse(data=ttl, format="turtle")
        for triple in tbox_triples:
            data.add(triple)
        return validator.validate_graph(data, shape_files=shapes, data_source="inline")

    return _check


@pytest.fixture
def configure(monkeypatch):
    """configure(API_KEY="k", RBAC_ENABLED="true") -> applies environment settings for one test.

    Settings are cached; the cache is cleared on the way in and on the way out so no test
    leaks configuration into another.
    """
    from core.config import get_settings

    def _apply(**env):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()

    yield _apply
    monkeypatch.undo()
    get_settings.cache_clear()


def pytest_collection_modifyitems(items):
    """Attach the pyramid-level markers declared in tests/levels.py."""
    from tests.levels import levels_for

    for item in items:
        stem = item.module.__name__.rsplit(".", 1)[-1]
        for level in levels_for(stem):
            item.add_marker(getattr(pytest.mark, level))


class SecureEnv:
    """Server-side credentials for the security tests. Keys exist only inside the test."""

    USERS = {
        # id: (tenant, role, display name)
        "suchismita": ("abhigya-ai-lab", "admin", "Suchismita"),
        "reader": ("abhigya-ai-lab", "viewer", "Reader"),
        "analyst": ("abhigya-ai-lab", "analyst", "Analyst"),
        "outsider": ("research", "analyst", "Outsider"),
        "research-admin": ("research", "admin", "Research admin"),
        "operator": ("default", "platform_admin", "Platform operator"),
        "ghost": ("no-such-tenant", "admin", "Ghost"),
    }

    def __init__(self, path):
        from core.security import hash_key, new_api_key

        self.keys = {user: new_api_key() for user in self.USERS}
        records = [
            {"id": user, "display_name": name, "tenant_id": tenant, "role": role, "key_sha256": hash_key(self.keys[user])}
            for user, (tenant, role, name) in self.USERS.items()
        ]
        path.write_text(__import__("json").dumps({"credentials": records}), encoding="utf-8")
        self.path = path

    def h(self, user, **extra):
        """Headers for a user. ``extra`` adds forged headers such as X_Role='admin'."""
        headers = {"X-API-Key": self.keys[user]}
        headers.update({k.replace("_", "-"): v for k, v in extra.items()})
        return headers


@pytest.fixture
def secure(configure, tmp_path):
    env = SecureEnv(tmp_path / "credentials.json")
    configure(API_CREDENTIALS_FILE=str(env.path), API_KEY="", RBAC_ENABLED="true", ENVIRONMENT="development")
    return env
