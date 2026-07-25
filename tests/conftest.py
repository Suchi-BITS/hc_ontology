"""Shared pytest fixtures for SHACL and API tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph

import api
import routers.shacl as shacl_routes
from core.config import get_settings
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
        owl_file=str(ROOT / "healthcare_ontology.owl"),
        validation_mode=settings.get("shacl_validation_mode", "warn"),
        data_dir=ROOT / "data",
    )


@pytest.fixture
def client():
    shacl_routes._last_report = None
    return TestClient(api.app)
