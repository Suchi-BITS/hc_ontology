"""Integration tests for SHACL validation."""

from pathlib import Path

import pytest

from core.shacl_loader import load_all_shapes
from core.shacl_report import ShaclReportFormatter


def test_load_all_shapes_entry_point(project_root):
    graph = load_all_shapes(project_root / "shapes")
    from tests.test_patient_shapes import EXPECTED_NODE_SHAPES, node_shape_names

    assert EXPECTED_NODE_SHAPES <= node_shape_names(graph)


def test_shipped_ontology_conforms_to_its_own_shapes(validator, project_root):
    """The sample data must satisfy the project's own shapes (PatientJohn used to fail)."""
    result = validator.validate_ontology()
    violations = [v for v in result.violations if v.severity == "Violation"]
    assert violations == [], [(v.focus_node, v.message) for v in violations]
    assert result.summary.conforms is True
    assert {"clinical_shapes.ttl", "patient_shapes.ttl", "medication_shapes.ttl"} <= set(result.summary.shapes_used)


def test_a_broken_patient_is_detected_in_the_real_ontology(validator, project_root):
    """Guard against the validation silently doing nothing: remove a required field and it must fail."""
    from rdflib import Graph, XSD

    from core.dataset import Dataset

    graph = Dataset.default().graph()
    hc = "http://example.org/healthcare-hospital.owl#"
    from rdflib import URIRef

    graph.remove((URIRef(hc + "PatientJohn"), URIRef(hc + "dateOfBirth"), None))
    result = validator.validate_graph(graph, data_source="mutated")
    assert result.summary.conforms is False
    assert any(
        v.result_path and v.result_path.endswith("dateOfBirth") and v.severity == "Violation"
        for v in result.violations
    )


def test_prescription_allergy_conflict(validator, sample_instances_dir):
    result = validator.validate_data_file(
        sample_instances_dir / "invalid_prescription_allergy.ttl",
        shape_files=["medication_shapes.ttl", "patient_shapes.ttl"],
    )
    assert result.summary.conforms is False
    conflicts = [v for v in result.violations
                 if v.severity == "Violation" and "allergic" in (v.message or "").lower()
                 and "SPARQLConstraintComponent" in (v.source_constraint or "")]
    assert len(conflicts) == 1, [(v.severity, v.message) for v in result.violations]
    assert not any(
        v.message and "allergic" in v.message.lower() and v.severity != "Violation"
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
