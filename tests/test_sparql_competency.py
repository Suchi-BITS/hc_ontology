"""SPARQL tests: every competency question is an executable query with a stated answer.

The queries live in ``sparql/*.rq`` (one per question). The expected answers below are
written by hand from the sample data, not copied from the engine's output, so a change
to the ontology, the data or a query shows up as a failing test.

Level: SPARQL tests (RDF graph only; no reasoner, no Neo4j). Two tests also send the
query through the real ``POST /sparql`` endpoint to prove the validator and executor
accept what the ontology supports.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import rdflib
from rdflib import XSD, Literal, URIRef

ROOT = Path(__file__).resolve().parent.parent
SPARQL_DIR = ROOT / "sparql"
from core.dataset import Dataset  # noqa: E402

OWL_FILE = Dataset.default()  # the questions run against schema + sample data
HC = "http://example.org/healthcare-hospital.owl#"


@pytest.fixture(scope="module")
def graph():
    return OWL_FILE.graph()


def text(term) -> str:
    if isinstance(term, URIRef):
        return str(term).split("#")[-1]
    return str(term.toPython())


def run(graph, name, **bindings):
    query = (SPARQL_DIR / f"{name}.rq").read_text(encoding="utf-8")
    result = graph.query(query, initBindings=bindings) if bindings else graph.query(query)
    return [tuple(text(x) for x in row) for row in result]


def entailed(graph):
    """The graph plus the class/property hierarchy closure (what a reasoner adds for questions like CQ21)."""
    from core.shacl_validator import entail_hierarchy

    return entail_hierarchy(graph)


def copy_of(graph):
    clone = rdflib.Graph()
    for triple in graph:
        clone.add(triple)
    return clone


# name -> (bindings, expected rows in query order)
CASES = {
    "cq01_patients": (
        {}, [("PatientAlice",), ("PatientBob",), ("PatientDavid",), ("PatientEmma",), ("PatientJohn",)],
    ),
    "cq02_patient_encounters": (
        {}, [
            ("PatientAlice", "Encounter004", "Ambulatory"),
            ("PatientBob", "Encounter005", "Ambulatory"),
            ("PatientDavid", "Encounter003", "Emergency"),
            ("PatientDavid", "Encounter006", "Inpatient"),
            ("PatientEmma", "Encounter002", "Ambulatory"),
            ("PatientJohn", "Encounter001", "Ambulatory"),
        ],
    ),
    "cq03_patient_conditions": (
        {}, [
            ("PatientAlice", "Diabetes"), ("PatientBob", "Diabetes"), ("PatientDavid", "Migraine"),
            ("PatientEmma", "Influenza"), ("PatientJohn", "Hypertension"),
        ],
    ),
    "cq04_patients_by_condition_code": (
        {"system": Literal("http://hl7.org/fhir/sid/icd-10", datatype=XSD.anyURI),
         "code": Literal("E11", datatype=XSD.string)},
        [("PatientAlice",), ("PatientBob",)],
    ),
    "cq05_medications_and_categories": (
        {}, [
            ("Amlodipine", "Antihypertensive"), ("Amoxicillin", "Antibiotic"), ("Aspirin", "Analgesic"),
            ("Aspirin", "Antiplatelet"), ("InsulinGlargine", "Antidiabetic"), ("Metformin", "Antidiabetic"),
            ("Paracetamol", "Analgesic"),
        ],
    ),
    "cq06_numeric_observations": (
        {}, [
            ("PatientAlice", "Hemoglobin A1c/Hemoglobin.total in Blood", "7.2", "%"),
            ("PatientJohn", "Systolic blood pressure", "152.0", "mm[Hg]"),
        ],
    ),
    "cq07_encounter_providers": (
        {}, [
            ("Encounter001", "DrSmith"), ("Encounter001", "NurseMary"), ("Encounter002", "DrKumar"),
            ("Encounter003", "DrJohn"), ("Encounter003", "DrWilliams"), ("Encounter004", "DrKumar"),
            ("Encounter005", "DrKumar"), ("Encounter006", "DrJohn"), ("Encounter006", "NurseRita"),
        ],
    ),
    "cq08_doctors_by_specialty": (
        {}, [
            ("DrJohn", "Neurology"), ("DrKumar", "Internal medicine"), ("DrSmith", "Cardiology"),
            ("DrWilliams", "Surgery"),
        ],
    ),
    "cq09_allergies": ({}, [("PatientBob", "Amoxicillin")]),
    "cq10_medication_allergy_conflicts": ({}, []),  # the sample data is conflict-free
    "cq11_patients_on_antidiabetics": ({}, [("PatientAlice",), ("PatientBob",)]),
    "cq12_beds_per_department": (
        {}, [("CardiologyDept", "Bed1"), ("CardiologyDept", "Bed2"), ("ICUDept", "Bed4"), ("NeurologyDept", "Bed3")],
    ),
    "cq13_diagnoses_per_doctor": ({}, [("DrKumar", "3"), ("DrJohn", "1"), ("DrSmith", "1")]),
    "cq14_all_persons": (
        {}, [(n,) for n in (
            "DrJohn", "DrKumar", "DrSmith", "DrWilliams", "NurseMary", "NurseRita",
            "PatientAlice", "PatientBob", "PatientDavid", "PatientEmma", "PatientJohn",
        )],
    ),
    "cq15_unfulfilled_appointments": ({}, [("Appointment002",)]),
    "cq16_encounter_observations": (
        {}, [("Encounter001", "Observation001", "Systolic blood pressure", "152.0", "mm[Hg]")],
    ),
    "cq17_patient_medications": (
        {}, [
            ("PatientAlice", "Metformin", "DrKumar"), ("PatientBob", "InsulinGlargine", "DrKumar"),
            ("PatientEmma", "Amoxicillin", "DrKumar"), ("PatientEmma", "Paracetamol", "DrKumar"),
            ("PatientJohn", "Amlodipine", "DrSmith"), ("PatientJohn", "Aspirin", "DrSmith"),
        ],
    ),
    "cq18_findings_in_diagnosing_encounter": (
        {}, [("PatientJohn", "Hypertension", "Systolic blood pressure", "152.0")],
    ),
    "cq21_patients_with_a_condition": (  # asked of the graph WITH the class hierarchy applied
        {}, [("PatientAlice",), ("PatientBob",), ("PatientDavid",), ("PatientEmma",), ("PatientJohn",)],
    ),
}
ENTAILED = {"cq21_patients_with_a_condition"}
# Questions whose answer is not a table; they have their own tests below.
OTHER_FORMS = {"cq19_ask_allergy_conflict", "cq20_construct_patient_summary"}


def test_every_query_file_has_an_expected_answer_and_vice_versa():
    on_disk = {p.stem for p in SPARQL_DIR.glob("*.rq")}
    assert on_disk == set(CASES) | OTHER_FORMS, sorted(on_disk ^ (set(CASES) | OTHER_FORMS))


@pytest.mark.parametrize("name", sorted(CASES))
def test_competency_question_returns_the_expected_answer(graph, name):
    bindings, expected = CASES[name]
    source = entailed(graph) if name in ENTAILED else graph
    assert run(source, name, **bindings) == expected


def test_every_query_documents_its_question():
    for path in SPARQL_DIR.glob("*.rq"):
        first = path.read_text(encoding="utf-8").splitlines()[0]
        assert first.startswith("# CQ") and first.endswith(("?", ")", ".")), path.name


def test_queries_only_use_terms_that_exist_in_the_ontology(graph):
    """A query cannot cite a class or property the ontology does not define."""
    import re

    from rdflib import OWL, RDF, RDFS

    defined = {
        str(s).split("#")[-1]
        for t in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.NamedIndividual)
        for s in graph.subjects(RDF.type, t)
    }
    for path in SPARQL_DIR.glob("*.rq"):
        for term in re.findall(r"\bhc:([A-Za-z0-9_]+)", path.read_text(encoding="utf-8")):
            assert term in defined, f"{path.name} uses hc:{term}, which the ontology does not define"


# ---- the queries are discriminating: they change when the data changes ----------------

def test_conflict_query_finds_a_real_conflict(graph):
    """CQ10 returns nothing on clean data; it must return the offending prescription on bad data."""
    mutated = rdflib.Graph()
    for triple in graph:
        mutated.add(triple)
    hc = rdflib.Namespace(HC)
    mutated.add((hc.PrescriptionDiabetesBob, hc.containsMedication, hc.Amoxicillin))  # Bob is allergic
    assert run(mutated, "cq10_medication_allergy_conflicts") == [
        ("PrescriptionDiabetesBob", "PatientBob", "Amoxicillin")
    ]


def test_code_query_is_driven_by_its_parameters(graph):
    icd = Literal("http://hl7.org/fhir/sid/icd-10", datatype=XSD.anyURI)
    assert run(graph, "cq04_patients_by_condition_code", system=icd, code=Literal("I10", datatype=XSD.string)) == [
        ("PatientJohn",)
    ]
    assert run(graph, "cq04_patients_by_condition_code", system=icd, code=Literal("Z99", datatype=XSD.string)) == []
    snomed = Literal("http://snomed.info/sct", datatype=XSD.anyURI)
    assert run(graph, "cq04_patients_by_condition_code", system=snomed, code=Literal("44054006", datatype=XSD.string)) == [
        ("PatientAlice",), ("PatientBob",)
    ]


def test_subclass_path_finds_persons_that_a_plain_type_match_misses(graph):
    plain = graph.query("PREFIX hc: <http://example.org/healthcare-hospital.owl#> SELECT ?p WHERE { ?p a hc:Person }")
    assert len(list(plain)) == 0  # nobody is asserted to be a bare Person
    assert len(run(graph, "cq14_all_persons")) == 11  # the property path follows rdfs:subClassOf


def test_removed_modeling_would_break_the_antidiabetic_query(graph):
    """CQ11 depends on category-as-data; typing Metformin as a class would not satisfy it."""
    mutated = rdflib.Graph()
    for triple in graph:
        mutated.add(triple)
    hc = rdflib.Namespace(HC)
    mutated.remove((hc.Metformin, hc.medicationCategory, hc.MedCategoryAntidiabetic))
    assert run(mutated, "cq11_patients_on_antidiabetics") == [("PatientBob",)]


# ---- through the real API -------------------------------------------------------------

def _api_rows(client, name):
    query = (SPARQL_DIR / f"{name}.rq").read_text(encoding="utf-8")
    response = client.post("/sparql", json={"query": query})
    assert response.status_code == 200, response.text
    return response.json()["results"]


def test_api_executes_competency_questions(client):
    assert _api_rows(client, "cq01_patients") == [[HC + n] for n in
                                                  ("PatientAlice", "PatientBob", "PatientDavid", "PatientEmma", "PatientJohn")]
    kumar = next(row for row in _api_rows(client, "cq13_diagnoses_per_doctor") if row[0] == HC + "DrKumar")
    assert kumar[1] == "3"


def test_api_accepts_a_valid_property_path_query(client):
    assert len(_api_rows(client, "cq14_all_persons")) == 11


# ---- the newer questions: each one is shown to depend on the thing it claims to ask --------------------

def test_encounter_observations_answer_follows_the_link_not_the_patient(graph):
    """Alice has an HbA1c result, but it is not linked to her encounter; CQ16 must not invent the link."""
    assert not any("Alice" in row[0] for row in run(graph, "cq16_encounter_observations"))
    hc = rdflib.Namespace(HC)
    linked = copy_of(graph)
    linked.add((hc.Encounter004, hc.includesObservation, hc.ResultAlice001))
    assert ("Encounter004", "ResultAlice001", "Hemoglobin A1c/Hemoglobin.total in Blood", "7.2", "%") in run(
        linked, "cq16_encounter_observations")


def test_patient_medications_are_driven_by_prescriptions(graph):
    hc = rdflib.Namespace(HC)
    changed = copy_of(graph)
    changed.remove((hc.PrescriptionDiabetesAlice, hc.containsMedication, hc.Metformin))
    assert not [r for r in run(changed, "cq17_patient_medications") if r[0] == "PatientAlice"]
    assert [r for r in run(graph, "cq17_patient_medications") if r[0] == "PatientAlice"]


def test_findings_query_requires_the_shared_encounter(graph):
    """Unlinking the observation from John's encounter removes the answer: the join is the semantics."""
    hc = rdflib.Namespace(HC)
    changed = copy_of(graph)
    changed.remove((hc.Encounter001, hc.includesObservation, hc.Observation001))
    assert run(changed, "cq18_findings_in_diagnosing_encounter") == []


def test_ask_query_flips_when_a_conflict_exists(graph):
    query = (SPARQL_DIR / "cq19_ask_allergy_conflict.rq").read_text(encoding="utf-8")
    assert graph.query(query).askAnswer is False
    hc = rdflib.Namespace(HC)
    unsafe = copy_of(graph)
    unsafe.add((hc.PrescriptionDiabetesBob, hc.containsMedication, hc.Amoxicillin))
    assert unsafe.query(query).askAnswer is True


def test_construct_returns_a_bounded_patient_subgraph(graph):
    query = (SPARQL_DIR / "cq20_construct_patient_summary.rq").read_text(encoding="utf-8")
    hc = rdflib.Namespace(HC)
    out = graph.query(query, initBindings={"patient": hc.PatientJohn}).graph
    subjects = {s for s, _p, _o in out}
    assert hc.PatientJohn in subjects and hc.DiagnosisHypertension in subjects
    assert {hc.Prescription001, hc.PrescriptionHypertensionJohn} <= subjects
    assert not subjects & {hc.PatientAlice, hc.PatientBob, hc.DiagnosisFlu}  # nobody else leaks in
    assert any(p == hc.diagnosisName and str(o) == "Hypertension" for _s, p, o in out)


def test_condition_query_needs_the_class_hierarchy(graph):
    assert run(graph, "cq21_patients_with_a_condition") == []  # asserted graph: nobody is typed as a Condition
    assert len(run(entailed(graph), "cq21_patients_with_a_condition")) == 5


# ---- the catalog (traceability) ---------------------------------------------------------------

import ast
import json
import re

from rdflib import RDFS

CATALOG = json.loads((SPARQL_DIR / "catalog.json").read_text(encoding="utf-8"))["questions"]


HCNS = rdflib.Namespace(HC)


def _ontology_terms(graph):
    from rdflib import OWL, RDF

    def names(*types):
        return {str(s).split("#")[-1] for t in types for s in graph.subjects(RDF.type, t)}

    return names(OWL.Class, OWL.NamedIndividual), names(OWL.ObjectProperty, OWL.DatatypeProperty)


def test_catalog_has_one_entry_per_query_file():
    assert [q["id"] for q in CATALOG] == sorted(p.stem for p in SPARQL_DIR.glob("*.rq"))


def test_catalog_entries_are_complete():
    for q in CATALOG:
        for field in ("domain_question", "purpose", "expected", "explanation"):
            assert len(q[field]) > 15, (q["id"], field)
        assert q["tests"], q["id"]
        assert q["form"] in ("SELECT", "ASK", "CONSTRUCT")


def test_catalog_form_matches_the_query():
    for q in CATALOG:
        body = re.sub(r"(?m)^\s*#.*$|PREFIX[^\n]*", "", (SPARQL_DIR / f"{q['id']}.rq").read_text(encoding="utf-8"))
        assert body.strip().split()[0].upper() == q["form"], q["id"]


def test_catalog_lists_the_terms_the_query_uses(graph):
    classes, properties = _ontology_terms(graph)
    for q in CATALOG:
        used = set(re.findall(r"\bhc:([A-Za-z0-9_]+)", (SPARQL_DIR / f"{q['id']}.rq").read_text(encoding="utf-8")))
        assert used <= set(q["concepts"]) | set(q["properties"]), q["id"]
        # A listed concept the query does not name must be justified by the model: it is the domain or
        # range of a property the query does use (so the query traverses it without saying so).
        implied = {str(o).split("#")[-1] for name in used & properties
                   for pred in (RDFS.domain, RDFS.range) for o in graph.objects(HCNS[name], pred)}
        assert set(q["concepts"]) - used <= implied, (q["id"], sorted(set(q["concepts"]) - used - implied))
        assert set(q["properties"]) <= used, (q["id"], "a listed property the query never uses")
        assert set(q["concepts"]) <= classes, (q["id"], "concepts must be classes or individuals")
        assert set(q["properties"]) <= properties, (q["id"], "properties must be properties")


def test_catalog_tests_exist():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for q in CATALOG:
        for name in q["tests"]:
            assert name in defined, f"{q['id']} cites test {name}, which does not exist"


def test_catalog_flags_entailment_exactly_where_it_is_needed():
    assert {q["id"] for q in CATALOG if q.get("requires_entailment")} == ENTAILED


def test_generated_document_is_up_to_date():
    import subprocess
    import sys

    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_cq_doc.py"), "--check"],
                          capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr
