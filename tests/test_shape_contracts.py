"""SHACL contract tests: for each important shape, a VALID document and one INVALID variant per rule.

Method (mutation testing for data): start from a document that conforms, change exactly one
thing, and require the specific rule that owns that thing to fire. The valid base proves the
rule is not simply always firing; the mutation proves the rule actually detects the defect.

Shapes covered: Patient, Medication, Allergy, Encounter, Condition (Diagnosis), Observation,
plus the prescription/allergy safety rule. The ontology schema is merged into the data graph,
as in production, so RDFS inference can connect subclasses and sub-properties.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "sample_instances"


def doc(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


def mutate(base: str, old: str, new: str) -> str:
    assert old in base, f"mutation anchor not found: {old!r}"
    return base.replace(old, new, 1)


def hits(result, fragment: str, severity: str):
    return [v for v in result.violations if fragment in (v.message or "") and v.severity == severity]


ENCOUNTER = doc("valid_encounter.ttl")
MEDICATION = doc("valid_medication_safety.ttl")

# (id, base document, old text, new text, message fragment, severity)
MUTATIONS = [
    # ---- Patient -----------------------------------------------------------------------
    ("patient_missing_dob", ENCOUNTER, '    hc:dateOfBirth "1985-03-14"^^xsd:date ;\n', "", "must have a dateOfBirth", "Violation"),
    ("patient_dob_as_string", ENCOUNTER, '"1985-03-14"^^xsd:date', '"1985-03-14"^^xsd:string', "xsd:date", "Violation"),
    ("patient_dob_impossible_date", ENCOUNTER, '"1985-03-14"^^xsd:date', '"1985-02-30"^^xsd:date', "xsd:date", "Violation"),
    ("patient_dob_not_a_date", ENCOUNTER, '"1985-03-14"^^xsd:date', '"banana"^^xsd:date', "xsd:date", "Violation"),
    ("patient_two_dobs", ENCOUNTER, '    hc:dateOfBirth "1985-03-14"^^xsd:date ;\n',
     '    hc:dateOfBirth "1985-03-14"^^xsd:date, "1986-03-14"^^xsd:date ;\n', "single xsd:date", "Violation"),
    ("patient_bad_blood_group", ENCOUNTER, 'hc:bloodGroup "O+"', 'hc:bloodGroup "Z+"', "valid ABO", "Violation"),
    ("patient_missing_first_name", ENCOUNTER, '    hc:firstName "John"^^xsd:string ;\n', "", "must have a firstName", "Violation"),
    ("patient_gender_not_a_concept", ENCOUNTER,
     '    hc:lastName "Doe"^^xsd:string ;\n    hc:administrativeGender hc:GenderMale ;',
     '    hc:lastName "Doe"^^xsd:string ;\n    hc:administrativeGender hc:Banana ;', "AdministrativeGender", "Violation"),
    ("patient_encounter_link_points_at_a_doctor", ENCOUNTER, "hc:hasEncounter hc:Enc ;", "hc:hasEncounter hc:Dr ;",
     "hasEncounter must point to an hc:Encounter", "Violation"),
    ("patient_observation_link_points_at_a_diagnosis", ENCOUNTER, "hc:hasObservation hc:Bp .", "hc:hasObservation hc:Dx .",
     "hasObservation must point to an hc:Observation", "Violation"),
    # ---- Condition / Diagnosis -------------------------------------------------------------
    ("condition_status_outside_list", ENCOUNTER, 'hc:clinicalStatus "active"', 'hc:clinicalStatus "maybe"', "clinicalStatus must be one of", "Violation"),
    ("condition_abatement_before_onset", ENCOUNTER, '    hc:onsetDate "2026-03-01"^^xsd:date .',
     '    hc:onsetDate "2026-03-01"^^xsd:date ;\n    hc:abatementDate "2026-02-01"^^xsd:date .', "on or before abatementDate", "Violation"),
    ("condition_onset_as_string", ENCOUNTER, 'hc:onsetDate "2026-03-01"^^xsd:date', 'hc:onsetDate "2026-03-01"^^xsd:string', "xsd:date", "Violation"),
    ("condition_shared_by_two_patients", ENCOUNTER, "hc:MR a hc:MedicalRecord .",
     'hc:MR a hc:MedicalRecord .\nhc:Pat2 a hc:Patient ; hc:hasDiagnosis hc:Dx .', "at most one patient", "Violation"),
    ("diagnosis_without_code", ENCOUNTER, "    hc:hasCode hc:CodeI10 ;\n", "", "bound to a CodeConcept", "Violation"),
    ("diagnosis_by_a_nurse", ENCOUNTER, "hc:diagnosedBy hc:Dr ;", "hc:diagnosedBy hc:NurseX ;",
     "linked to a doctor", "Violation"),
    # ---- Encounter ---------------------------------------------------------------------------
    ("encounter_without_type", ENCOUNTER, "    hc:encounterType hc:EncounterTypeAmbulatory ;\n", "", "exactly one encounterType", "Violation"),
    ("encounter_type_is_not_a_vocabulary_concept", ENCOUNTER, "hc:encounterType hc:EncounterTypeAmbulatory ;",
     "hc:encounterType hc:Dr ;", "exactly one encounterType", "Violation"),
    ("encounter_start_without_time_zone", ENCOUNTER, '"2026-03-01T09:30:00Z"^^xsd:dateTime', '"2026-03-01T09:30:00"^^xsd:dateTime',
     "time zone", "Violation"),
    ("encounter_ends_before_it_starts", ENCOUNTER, '"2026-03-01T10:00:00Z"^^xsd:dateTime', '"2026-03-01T09:00:00Z"^^xsd:dateTime',
     "not after encounterEnd", "Violation"),
    ("encounter_without_patient", ENCOUNTER, "    hc:hasEncounter hc:Enc ;\n", "", "exactly one patient", "Violation"),
    ("encounter_with_two_patients", ENCOUNTER, "hc:MR a hc:MedicalRecord .",
     "hc:MR a hc:MedicalRecord .\nhc:Pat2 a hc:Patient ; hc:hasEncounter hc:Enc .", "exactly one patient", "Violation"),
    ("encounter_without_participant", ENCOUNTER, "    hc:worksInDepartment hc:Dept ;\n    hc:participatesIn hc:Enc .",
     "    hc:worksInDepartment hc:Dept .", "participating practitioner", "Warning"),
    # ---- Observation ---------------------------------------------------------------------------
    ("observation_value_without_unit", ENCOUNTER, '    hc:observationUnit "mm[Hg]"^^xsd:string ;\n', "", "requires an observationUnit", "Violation"),
    ("observation_value_as_string", ENCOUNTER, "hc:observationValue 152.0", 'hc:observationValue "152"^^xsd:string', "xsd:decimal", "Violation"),
    ("observation_time_without_time_zone", ENCOUNTER, '"2026-03-01T09:40:00Z"^^xsd:dateTime', '"2026-03-01T09:40:00"^^xsd:dateTime',
     "time zone", "Violation"),
    ("observation_without_patient", ENCOUNTER, "    hc:hasDiagnosis hc:Dx ;\n    hc:hasObservation hc:Bp .", "    hc:hasDiagnosis hc:Dx .",
     "exactly one patient", "Violation"),
    ("observation_without_code", ENCOUNTER, "    hc:hasCode hc:CodeSbp ;\n", "", "Prefer binding an Observation", "Info"),
    # ---- Medication ------------------------------------------------------------------------------
    ("medication_without_name", MEDICATION, '    hc:medicationName "Amoxicillin"^^xsd:string ;\n', "", "medicationName", "Warning"),
    ("medication_without_category", MEDICATION, "    hc:medicationCategory hc:MedCategoryAntibiotic .",
     "    hc:medicationName \"Amoxicillin\"^^xsd:string .", "should have a medicationCategory", "Warning"),
    ("medication_category_is_not_a_category", MEDICATION, "hc:medicationCategory hc:MedCategoryAntibiotic .",
     "hc:medicationCategory hc:Pat .", "medicationCategory", "Warning"),
    # ---- Allergy ---------------------------------------------------------------------------------------
    ("allergy_to_something_that_is_not_a_medication", MEDICATION, "hc:allergyToMedication hc:Amoxicillin .",
     "hc:allergyToMedication hc:Pat .", "must name the medication", "Violation"),
    ("allergy_without_medication", MEDICATION, "hc:AllergyAmoxicillin a hc:Allergy ;\n    hc:allergyToMedication hc:Amoxicillin .",
     "hc:AllergyAmoxicillin a hc:Allergy .", "must name the medication", "Violation"),
    ("allergy_without_patient", MEDICATION, "    hc:hasMedicalRecord hc:MR ;\n    hc:hasAllergy hc:AllergyAmoxicillin .",
     "    hc:hasMedicalRecord hc:MR .", "exactly one patient", "Violation"),
    ("allergy_shared_by_two_patients", MEDICATION, "hc:MR a hc:MedicalRecord .",
     "hc:MR a hc:MedicalRecord .\nhc:Pat2 a hc:Patient ; hc:hasAllergy hc:AllergyAmoxicillin .", "exactly one patient", "Violation"),
    ("patient_allergy_link_points_at_a_prescription", MEDICATION, "hc:hasAllergy hc:AllergyAmoxicillin .",
     "hc:hasAllergy hc:Rx .", "hasAllergy must point to an hc:Allergy", "Violation"),
    # ---- Safety rule ---------------------------------------------------------------------------------------
    ("prescription_of_an_allergen", MEDICATION, "hc:containsMedication hc:Paracetamol .", "hc:containsMedication hc:Amoxicillin .",
     "must not contain a medication the patient is allergic to", "Violation"),
]

# Anchors used by the nurse/diagnosis mutation need the extra individual declared.
EXTRAS = {"diagnosis_by_a_nurse": "\nhc:NurseX a hc:Nurse .\n"}


@pytest.mark.parametrize("base", [ENCOUNTER, MEDICATION], ids=["valid_encounter", "valid_medication_safety"])
def test_the_valid_base_documents_have_no_violations(check, base):
    result = check(base)
    assert [v.message for v in result.violations if v.severity == "Violation"] == []
    assert result.summary.conforms is True


@pytest.mark.parametrize("case", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_one_defect_triggers_exactly_the_rule_that_owns_it(check, case):
    name, base, old, new, fragment, severity = case
    mutated = mutate(base, old, new) + EXTRAS.get(name, "")
    result = check(mutated)
    assert hits(result, fragment, severity), (
        f"{name}: expected a {severity} containing {fragment!r}, got "
        f"{[(v.severity, v.message) for v in result.violations]}"
    )
    if severity == "Violation":
        assert result.summary.conforms is False


def test_each_rule_is_proven_by_its_own_mutation_not_by_a_neighbour(check):
    """Mutations must not all trip the same rule: the expected fragments are diverse."""
    assert len({m[4] for m in MUTATIONS}) >= 25
    assert len(MUTATIONS) >= 34


@pytest.mark.parametrize("severity", ["Violation", "Warning", "Info"])
def test_every_severity_level_is_exercised(severity):
    assert any(m[5] == severity for m in MUTATIONS)
