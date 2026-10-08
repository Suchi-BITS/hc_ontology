"""Final semantic review: inverse decisions, the person/practitioner/patient model, temporal ordering, closed shapes,
and a guard against vacuous assertions. See docs/ontology-engineering.md, sections 16 to 19."""

from __future__ import annotations

import ast
import csv
import glob
from pathlib import Path

import pytest
from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

from core.dataset import Dataset
from tests.reasoning import needs_java, reason

ROOT = Path(__file__).resolve().parent.parent
HC = Namespace("http://example.org/healthcare-hospital.owl#")
SH = Namespace("http://www.w3.org/ns/shacl#")
PREFIXES = """@prefix hc: <http://example.org/healthcare-hospital.owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
"""


def local(term) -> str:
    return str(term).split("#")[-1]


@pytest.fixture(scope="module")
def schema():
    return Graph().parse(Dataset.default().schema, format="turtle")


@pytest.fixture(scope="module")
def combined():
    return Dataset.default().graph()


# ===========================================================================================================
# 1. Inverse properties: every object property has a recorded decision, and the schema matches the decisions
# ===========================================================================================================

@pytest.fixture(scope="module")
def decisions():
    with open(ROOT / "ontology" / "inverse_decisions.csv", encoding="utf-8", newline="") as fh:
        return {row["property"]: row for row in csv.DictReader(fh)}


def object_properties(schema):
    return {local(p) for p in schema.subjects(RDF.type, OWL.ObjectProperty)}


def declared_inverses(schema):
    pairs = {}
    for a, b in schema.subject_objects(OWL.inverseOf):
        pairs[local(a)], pairs[local(b)] = local(b), local(a)
    return pairs


def test_every_object_property_has_exactly_one_documented_decision(schema, decisions):
    assert set(decisions) == object_properties(schema), (
        f"undocumented: {sorted(object_properties(schema) - set(decisions))}; "
        f"stale: {sorted(set(decisions) - object_properties(schema))}")


def test_decisions_use_the_four_categories_and_always_give_a_reason(decisions):
    assert {d["decision"] for d in decisions.values()} == {"A", "B", "C", "D"}
    for name, d in decisions.items():
        assert len(d["rationale"]) > 40, f"{name}: the rationale is too thin to be a decision"


def test_the_schema_declares_an_inverse_exactly_where_the_decision_is_A(schema, decisions):
    pairs = declared_inverses(schema)
    for name, d in decisions.items():
        if d["decision"] == "A":
            assert pairs.get(name) == d["inverse"], f"{name}: decision A, but the schema declares {pairs.get(name)!r}"
            assert decisions[d["inverse"]]["decision"] == "A" and decisions[d["inverse"]]["inverse"] == name
        else:
            assert name not in pairs, f"{name} is {d['decision']} (no inverse) but the schema declares one"
            assert d["inverse"] == ""


def test_only_a_minority_of_properties_were_given_inverses_none_artificially(schema, decisions):
    """The audit's 42 uninverted properties were not all 'fixed': 32 stay without an inverse, each with a reason."""
    without = [n for n, d in decisions.items() if d["decision"] != "A"]
    assert len(without) == 32
    assert sum(1 for d in decisions.values() if d["decision"] == "A") == 54      # 27 pairs
    assert {d["decision"] for n, d in decisions.items() if n in {"hasCode", "hasSpecialty", "medicationCategory",
                                                                 "administrativeGender", "encounterType"}} == {"D"}


def test_inverse_pairs_swap_domain_and_range(schema, decisions):
    for name, d in decisions.items():
        if d["decision"] != "A":
            continue
        inv = d["inverse"]
        assert set(schema.objects(HC[name], RDFS.domain)) == set(schema.objects(HC[inv], RDFS.range)) or \
            _union_members(schema, HC[name], RDFS.domain) == _union_members(schema, HC[inv], RDFS.range), (name, inv)
        assert _union_members(schema, HC[name], RDFS.range) == _union_members(schema, HC[inv], RDFS.domain), (name, inv)


def _union_members(schema, prop, predicate):
    out = set()
    for o in schema.objects(prop, predicate):
        if isinstance(o, URIRef):
            out.add(o)
        else:
            for lst in schema.objects(o, OWL.unionOf):
                out |= set(schema.items(lst))
    return out


NEW_PAIRS = [("hasAllergy", "allergyForPatient"), ("receivesTreatment", "treatmentForPatient"),
             ("underwentTest", "testForPatient"), ("diagnosedBy", "madeDiagnosis"), ("prescribedBy", "issuedPrescription"),
             ("containsMedication", "containedInPrescription"), ("orderedTest", "orderedBy"),
             ("containsWard", "wardOfDepartment"), ("worksInDepartment", "hasStaffMember"), ("reportsTo", "supervises"),
             ("managesDepartment", "managedBy")]


@pytest.mark.parametrize("a,b", NEW_PAIRS)
def test_each_added_inverse_is_declared_with_a_comment_that_says_it_is_inferred(schema, a, b):
    assert (HC[a], OWL.inverseOf, HC[b]) in schema or (HC[b], OWL.inverseOf, HC[a]) in schema
    comment = str(next(schema.objects(HC[b], RDFS.comment)))
    assert "Inferred as the inverse of" in comment and a in comment


def test_the_decision_table_in_the_documentation_matches_the_decisions(decisions):
    text = (ROOT / "docs" / "ontology-engineering.md").read_text(encoding="utf-8")
    for name, d in decisions.items():
        line = f"| `{name}` | {d['decision']} | " + (f"`{d['inverse']}`" if d["inverse"] else "none") + " |"
        assert line in text, f"docs/ontology-engineering.md does not carry the decision for {name}"


@needs_java
def test_the_reasoner_infers_the_added_inverses_from_the_sample_data():
    world, onto = reason(Dataset.default().graph())
    assert list(world.inconsistent_classes()) == []
    assert onto.AllergyBobAmoxicillin.allergyForPatient.name == "PatientBob"
    assert {d.name for d in onto.DrKumar.madeDiagnosis} == {"DiagnosisFlu", "DiagnosisDiabetesAlice", "DiagnosisDiabetesBob"}
    assert {p.name for p in onto.Metformin.containedInPrescription} == {"PrescriptionDiabetesAlice"}
    assert onto.WardICU.wardOfDepartment.name == "ICUDept"
    assert {t.name for t in onto.PatientAlice.underwentTest} == {"BloodTestAlice001"}
    assert onto.BloodTestAlice001.testForPatient.name == "PatientAlice"
    assert onto.BloodTestAlice001.orderedBy.name == "DrKumar"


def test_the_projection_carries_the_new_inverses_marked_as_inferred():
    from services.graph_projection import build_projection

    projection = build_projection(Dataset.default())
    inferred = {e.rel_type for e in projection.edges if e.inferred}
    assert {"ALLERGYFORPATIENT", "MADEDIAGNOSIS", "CONTAINEDINPRESCRIPTION", "WARDOFDEPARTMENT", "HASSTAFFMEMBER",
            "ORDEREDBY", "TESTFORPATIENT", "ISSUEDPRESCRIPTION"} <= inferred
    asserted = {e.rel_type for e in projection.edges if not e.inferred}
    assert {"HASALLERGY", "DIAGNOSEDBY", "CONTAINSMEDICATION", "WORKSINDEPARTMENT"} <= asserted
    assert not {"ALLERGYFORPATIENT", "MADEDIAGNOSIS"} & asserted, "inverse edges are inferred, never asserted in the data"


def test_the_sample_data_asserts_only_the_forward_direction():
    data = Graph().parse(Dataset.default().data, format="turtle")
    for _, inverse in NEW_PAIRS:
        assert not list(data.triples((None, HC[inverse], None))), f"{inverse} must be inferred, not stored"


# ===========================================================================================================
# 2. Person / Practitioner / Patient
# ===========================================================================================================

def test_roles_are_types_a_person_may_hold_together(schema):
    """Patient and Practitioner are overlapping subclasses of Person; neither contains the other; no role class exists."""
    for role in ("Patient", "Practitioner"):
        assert (HC[role], RDFS.subClassOf, HC.Person) in schema
    assert (HC.Patient, RDFS.subClassOf, HC.Practitioner) not in schema
    assert (HC.Practitioner, RDFS.subClassOf, HC.Patient) not in schema
    for members in schema.subjects(RDF.type, OWL.AllDisjointClasses):
        listed = set()
        for lst in schema.objects(members, OWL.members):
            listed |= set(schema.items(lst))
        assert not ({HC.Patient, HC.Practitioner} & listed), "a role class was declared disjoint from another"
        assert not ({HC.Doctor, HC.Nurse, HC.Patient} & listed)
    assert (HC.PractitionerRole, RDF.type, OWL.Class) not in schema, "no PractitionerRole class: see the modelling decision"


def test_a_person_is_not_an_organization_or_a_location(schema):
    """The disjointness that DOES hold: kinds of thing, as opposed to roles a person plays."""
    for members in schema.subjects(RDF.type, OWL.AllDisjointClasses):
        listed = set()
        for lst in schema.objects(members, OWL.members):
            listed |= set(schema.items(lst))
        if HC.Person in listed:
            assert {HC.Organization, HC.Location, HC.Encounter, HC.Medication} <= listed
            return
    pytest.fail("Person is not in any disjointness axiom")


def dual_role_graph() -> Graph:
    """A real person in the sample data (Dr Kumar) who is also registered as a patient."""
    g = Dataset.default().graph()
    kumar = HC.DrKumar
    g.add((kumar, RDF.type, HC.Patient))
    g.add((kumar, HC.bloodGroup, Literal("O-", datatype=XSD.string)))
    return g


def test_one_individual_can_be_a_doctor_and_a_patient_and_still_validate(validator):
    g = dual_role_graph()
    types = {local(t) for t in g.objects(HC.DrKumar, RDF.type)}
    assert {"Doctor", "Patient"} <= types
    result = validator.validate_graph(g, data_source="dual role")
    assert result.summary.conforms is True and result.summary.violation_count == 0


@needs_java
def test_the_reasoner_accepts_a_doctor_who_is_also_a_patient():
    world, onto = reason(dual_role_graph())
    assert list(world.inconsistent_classes()) == []
    kumar = onto.DrKumar
    assert onto.Doctor in kumar.is_a and onto.Patient in kumar.is_a
    # the person keeps one identity: the encounter they attended as a doctor is still theirs
    assert {e.name for e in kumar.participatesIn} == {"Encounter002", "Encounter004", "Encounter005"}


def test_roles_do_not_force_a_second_identity():
    """Both roles share the IRI, the name and the birth date: nothing is duplicated per role."""
    g = dual_role_graph()
    assert len(list(g.objects(HC.DrKumar, HC.dateOfBirth))) == 1
    assert len(list(g.objects(HC.DrKumar, HC.lastName))) == 1


# ===========================================================================================================
# 3. Temporal ordering of an encounter (SHACL), with the three layers' responsibilities kept distinct
# ===========================================================================================================

def encounter(start, end=None) -> str:
    end_line = f'    hc:encounterEnd "{end}"^^xsd:dateTime ;\n' if end else ""
    return PREFIXES + f"""
hc:EncT a hc:EncounterType .
hc:P a hc:Patient ; hc:hasEncounter hc:E .
hc:E a hc:Encounter ; hc:encounterType hc:EncT ;
{end_line}    hc:encounterStart "{start}"^^xsd:dateTime .
"""


def ordering_problems(validator, start, end=None):
    result = validator.validate_rdf_text(encounter(start, end), rdf_format="turtle", shape_files=["clinical_shapes.ttl"])
    return [v for v in result.violations if v.severity == "Violation" and "encounterStart" in (v.result_path or "")]


@pytest.mark.parametrize("start,end", [
    ("2026-03-01T09:00:00Z", "2026-03-01T10:00:00Z"),            # end after start
    ("2026-03-01T09:00:00Z", "2026-03-01T09:00:00Z"),            # a zero-length encounter is allowed (<=, not <)
    ("2026-03-01T09:00:00Z", None),                              # an open encounter has no end yet
    ("2026-03-01T10:00:00+02:00", "2026-03-01T09:00:00Z"),       # the same instant written in two zones
    ("2026-03-01T10:00:00+02:00", "2026-03-01T09:30:00Z"),       # end is 90 minutes after start once zones are applied
    ("2026-03-01T23:30:00Z", "2026-03-02T00:15:00Z"),            # across midnight
])
def test_valid_encounter_intervals_pass(validator, start, end):
    assert ordering_problems(validator, start, end) == []


@pytest.mark.parametrize("start,end", [
    ("2026-03-01T10:00:00Z", "2026-03-01T09:59:59Z"),            # one second early
    ("2026-03-01T10:00:00Z", "2026-02-28T10:00:00Z"),            # a day early
    ("2026-03-01T10:00:00Z", "2026-03-01T10:30:00+02:00"),       # looks later, but is 08:30Z: before the start
    ("2026-03-02T00:15:00Z", "2026-03-01T23:30:00Z"),            # across midnight, backwards
])
def test_invalid_encounter_intervals_are_rejected_by_shacl(validator, start, end):
    problems = ordering_problems(validator, start, end)
    assert len(problems) == 1 and "not after encounterEnd" in problems[0].message


def test_the_real_sample_data_has_valid_intervals_and_a_mutation_is_caught(validator):
    g = Dataset.default().graph()
    ends = list(g.triples((None, HC.encounterEnd, None)))
    assert len(ends) == 6
    assert validator.validate_graph(g, data_source="valid").summary.conforms is True
    start = next(g.objects(HC.Encounter001, HC.encounterStart))
    g.set((HC.Encounter001, HC.encounterEnd, Literal("2026-03-01T08:00:00+00:00", datatype=XSD.dateTime)))
    assert start.toPython().hour == 9
    result = validator.validate_graph(g, data_source="mutated")
    bad = [v for v in result.violations if v.severity == "Violation" and v.focus_node.endswith("Encounter001")]
    assert len(bad) == 1 and "not after encounterEnd" in bad[0].message


def test_the_same_defect_is_stopped_by_each_layer_for_its_own_input(validator, tmp_path):
    """Layer responsibilities: the CSV data contract protects the SOURCE (row-level message, before any RDF exists);
    SHACL protects the RDF, whatever produced it. Neither relies on the other."""
    import shutil

    from services import sample_data

    case = ROOT / "data" / "invalid_source" / "encounter_ends_before_start"
    shutil.copytree(sample_data.SOURCE_DIR, tmp_path / "src")
    shutil.copy(case / "encounters.csv", tmp_path / "src")
    problems = sample_data.check_dataset(sample_data.load_dataset(tmp_path / "src"), sample_data.load_drug_reference(),
                                         source_dir=tmp_path / "src")
    assert [p.code for p in problems if "end is before start" in p.message] == ["INVALID_DATE"]
    assert ordering_problems(validator, "2026-03-01T10:00:00Z", "2026-03-01T08:00:00Z")      # RDF with no CSV behind it


def test_owl_cannot_state_the_ordering_so_the_schema_does_not_try(schema):
    """OWL has no way to compare two datatype values of the same individual; the rule is deliberately not in the schema."""
    for restriction in schema.subjects(RDF.type, OWL.Restriction):
        assert local(next(schema.objects(restriction, OWL.onProperty))) not in {"encounterStart", "encounterEnd"}


# ===========================================================================================================
# 4. Closed shapes: only where the structure is a fixed value object
# ===========================================================================================================

CLOSED = {"CodeConceptShape", "IdentifierShape"}


def shapes_graph() -> Graph:
    g = Graph()
    for path in glob.glob(str(ROOT / "shapes" / "**" / "*.ttl"), recursive=True):
        g.parse(path, format="turtle")
    return g


def test_exactly_the_value_object_shapes_are_closed():
    closed = {local(s) for s in shapes_graph().subjects(SH.closed, Literal(True))}
    assert closed == CLOSED, "closing a shape is a modelling decision; add it to CLOSED and to the documentation"


def test_entity_shapes_stay_open_for_extension():
    g = shapes_graph()
    for name in ("PatientShape", "DoctorShape", "EncounterShape", "MedicationShape", "DiagnosisShape", "HospitalShape"):
        shape = next(s for s in g.subjects(RDF.type, SH.NodeShape) if local(s) == name)   # StopIteration if the shape vanished
        assert not list(g.objects(shape, SH.closed)), f"{name} must stay open"


def test_a_misspelt_property_on_a_code_concept_is_caught(validator):
    data = PREFIXES + """
hc:C a hc:CodeConcept ; hc:codeSystem "http://loinc.org"^^xsd:anyURI ; hc:codeValue "8480-6"^^xsd:string ;
    hc:codeValu "8480-6"^^xsd:string .
"""
    result = validator.validate_rdf_text(data, rdf_format="turtle", shape_files=["clinical_shapes.ttl"])
    closed = [v for v in result.violations if "ClosedConstraintComponent" in (v.source_constraint or "")]
    assert len(closed) == 1 and closed[0].result_path.endswith("codeValu")


def test_an_extra_property_on_an_identifier_is_caught(validator):
    data = PREFIXES + """
hc:I a hc:Identifier ; hc:identifierSystem "https://x.example/mrn"^^xsd:anyURI ; hc:identifierValue "1"^^xsd:string ;
    hc:identifierType "MRN"^^xsd:string ; hc:firstName "Not an identifier attribute"^^xsd:string .
"""
    result = validator.validate_rdf_text(data, rdf_format="turtle", shape_files=["clinical_shapes.ttl"])
    assert len([v for v in result.violations if "ClosedConstraintComponent" in (v.source_constraint or "")]) == 1


def test_a_well_formed_code_concept_and_identifier_still_pass_including_the_assigner(validator):
    data = PREFIXES + """
hc:H a hc:Hospital ; hc:hospitalName "H"^^xsd:string ; hc:hospitalId "H1"^^xsd:string .
hc:C a hc:CodeConcept ; hc:codeSystem "http://loinc.org"^^xsd:anyURI ; hc:codeValue "8480-6"^^xsd:string ;
    hc:codeDisplay "Systolic blood pressure"^^xsd:string .
hc:I a hc:Identifier ; hc:identifierSystem "https://x.example/mrn"^^xsd:anyURI ; hc:identifierValue "1"^^xsd:string ;
    hc:identifierType "MRN"^^xsd:string ; hc:identifierAssigner hc:H .
"""
    result = validator.validate_rdf_text(data, rdf_format="turtle", shape_files=["clinical_shapes.ttl"])
    assert [v for v in result.violations if v.severity == "Violation"] == []


def test_open_shapes_tolerate_an_extension_property(validator):
    """A patient record with an extra, schema-unknown attribute is not rejected: entity shapes are open on purpose."""
    g = Dataset.default().graph()
    g.add((HC.PatientJohn, HC.localExtensionNote, Literal("added by a site-specific profile")))
    result = validator.validate_graph(g, data_source="extension")
    assert result.summary.conforms is True and result.summary.violation_count == 0


# ===========================================================================================================
# 5. No vacuous assertions anywhere in the suite
# ===========================================================================================================

import sys as _sys

_sys.path.insert(0, str(ROOT / "scripts"))
from ci_checks import weak_assertion  # noqa: E402  (ONE definition, shared with the CI hygiene check)


def scan_suite():
    findings = []
    for path in sorted(glob.glob(str(ROOT / "tests" / "test_*.py"))):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                reason_ = weak_assertion(node.test)
                if reason_:
                    findings.append(f"{Path(path).name}:{node.lineno}: {reason_}: assert {ast.unparse(node.test)[:70]}")
    return findings


def test_the_suite_contains_no_vacuous_assertions():
    assert scan_suite() == []


@pytest.mark.parametrize("source,expected", [
    ("assert x or True", True), ("assert True", True), ("assert len(rows) > 0", True), ("assert len(rows) >= 1", True),
    ("assert count >= 0", True), ("assert value is not None", True),
    ("assert len(rows) == 5", False), ("assert value == 'x'", False), ("assert x or y", False), ("assert count >= 3", False),
])
def test_the_detector_catches_the_patterns_it_is_meant_to_catch(source, expected):
    node = ast.parse(source).body[0]
    assert (weak_assertion(node.test) is not None) is expected


def test_every_test_function_asserts_something():
    """A test with no assertion, raises-block or explicit failure proves only that the code did not crash."""
    silent = []
    for path in sorted(glob.glob(str(ROOT / "tests" / "test_*.py"))):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")):
            body = ast.dump(fn)
            if not any(k in body for k in ("Assert(", "raises", "pytest.fail", "pytest.skip", "'fail'", "assert_", "check")):
                silent.append(f"{Path(path).name}:{fn.lineno} {fn.name}")
    assert silent == []
