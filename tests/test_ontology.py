"""Ontology-level tests: the model itself, not the API around it.

Every test here is written to FAIL if a known modeling mistake returns. The
tests read the schema + sample data (core/dataset.py) with rdflib (no reasoner) except the last
group, which runs a real OWL reasoner and is skipped when Java is unavailable.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef
from rdflib.compare import isomorphic

ROOT = Path(__file__).resolve().parent.parent
from core.dataset import Dataset  # noqa: E402

OWL_FILE = Dataset.default()  # schema + sample data
HC = Namespace("http://example.org/healthcare-hospital.owl#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")


@pytest.fixture(scope="module")
def g() -> Graph:
    graph = Graph()
    graph += OWL_FILE.graph()
    return graph


def classes(g):
    return {c for c in g.subjects(RDF.type, OWL.Class) if isinstance(c, URIRef)}


def obj_props(g):
    return set(g.subjects(RDF.type, OWL.ObjectProperty))


def data_props(g):
    return set(g.subjects(RDF.type, OWL.DatatypeProperty))


def local(uri) -> str:
    return str(uri).split("#")[-1]


def individuals(g):
    return set(g.subjects(RDF.type, OWL.NamedIndividual))


def types_of(g, ind):
    return {local(t) for t in g.objects(ind, RDF.type) if str(t).startswith(str(HC))}


# ---------------------------------------------------------------------------
# Expected classes and the absence of known anti-patterns
# ---------------------------------------------------------------------------

CORE_CLASSES = {
    "Person", "Patient", "Practitioner", "Doctor", "Nurse", "Organization", "Hospital",
    "Department", "Location", "Encounter", "Appointment", "Condition", "Diagnosis",
    "Observation", "VitalSign", "DiagnosticResult", "Procedure", "Surgery", "Medication",
    "Prescription", "Allergy", "Identifier", "CodeConcept", "Specialty",
    "AdministrativeGender", "EncounterType", "MedicationCategory",
}

# Classes removed by the redesign. If one comes back, the old modeling problem came back.
REMOVED_CLASSES = {
    # specialty / role encoded as subclass of Doctor and Department
    "Cardiologist", "Neurologist", "Radiologist", "Pediatrician", "Surgeon", "Physician",
    "CardiologyDepartment", "NeurologyDepartment", "EmergencyDepartment", "ICUDepartment",
    "OrthopedicDepartment", "PediatricsDepartment", "OncologyDepartment",
    "RadiologyDepartment", "PharmacyDepartment", "LaboratoryDepartment",
    # therapeutic category encoded as subclass of Medication (source of "metformin is an Analgesic")
    "Analgesic", "Antibiotic", "Antiviral", "Vaccine", "ControlledDrug",
    # encounter setting split across unrelated classes
    "Admission", "Discharge", "EmergencyCase", "InpatientRecord", "OutpatientRecord", "EmergencyRecord",
    # imaging modeled as laboratory test, results typed as lab results
    "LabResult", "MRI", "CTScan", "XRay", "Ultrasound", "BloodTest", "UrineTest",
    # unused, unjustified
    "BloodBank",
}


def test_core_classes_exist(g):
    present = {local(c) for c in classes(g)}
    assert CORE_CLASSES <= present, f"missing: {sorted(CORE_CLASSES - present)}"


def test_removed_classes_stay_removed(g):
    present = {local(c) for c in classes(g)}
    assert not (REMOVED_CLASSES & present), sorted(REMOVED_CLASSES & present)


def test_all_classes_live_in_the_hc_namespace(g):
    for c in classes(g):
        assert str(c).startswith(str(HC)), c


# ---------------------------------------------------------------------------
# Class hierarchy: only genuine is-a relationships
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("child,parent", [
    ("Patient", "Person"), ("Practitioner", "Person"), ("Doctor", "Practitioner"),
    ("Nurse", "Practitioner"), ("Hospital", "Organization"), ("Department", "Organization"),
    ("Ward", "Location"), ("Room", "Location"), ("Bed", "Location"),
    ("Diagnosis", "Condition"), ("VitalSign", "Observation"), ("DiagnosticResult", "Observation"),
    ("Surgery", "Procedure"), ("LaboratoryTest", "DiagnosticTest"), ("ImagingStudy", "DiagnosticTest"),
    ("SurgicalTreatment", "Treatment"),
])
def test_subclass_relationships(g, child, parent):
    assert (HC[child], RDFS.subClassOf, HC[parent]) in g


@pytest.mark.parametrize("vocab", ["Specialty", "AdministrativeGender", "EncounterType", "MedicationCategory"])
def test_controlled_vocabulary_classes_are_skos_concepts(g, vocab):
    assert (HC[vocab], RDFS.subClassOf, SKOS.Concept) in g


def test_surgery_is_not_disjoint_from_its_own_parent(g):
    """The old model declared Surgery disjoint from Procedure while treating it as one."""
    assert (HC.Surgery, OWL.disjointWith, HC.Procedure) not in g
    assert (HC.Procedure, OWL.disjointWith, HC.Surgery) not in g
    for members in g.subjects(RDF.type, OWL.AllDisjointClasses):
        listed = set()
        for lst in g.objects(members, OWL.members):
            listed |= set(g.items(lst))
        assert not ({HC.Surgery, HC.Procedure} <= listed)


def test_roles_are_not_declared_disjoint(g):
    """A nurse can also be a patient; Patient and Practitioner must overlap."""
    for members in g.subjects(RDF.type, OWL.AllDisjointClasses):
        listed = set()
        for lst in g.objects(members, OWL.members):
            listed |= set(g.items(lst))
        assert not ({HC.Patient, HC.Practitioner} <= listed)
        assert not ({HC.Patient, HC.Doctor} <= listed)


# ---------------------------------------------------------------------------
# Properties: inverses, hierarchy, characteristics
# ---------------------------------------------------------------------------

INVERSE_PAIRS = [
    ("hasEncounter", "encounterForPatient"), ("participatesIn", "hasParticipant"),
    ("diagnoses", "diagnosedIn"), ("includesObservation", "observedDuring"),
    ("involvesProcedure", "performedDuring"), ("hasObservation", "observationForPatient"),
    ("hasDiagnosis", "diagnosisForPatient"), ("hasCondition", "conditionSubject"),
    ("hasAppointment", "appointmentForPatient"), ("prescribedFor", "hasPrescription"),
    ("hasDepartment", "belongsToHospital"), ("containsRoom", "locatedInWard"),
    ("containsBed", "locatedInRoom"), ("producesResult", "resultOfTest"),
    ("requiresTreatment", "treatsDiagnosis"), ("fulfilledBy", "fulfillsAppointment"),
]


@pytest.mark.parametrize("a,b", INVERSE_PAIRS)
def test_inverse_properties(g, a, b):
    forward = (HC[a], OWL.inverseOf, HC[b]) in g
    backward = (HC[b], OWL.inverseOf, HC[a]) in g
    assert forward or backward, f"{a} / {b} are not declared inverses"


def test_encounter_relationships_have_correct_domain_and_range(g):
    expected = {
        "hasEncounter": ("Patient", "Encounter"),
        "participatesIn": ("Practitioner", "Encounter"),
        "diagnoses": ("Encounter", "Condition"),
        "includesObservation": ("Encounter", "Observation"),
        "involvesProcedure": ("Encounter", "Procedure"),
    }
    for prop, (dom, rng) in expected.items():
        assert (HC[prop], RDFS.domain, HC[dom]) in g, prop
        assert (HC[prop], RDFS.range, HC[rng]) in g, prop


@pytest.mark.parametrize("sub,sup", [
    ("hasDiagnosis", "hasCondition"), ("diagnosisForPatient", "conditionSubject"),
    ("involvesSurgery", "includesProcedure"), ("locatedInWard", "partOfLocation"),
    ("locatedInRoom", "partOfLocation"),
])
def test_property_hierarchy(g, sub, sup):
    assert (HC[sub], RDFS.subPropertyOf, HC[sup]) in g


def test_part_of_location_is_transitive(g):
    assert (HC.partOfLocation, RDF.type, OWL.TransitiveProperty) in g


@pytest.mark.parametrize("prop", [
    "dateOfBirth", "encounterStart", "encounterEnd", "administrativeGender", "encounterType",
    "encounterForPatient", "conditionSubject", "observationForPatient", "observationValue",
    "observationUnit", "effectiveDateTime", "codeSystem", "codeValue", "identifierSystem",
    "identifierValue", "appointmentForPatient", "prescribedFor",
    # single-valued attributes (the Neo4j projection stores these as scalars)
    "firstName", "lastName", "bloodGroup", "diagnosisName", "medicationName", "hospitalName",
    "departmentName", "treatmentName", "testName", "appointmentStatus", "treatmentStatus",
])
def test_single_valued_properties_are_functional(g, prop):
    assert (HC[prop], RDF.type, OWL.FunctionalProperty) in g


@pytest.mark.parametrize("prop", ["phoneNumber", "emailAddress", "address", "emergencyContact", "observationValueText"])
def test_genuinely_multi_valued_attributes_are_not_functional(g, prop):
    assert (HC[prop], RDF.type, OWL.FunctionalProperty) not in g


def test_specialty_is_a_property_not_a_subclass(g):
    assert (HC.hasSpecialty, RDF.type, OWL.ObjectProperty) in g
    assert (HC.hasSpecialty, RDFS.range, HC.Specialty) in g
    assert (HC.specialization, RDF.type, OWL.DatatypeProperty) not in g


def test_removed_properties_stay_removed(g):
    present = {local(p) for p in obj_props(g) | data_props(g)}
    removed = {
        "specialization", "diagnosisCode", "gender", "medicationCode", "procedureCode", "surgeryCode",
        "testCode", "personId", "patientNumber", "doctorLicenseNumber", "nurseLicenseNumber",
        "admittedTo", "dischargedFrom", "emergencyCaseFor", "handledByDoctor", "recordsVitalSign",
        "enteredByNurse", "appointmentDate", "appointmentTime", "resultValue", "resultDate",
        "surgeryDate", "admissionDate", "dischargeDate",
    }
    assert not (removed & present), sorted(removed & present)


def test_dosage_belongs_to_the_prescription_not_the_drug(g):
    assert (HC.dosageInstruction, RDFS.domain, HC.Prescription) in g
    assert (HC.dosage, RDF.type, OWL.DatatypeProperty) not in g


# ---------------------------------------------------------------------------
# Datatypes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prop,datatype", [
    ("dateOfBirth", XSD.date), ("onsetDate", XSD.date), ("diagnosisDate", XSD.date),
    ("prescriptionDate", XSD.date), ("invoiceDate", XSD.date), ("testDate", XSD.date),
    ("encounterStart", XSD.dateTime), ("encounterEnd", XSD.dateTime), ("scheduledStart", XSD.dateTime),
    ("effectiveDateTime", XSD.dateTime), ("performedDateTime", XSD.dateTime),
    ("observationValue", XSD.decimal), ("totalBeds", XSD.integer),
    ("isControlledSubstance", XSD.boolean),
    ("codeSystem", XSD.anyURI), ("identifierSystem", XSD.anyURI),
])
def test_datatype_ranges(g, prop, datatype):
    assert (HC[prop], RDFS.range, datatype) in g


def test_no_temporal_property_is_a_string(g):
    suffixes = ("Date", "DateTime", "Time", "Start", "End")
    for p in data_props(g):
        if local(p).endswith(suffixes):
            assert (p, RDFS.range, XSD.string) not in g, f"{local(p)} is temporal but typed xsd:string"


def test_temporal_literals_match_their_declared_precision(g):
    """Dates carry no time; instants (dateTime) always carry a time zone offset."""
    for s, p, o in g:
        if not isinstance(o, Literal) or o.datatype not in (XSD.date, XSD.dateTime):
            continue
        lex = str(o)
        if o.datatype == XSD.date:
            assert len(lex) == 10 and "T" not in lex, (s, p, lex)
        else:
            assert lex.endswith("Z") or lex[-6] in "+-", f"dateTime without time zone: {local(s)} {local(p)} {lex}"


# ---------------------------------------------------------------------------
# Documentation quality: labels and definitions
# ---------------------------------------------------------------------------

def test_every_class_has_label_and_meaningful_comment(g):
    for c in classes(g):
        labels = list(g.objects(c, RDFS.label))
        comments = [str(x) for x in g.objects(c, RDFS.comment)]
        assert labels, f"{local(c)} has no rdfs:label"
        assert comments and all(len(x) >= 25 for x in comments), f"{local(c)} has no real rdfs:comment"
        # Intent: the label is a readable phrase, not the identifier pasted back. A multi-word CamelCase class name
        # (AntidiabeticMedication) must be spelled out with spaces ("antidiabetic medication").
        words = re.findall(r"[A-Z][a-z0-9]*", local(c))
        if len(words) > 1:
            assert " " in str(labels[0]), f"{local(c)} is labelled {str(labels[0])!r}, which is just the identifier"


def test_every_property_has_label_and_object_properties_have_comments(g):
    for p in data_props(g) | obj_props(g):
        assert list(g.objects(p, RDFS.label)), f"{local(p)} has no label"
        assert list(g.objects(p, RDFS.comment)), f"{local(p)} has no comment"


def test_ontology_header_carries_version_and_description(g):
    header = next(iter(g.subjects(RDF.type, OWL.Ontology)))
    assert list(g.objects(header, OWL.versionInfo))
    assert list(g.objects(header, RDFS.label))
    assert list(g.objects(header, RDFS.comment))


# ---------------------------------------------------------------------------
# Controlled vocabularies and code binding
# ---------------------------------------------------------------------------

def test_every_vocabulary_concept_has_label_and_scheme(g):
    vocab = {HC.Specialty, HC.AdministrativeGender, HC.EncounterType, HC.MedicationCategory}
    concepts = [i for i in individuals(g) if set(g.objects(i, RDF.type)) & vocab]
    assert len(concepts) >= 20
    for c in concepts:
        assert list(g.objects(c, SKOS.prefLabel)), local(c)
        assert list(g.objects(c, SKOS.inScheme)), local(c)


def test_code_concepts_follow_the_binding_pattern(g):
    codes = [i for i in individuals(g) if HC.CodeConcept in set(g.objects(i, RDF.type))]
    assert len(codes) >= 8
    systems = set()
    for c in codes:
        system = next(g.objects(c, HC.codeSystem), None)
        assert system is not None and system.datatype == XSD.anyURI, local(c)
        for prop in (HC.codeValue, HC.codeDisplay):
            value = next(g.objects(c, prop), None)
            assert isinstance(value, Literal) and str(value).strip(), f"{local(c)} has no usable {local(prop)}"
        systems.add(str(system))
    assert {"http://hl7.org/fhir/sid/icd-10", "http://loinc.org"} <= systems


def test_diagnoses_are_bound_to_codes_via_hascode(g):
    diagnoses = [i for i in individuals(g) if HC.Diagnosis in set(g.objects(i, RDF.type))]
    assert len(diagnoses) == 5, "one Diagnosis record per patient"
    for d in diagnoses:
        assert list(g.objects(d, HC.hasCode)), f"{local(d)} has no hasCode"


# ---------------------------------------------------------------------------
# Instance-level regressions: the specific mistakes the audit found
# ---------------------------------------------------------------------------

def test_metformin_and_insulin_are_antidiabetics_not_analgesics(g):
    for name in ("Metformin", "InsulinGlargine"):
        ind = HC[name]
        assert types_of(g, ind) == {"Medication"}, f"{name} must be a plain Medication, got {types_of(g, ind)}"
        cats = {local(c) for c in g.objects(ind, HC.medicationCategory)}
        assert cats == {"MedCategoryAntidiabetic"}, cats


def test_every_medication_has_a_category_and_no_therapeutic_class(g):
    meds = [i for i in individuals(g) if HC.Medication in set(g.objects(i, RDF.type))]
    assert len(meds) >= 6
    for m in meds:
        assert types_of(g, m) == {"Medication"}, local(m)
        assert list(g.objects(m, HC.medicationCategory)), f"{local(m)} has no medicationCategory"


def test_aspirin_has_two_categories(g):
    """Why category is a property: one drug can belong to several."""
    cats = {local(c) for c in g.objects(HC.Aspirin, HC.medicationCategory)}
    assert cats == {"MedCategoryAnalgesic", "MedCategoryAntiplatelet"}


def test_every_patient_has_dob_and_gender(g):
    """PatientJohn used to fail PatientShape because the DATA was incomplete."""
    patients = [i for i in individuals(g) if HC.Patient in set(g.objects(i, RDF.type))]
    assert HC.PatientJohn in patients
    for p in patients:
        dob = next(g.objects(p, HC.dateOfBirth), None)
        assert isinstance(dob, Literal) and dob.datatype == XSD.date, f"{local(p)} has no xsd:date dateOfBirth"
        gender = next(g.objects(p, HC.administrativeGender), None)
        assert gender in {HC.GenderMale, HC.GenderFemale, HC.GenderOther, HC.GenderUnknown}, f"{local(p)}: {gender}"


def test_a_diagnosis_record_belongs_to_exactly_one_patient(g):
    diagnoses = [i for i in individuals(g) if HC.Diagnosis in set(g.objects(i, RDF.type))]
    for d in diagnoses:
        owners = set(g.subjects(HC.hasDiagnosis, d))
        assert len(owners) == 1, f"{local(d)} belongs to {sorted(local(o) for o in owners)}"


def test_doctors_are_plain_doctors_with_a_specialty_concept(g):
    doctors = [i for i in individuals(g) if HC.Doctor in set(g.objects(i, RDF.type))]
    assert len(doctors) >= 4
    for d in doctors:
        assert types_of(g, d) == {"Doctor"}, f"{local(d)}: {types_of(g, d)}"
        specs = list(g.objects(d, HC.hasSpecialty))
        assert specs and all(HC.Specialty in set(g.objects(s, RDF.type)) for s in specs), local(d)
    assert (HC.DrSmith, HC.hasSpecialty, HC.SpecialtyCardiology) in g


def test_identity_is_not_the_name(g):
    """Business identifiers are Identifier individuals with a system, not name strings."""
    assert (HC.PatientJohn, HC.hasIdentifier, HC.IdMrnJohn) in g
    assert (HC.IdMrnJohn, HC.identifierType, Literal("MRN", datatype=XSD.string)) in g
    assert next(g.objects(HC.IdMrnJohn, HC.identifierAssigner), None) == HC.CityHospital


def test_encounter_links_patient_practitioner_and_clinical_facts(g):
    assert (HC.PatientJohn, HC.hasEncounter, HC.Encounter001) in g
    assert (HC.DrSmith, HC.participatesIn, HC.Encounter001) in g
    assert (HC.Encounter001, HC.diagnoses, HC.DiagnosisHypertension) in g
    assert (HC.Encounter001, HC.includesObservation, HC.Observation001) in g
    assert (HC.Encounter001, HC.involvesProcedure, HC.Procedure001) in g
    assert (HC.Appointment001, HC.fulfilledBy, HC.Encounter001) in g


def test_semantic_query_patients_by_diagnosis_code(g):
    """A knowledge-graph question the old string-code model could not answer by code system."""
    rows = g.query(
        """
        PREFIX hc: <http://example.org/healthcare-hospital.owl#>
        SELECT DISTINCT ?p WHERE {
          ?p hc:hasDiagnosis/hc:hasCode ?c .
          ?c hc:codeSystem "http://hl7.org/fhir/sid/icd-10"^^<http://www.w3.org/2001/XMLSchema#anyURI> ;
             hc:codeValue "E11"^^<http://www.w3.org/2001/XMLSchema#string> .
        }"""
    )
    assert {local(r[0]) for r in rows} == {"PatientAlice", "PatientBob"}


# ---------------------------------------------------------------------------
# The shipped file is the generator's output (single source of truth)
# ---------------------------------------------------------------------------

def test_committed_schema_and_sample_data_equal_their_generators_output():
    with tempfile.TemporaryDirectory() as tmp:
        schema_out, data_out = Path(tmp) / "schema.ttl", Path(tmp) / "data.ttl"
        subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_hc_ontology.py"), "--output", str(schema_out)],
                       check=True, capture_output=True, cwd=ROOT)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_sample_data.py"), "--output", str(data_out),
                        "--schema", str(schema_out)], check=True, capture_output=True, cwd=ROOT)
        generated_schema = Graph().parse(schema_out, format="turtle")
        generated_data = Graph().parse(data_out, format="turtle")
    assert isomorphic(generated_schema, Graph().parse(OWL_FILE.schema, format="turtle")), (
        "ontology/healthcare_schema.ttl differs from scripts/generate_hc_ontology.py output. "
        "Edit the generator and regenerate; do not hand-edit the schema.")
    assert isomorphic(generated_data, Graph().parse(OWL_FILE.data, format="turtle")), (
        "data/sample_data.ttl differs from scripts/generate_sample_data.py output. "
        "Edit data/source/*.csv or the generator and regenerate; do not hand-edit the data.")


# ---------------------------------------------------------------------------
# Reasoner-backed checks (HermiT via Owlready2; needs Java)
# ---------------------------------------------------------------------------

from tests.reasoning import needs_java, reason  # noqa: E402


@pytest.fixture(scope="module")
def reasoned():
    return reason(OWL_FILE.graph())


@needs_java
def test_ontology_is_consistent_and_satisfiable(reasoned):
    world, _ = reasoned
    assert list(world.inconsistent_classes()) == []


@needs_java
def test_reasoner_classifies_antidiabetic_medication(reasoned):
    """Defined class: membership is inferred from medicationCategory, never asserted."""
    _, onto = reasoned
    members = {i.name for i in onto.AntidiabeticMedication.instances()}
    assert members == {"Metformin", "InsulinGlargine"}
    assert onto.Aspirin not in onto.AntidiabeticMedication.instances()


@needs_java
def test_reasoner_classifies_inpatient_encounters(reasoned):
    _, onto = reasoned
    assert {i.name for i in onto.InpatientEncounter.instances()} == {"Encounter006"}


@needs_java
def test_reasoner_infers_inverse_and_transitive_relations(reasoned):
    _, onto = reasoned
    assert onto.Encounter001.encounterForPatient is onto.PatientJohn
    assert onto.DrSmith in onto.Encounter001.hasParticipant
    assert onto.Observation001.observedDuring == [onto.Encounter001]
    assert onto.Bed1.locatedInRoom == [onto.Room101]
    assert onto.WardA in onto.Bed1.partOfLocation  # bed -> room -> ward, by transitivity
