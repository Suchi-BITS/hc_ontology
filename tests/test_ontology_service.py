"""The Python service layer must keep working against the redesigned ontology.

These tests would have caught the two integration breaks found while redesigning:
functional properties return scalars (not lists) in Owlready2, and the old
`specialization` / `diagnosisCode` string properties no longer exist.
"""

import pytest

from core.dependencies import get_ontology


@pytest.fixture(scope="module")
def hc():
    return get_ontology()


def test_doctor_specialty_comes_from_the_vocabulary_concept(hc):
    by_name = {d["name"]: d["specialization"] for d in hc.get_doctors()}
    assert by_name["DrSmith"] == "Cardiology"
    assert by_name["DrJohn"] == "Neurology"
    assert by_name["DrKumar"] == "Internal medicine"


def test_every_doctor_is_found_without_specialty_subclasses(hc):
    assert {d["name"] for d in hc.get_doctors()} == {"DrSmith", "DrJohn", "DrWilliams", "DrKumar"}


def test_diagnosis_code_comes_from_the_code_concept(hc):
    result = hc.get_patient_diagnoses("PatientJohn")
    assert result["diagnoses"] == [
        {"diagnosis_name": "DiagnosisHypertension", "diagnosis_code": "I10", "diagnosis_title": "Hypertension"}
    ]


def test_doctor_patient_traversal_uses_inverse_of_functional_property(hc):
    result = hc.get_doctor_patients("DrKumar")
    assert {p["patient"] for p in result["patients"]} == {"PatientEmma", "PatientAlice", "PatientBob"}


def test_appointments_resolve_the_patient_of_a_functional_property(hc):
    rows = {a["appointment"]: a for a in hc.get_appointments()}
    assert rows["Appointment001"]["patient"] == "PatientJohn"
    assert rows["Appointment001"]["doctor"] == "DrSmith"
    assert rows["Appointment002"]["patient"] == "PatientEmma"


def test_each_diabetes_diagnosis_belongs_to_its_own_patient(hc):
    alice = hc.get_patient_diagnoses("PatientAlice")["diagnoses"]
    bob = hc.get_patient_diagnoses("PatientBob")["diagnoses"]
    assert [d["diagnosis_name"] for d in alice] == ["DiagnosisDiabetesAlice"]
    assert [d["diagnosis_name"] for d in bob] == ["DiagnosisDiabetesBob"]


def test_demo_seed_no_longer_rewrites_the_ontology(hc, tmp_path):
    from services.seed_demo_data import seed_demo_ontology

    result = seed_demo_ontology(hc)
    assert result["owl_saved"] is False
    assert "Metformin" in result["entities_present"]


def test_class_listing_exposes_the_new_core_and_hides_removed_classes(hc):
    classes = set(hc.get_classes())
    assert {"Encounter", "Condition", "Practitioner", "CodeConcept", "Identifier"} <= classes
    assert not ({"Cardiologist", "Analgesic", "Admission", "LabResult"} & classes)
