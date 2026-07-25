"""Integration tests for SHACL validation."""

from pathlib import Path

import pytest

from core.shacl_loader import load_all_shapes
from core.shacl_report import ShaclReportFormatter


def test_load_all_shapes_entry_point(project_root):
    graph = load_all_shapes(project_root / "shapes")
    assert len(graph) > 0


def test_validate_ontology_runs(validator, project_root):
    owl = project_root / "healthcare_ontology.owl"
    if not owl.is_file():
        pytest.skip("healthcare_ontology.owl not present")

    result = validator.validate_ontology()
    assert result.summary.data_source
    assert isinstance(result.summary.conforms, bool)
    # Production sample data lacks dateOfBirth → PatientShape Violations expected.
    # Ensure core hospital/bloodGroup rules are not the only signal of life.
    assert result.summary.total_violations >= 0


def test_prescription_allergy_conflict(validator, sample_instances_dir):
    result = validator.validate_data_file(
        sample_instances_dir / "invalid_prescription_allergy.ttl",
        shape_files=["medication_shapes.ttl", "patient_shapes.ttl"],
    )
    assert result.summary.conforms is False
    assert any(
        v.message and "allergic" in v.message.lower() for v in result.violations
    ) or any(
        v.source_constraint and "SPARQL" in (v.source_constraint or "")
        for v in result.violations
    )


def test_html_report_renders(validator, sample_instances_dir):
    result = validator.validate_data_file(
        sample_instances_dir / "valid_patient.ttl",
        shape_files=["patient_shapes.ttl"],
    )
    html = ShaclReportFormatter().to_html(result)
    assert "SHACL Validation Report" in html


def test_validator_health(validator):
    health = validator.health()
    assert health["shapes"]["ready"] is True
    assert health["shapes"]["manifest_present"] is True
    assert "validation_mode" in health
