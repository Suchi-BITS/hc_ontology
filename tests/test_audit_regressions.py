"""Regression tests for the specific defects found by the architecture audit.

Each test names the finding it guards. They exercise the REAL sample data and the real
shapes, and each one was checked to fail when the defect is reintroduced.
"""

from __future__ import annotations

import pytest
from rdflib import OWL, RDF, XSD, Graph, Literal, Namespace

from services.graph_projection import build_projection
from tests.reasoning import needs_java, reason

HC = Namespace("http://example.org/healthcare-hospital.owl#")


@pytest.fixture(scope="module")
def sample(project_root):
    from core.dataset import Dataset

    return Dataset.default().graph()


def copy(graph: Graph) -> Graph:
    out = Graph()
    for triple in graph:
        out.add(triple)
    return out


def violations(result, severity="Violation"):
    return [v for v in result.violations if v.severity == severity]


# ---- Finding: "Metformin and insulin are typed as Analgesic" -----------------------------

@pytest.mark.parametrize("drug", ["Metformin", "InsulinGlargine"])
def test_antidiabetic_drugs_are_not_analgesics_in_any_layer(sample, client, drug):
    # RDF: the only asserted type is Medication, and the category is Antidiabetic
    assert set(sample.objects(HC[drug], RDF.type)) == {OWL.NamedIndividual, HC.Medication}
    assert set(sample.objects(HC[drug], HC.medicationCategory)) == {HC.MedCategoryAntidiabetic}
    # the class that caused the bug no longer exists, so it cannot be chosen again
    assert (HC.Analgesic, RDF.type, OWL.Class) not in sample
    # graph projection: labels carry no therapeutic class
    node = next(n for n in build_projection(sample).nodes if n.properties["name"] == drug)
    assert set(node.labels) == {"Resource", "Medication"}
    # API: there is no Analgesic class to list or to query
    assert "Analgesic" not in client.get("/classes").json()
    assert client.get("/instances/Analgesic").status_code == 404
    assert drug in client.get("/instances/Medication").json()


# ---- Finding: "PatientJohn violates PatientShape" ------------------------------------------

def test_patient_john_conforms_and_is_actually_checked(validator, sample):
    result = validator.validate_graph(copy(sample), data_source="sample")
    assert [v for v in violations(result) if "PatientJohn" in v.focus_node] == []
    # ...and the check is real: take away what PatientShape requires and John must fail
    broken = copy(sample)
    broken.remove((HC.PatientJohn, HC.dateOfBirth, None))
    failing = violations(validator.validate_graph(broken, data_source="mutated"))
    john = [v for v in failing if "PatientJohn" in v.focus_node]
    assert any("dateOfBirth" in (v.result_path or "") for v in john)


@pytest.mark.parametrize(
    "subject,prop,message",
    [
        ("PatientJohn", "firstName", "firstName"),
        ("PatientJohn", "lastName", "lastName"),
        ("PatientJohn", "dateOfBirth", "dateOfBirth"),
        ("PatientJohn", "bloodGroup", "bloodGroup"),
        ("DrSmith", "hasSpecialty", "specialty"),
        ("DiagnosisHypertension", "hasCode", "CodeConcept"),
        ("DiagnosisHypertension", "diagnosedBy", "doctor"),
        ("DiagnosisHypertension", "diagnosisName", "diagnosisName"),
        ("Encounter001", "encounterType", "encounterType"),
        ("Encounter001", "encounterStart", "encounterStart"),
        ("Observation001", "observationUnit", "observationUnit"),
        ("Icd10_I10", "codeValue", "codeValue"),
        ("IdMrnJohn", "identifierValue", "identifierValue"),
        ("AllergyBobAmoxicillin", "allergyToMedication", "medication"),
    ],
)
def test_removing_a_required_property_from_real_data_is_detected(validator, sample, subject, prop, message):
    broken = copy(sample)
    assert (HC[subject], HC[prop], None) in broken, f"{subject} has no {prop} to remove"
    broken.remove((HC[subject], HC[prop], None))
    result = validator.validate_graph(broken, data_source="mutated")
    assert any(message in (v.message or "") and subject in v.focus_node for v in violations(result)), [
        (v.focus_node.split("#")[-1], v.message) for v in violations(result)
    ]


# ---- Finding: dates were free strings ---------------------------------------------------------

@pytest.mark.parametrize(
    "literal",
    [
        Literal("1985-03-14", datatype=XSD.string),
        Literal("14/03/1985", datatype=XSD.date),
        Literal("1985-13-01", datatype=XSD.date),
        Literal("1985-02-30", datatype=XSD.date),
        Literal("not a date", datatype=XSD.date),
    ],
    ids=["string", "wrong-format", "month-13", "feb-30", "garbage"],
)
def test_invalid_dates_of_birth_fail(validator, sample, literal):
    broken = copy(sample)
    broken.remove((HC.PatientJohn, HC.dateOfBirth, None))
    broken.add((HC.PatientJohn, HC.dateOfBirth, literal))
    result = validator.validate_graph(broken, data_source="mutated")
    assert any("xsd:date" in (v.message or "") and "PatientJohn" in v.focus_node for v in violations(result))


# Not testable here: rdflib canonicalizes a typed literal on construction/parsing, so a
# malformed-but-parseable form such as "2026-03-01 09:30:00Z" arrives as a normal dateTime
# ("2026-03-01T09:30:00+00:00") and is accepted. Lexical-form defects must be caught at the
# source (the generator/loader), not by SHACL.
@pytest.mark.parametrize(
    "instant",
    ["2026-03-01T09:30:00", "09:30"],
    ids=["no-offset", "time-only"],
)
def test_instants_without_a_valid_dateTime_or_time_zone_fail(validator, sample, instant):
    broken = copy(sample)
    broken.remove((HC.Encounter001, HC.encounterStart, None))
    broken.add((HC.Encounter001, HC.encounterStart, Literal(instant, datatype=XSD.dateTime)))
    result = validator.validate_graph(broken, data_source="mutated")
    assert any("encounterStart" in (v.result_path or "") for v in violations(result))


# ---- Finding: relationships were not checked for the right target type ----------------------------

@pytest.mark.parametrize(
    "subject,prop,wrong_target,message",
    [
        ("PatientJohn", "hasEncounter", "DrSmith", "hasEncounter must point"),
        ("PatientJohn", "hasObservation", "DiagnosisHypertension", "hasObservation must point"),
        ("PatientBob", "hasAllergy", "PrescriptionDiabetesBob", "hasAllergy must point"),
        ("DiagnosisHypertension", "diagnosedBy", "NurseMary", "linked to a doctor"),
        ("Encounter001", "encounterType", "DrSmith", "exactly one encounterType"),
        ("AllergyBobAmoxicillin", "allergyToMedication", "PatientBob", "must name the medication"),
        ("DrSmith", "hasSpecialty", "CityHospital", "hasSpecialty values must be"),
        ("Metformin", "medicationCategory", "PatientJohn", "medicationCategory"),
    ],
)
def test_relationship_to_the_wrong_kind_of_thing_fails_even_with_the_schema_loaded(
    validator, sample, subject, prop, wrong_target, message
):
    """The schema (with its rdfs:range) is in the data graph. Range must not 'repair' the mistake."""
    broken = copy(sample)
    broken.remove((HC[subject], HC[prop], None))
    broken.add((HC[subject], HC[prop], HC[wrong_target]))
    result = validator.validate_graph(broken, data_source="mutated")
    found = [v for v in result.violations if message in (v.message or "")]
    assert found, [(v.severity, v.message) for v in result.violations]


def test_entailment_adds_hierarchy_but_never_domain_or_range():
    from core.shacl_validator import entail_hierarchy

    g = Graph()
    g.parse(
        data="""
        @prefix hc: <http://example.org/healthcare-hospital.owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        hc:Diagnosis rdfs:subClassOf hc:Condition .
        hc:hasDiagnosis rdfs:subPropertyOf hc:hasCondition ; rdfs:range hc:Diagnosis ; rdfs:domain hc:Patient .
        hc:p hc:hasDiagnosis hc:d .
        hc:d a hc:Diagnosis .
        hc:x hc:hasDiagnosis hc:oops .
        """,
        format="turtle",
    )
    out = entail_hierarchy(g)
    assert (HC.d, RDF.type, HC.Condition) in out  # subclass entailed
    assert (HC.p, HC.hasCondition, HC.d) in out  # sub-property entailed
    assert (HC.oops, RDF.type, HC.Diagnosis) not in out  # range NOT entailed
    assert (HC.x, RDF.type, HC.Patient) not in out  # domain NOT entailed
    assert len(g) < len(out)


@needs_java
def test_owl_reasoner_catches_a_relationship_used_by_the_wrong_kind_of_thing(sample):
    """The OWL-level guard: domain + disjointness make a medication 'having an encounter' inconsistent."""
    from owlready2 import OwlReadyInconsistentOntologyError

    broken = copy(sample)
    broken.add((HC.Metformin, HC.hasEncounter, HC.Encounter001))  # domain Patient; Medication is disjoint from Person
    with pytest.raises(OwlReadyInconsistentOntologyError):
        reason(broken)


@needs_java
def test_the_unmutated_sample_is_consistent_so_the_check_above_is_meaningful(sample):
    world, _ = reason(copy(sample))
    assert list(world.inconsistent_classes()) == []


# ---- Finding: a Diagnosis individual was shared between patients ------------------------------------------

def test_sharing_one_diagnosis_between_patients_fails_in_real_data(validator, sample):
    broken = copy(sample)
    broken.add((HC.PatientEmma, HC.hasDiagnosis, HC.DiagnosisHypertension))  # John's diagnosis
    result = validator.validate_graph(broken, data_source="mutated")
    assert any("at most one patient" in (v.message or "") for v in violations(result))


def test_allergy_conflict_is_caught_in_real_data(validator, sample):
    broken = copy(sample)
    broken.add((HC.PrescriptionDiabetesBob, HC.containsMedication, HC.Amoxicillin))  # Bob is allergic
    result = validator.validate_graph(broken, data_source="mutated")
    assert any("allergic" in (v.message or "") and "PrescriptionDiabetesBob" in v.focus_node for v in violations(result))
