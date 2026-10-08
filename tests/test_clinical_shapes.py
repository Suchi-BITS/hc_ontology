"""SHACL tests for the encounter / observation / code-binding shapes.

Each invalid fixture isolates ONE mistake, so a regression in one rule is
reported by exactly the test that owns it.
"""

import pytest


def _messages(result, severity="Violation"):
    return [v.message for v in result.violations if v.severity == severity]


def test_complete_record_conforms_to_all_shapes(validator, sample_instances_dir):
    result = validator.validate_data_file(sample_instances_dir / "valid_encounter.ttl")
    assert result.summary.violation_count == 0, _messages(result)
    assert result.summary.warning_count == 0, _messages(result, "Warning")
    assert result.summary.conforms is True


def test_instant_without_time_zone_is_rejected(validator, sample_instances_dir):
    result = validator.validate_data_file(
        sample_instances_dir / "invalid_encounter_no_timezone.ttl",
        shape_files=["clinical_shapes.ttl"],
    )
    assert result.summary.conforms is False
    assert any("time zone" in m for m in _messages(result)), _messages(result)


def test_encounter_end_before_start_is_rejected(validator):
    data = """
    @prefix hc: <http://example.org/healthcare-hospital.owl#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    hc:EncT a hc:EncounterType .
    hc:P a hc:Patient ; hc:hasEncounter hc:E .
    hc:E a hc:Encounter ; hc:encounterType hc:EncT ;
        hc:encounterStart "2026-03-01T11:00:00Z"^^xsd:dateTime ;
        hc:encounterEnd   "2026-03-01T10:00:00Z"^^xsd:dateTime .
    """
    result = validator.validate_rdf_text(data, rdf_format="turtle", shape_files=["clinical_shapes.ttl"])
    assert result.summary.conforms is False
    assert any("not after encounterEnd" in m for m in _messages(result))


def test_encounter_must_belong_to_exactly_one_patient(validator):
    data = """
    @prefix hc: <http://example.org/healthcare-hospital.owl#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    hc:EncT a hc:EncounterType .
    hc:E a hc:Encounter ; hc:encounterType hc:EncT ;
        hc:encounterStart "2026-03-01T10:00:00Z"^^xsd:dateTime .
    """
    result = validator.validate_rdf_text(data, rdf_format="turtle", shape_files=["clinical_shapes.ttl"])
    assert result.summary.conforms is False
    assert any("exactly one patient" in m for m in _messages(result))


def test_numeric_observation_requires_a_unit(validator):
    data = """
    @prefix hc: <http://example.org/healthcare-hospital.owl#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    hc:P a hc:Patient ; hc:hasObservation hc:O .
    hc:O a hc:Observation ; hc:observationValue 7.2 .
    """
    result = validator.validate_rdf_text(data, rdf_format="turtle", shape_files=["clinical_shapes.ttl"])
    assert result.summary.conforms is False
    assert any("requires an observationUnit" in m for m in _messages(result))


def test_code_concept_requires_system_and_value(validator):
    data = """
    @prefix hc: <http://example.org/healthcare-hospital.owl#> .
    hc:C a hc:CodeConcept .
    """
    result = validator.validate_rdf_text(data, rdf_format="turtle", shape_files=["clinical_shapes.ttl"])
    assert result.summary.conforms is False
    paths = {v.result_path.split("#")[-1] for v in result.violations if v.result_path}
    assert {"codeSystem", "codeValue"} <= paths


def test_shared_diagnosis_record_is_rejected(validator, sample_instances_dir):
    """One Diagnosis individual may not be shared by two patients."""
    result = validator.validate_data_file(
        sample_instances_dir / "invalid_shared_diagnosis.ttl",
        shape_files=["diagnosis_shapes.ttl"],
    )
    assert any("at most one patient" in m for m in _messages(result)), _messages(result)


def test_diagnosis_requires_code_binding(validator):
    data = """
    @prefix hc: <http://example.org/healthcare-hospital.owl#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    hc:D a hc:Diagnosis ; hc:diagnosisName "Hypertension"^^xsd:string .
    """
    result = validator.validate_rdf_text(data, rdf_format="turtle", shape_files=["diagnosis_shapes.ttl"])
    assert any("CodeConcept" in m for m in _messages(result))


def test_clinical_status_is_a_closed_list(validator):
    data = """
    @prefix hc: <http://example.org/healthcare-hospital.owl#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    hc:D a hc:Condition ; hc:clinicalStatus "maybe"^^xsd:string .
    """
    result = validator.validate_rdf_text(data, rdf_format="turtle", shape_files=["diagnosis_shapes.ttl"])
    assert any("clinicalStatus" in m for m in _messages(result))


def test_date_of_birth_must_be_a_date_not_a_string(validator):
    data = """
    @prefix hc: <http://example.org/healthcare-hospital.owl#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    hc:GenderMale a hc:AdministrativeGender .
    hc:P a hc:Patient ; hc:firstName "A"^^xsd:string ; hc:lastName "B"^^xsd:string ;
        hc:administrativeGender hc:GenderMale ; hc:bloodGroup "O+"^^xsd:string ;
        hc:dateOfBirth "1990-04-12"^^xsd:string .
    """
    result = validator.validate_rdf_text(data, rdf_format="turtle", shape_files=["patient_shapes.ttl"])
    assert result.summary.conforms is False
    assert any("xsd:date" in m for m in _messages(result))


def test_gender_must_be_a_vocabulary_concept(validator):
    data = """
    @prefix hc: <http://example.org/healthcare-hospital.owl#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    hc:P a hc:Patient ; hc:firstName "A"^^xsd:string ; hc:lastName "B"^^xsd:string ;
        hc:administrativeGender hc:NotAConcept ; hc:bloodGroup "O+"^^xsd:string ;
        hc:dateOfBirth "1990-04-12"^^xsd:date .
    """
    result = validator.validate_rdf_text(data, rdf_format="turtle", shape_files=["patient_shapes.ttl"])
    assert any("AdministrativeGender" in m for m in _messages(result))


@pytest.mark.parametrize(
    "fixture,shapes",
    [("valid_patient.ttl", ["patient_shapes.ttl"]), ("valid_doctor.ttl", ["doctor_shapes.ttl"])],
)
def test_minimal_valid_fixtures_conform_to_their_own_shapes(validator, sample_instances_dir, fixture, shapes):
    result = validator.validate_data_file(sample_instances_dir / fixture, shape_files=shapes)
    assert result.summary.conforms is True
