"""Patient SHACL shape tests against data/sample_instances fixtures."""

from pathlib import Path


def test_shapes_directory_has_common_and_manifest(shacl_loader):
    files = shacl_loader.list_shape_files()
    assert "patient_shapes.ttl" in files
    assert "common/person_shapes.ttl" in files
    assert "shapes_manifest.ttl" in files



EXPECTED_NODE_SHAPES = {
    "PersonShape", "PatientShape", "PractitionerShape", "DoctorShape", "ConditionShape", "DiagnosisShape",
    "EncounterShape", "ObservationShape", "CodeConceptShape", "IdentifierShape", "MedicationShape",
    "PrescriptionAllergyConflictShape", "AllergyShape", "HospitalShape", "TreatmentShape",
}


def node_shape_names(graph):
    from rdflib import RDF, URIRef
    from rdflib.namespace import SH

    return {str(s).split("#")[-1] for s in graph.subjects(RDF.type, SH.NodeShape) if isinstance(s, URIRef)}


def test_load_all_shapes_merges_package(shapes_graph):
    """Every module of the package is merged: the expected shapes are all present."""
    assert EXPECTED_NODE_SHAPES <= node_shape_names(shapes_graph), EXPECTED_NODE_SHAPES - node_shape_names(shapes_graph)


def test_valid_patient_fixture(validator, sample_instances_dir):
    path = sample_instances_dir / "valid_patient.ttl"
    result = validator.validate_data_file(
        path,
        shape_files=["patient_shapes.ttl"],
    )
    assert result.summary.conforms is True
    assert result.summary.violation_count == 0


def test_invalid_patient_missing_dob(validator, sample_instances_dir):
    path = sample_instances_dir / "invalid_patient_missing_dob.ttl"
    result = validator.validate_data_file(
        path,
        shape_files=["patient_shapes.ttl"],
    )
    assert result.summary.conforms is False
    assert result.summary.violation_count >= 1
    assert any(
        v.result_path and "dateOfBirth" in v.result_path and v.severity == "Violation"
        for v in result.violations
    )


def test_invalid_blood_group_pattern(validator):
    data = """
    @prefix hc: <http://example.org/healthcare-hospital.owl#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    hc:PatientBad a hc:Patient ;
        hc:firstName "Bad"^^xsd:string ;
        hc:dateOfBirth "2000-01-01"^^xsd:string ;
        hc:bloodGroup "Z+"^^xsd:string .
    """
    result = validator.validate_rdf_text(
        data,
        rdf_format="turtle",
        shape_files=["patient_shapes.ttl"],
    )
    assert result.summary.conforms is False
    assert any(
        v.result_path and "bloodGroup" in v.result_path for v in result.violations
    )
