"""The book material is tested like code.

* every exercise in docs/book-chapter-mapping.md that can run offline is run here, and its stated
  outcome is asserted;
* every repository path and test name the new documents mention must exist;
* the structure the documents promise (fourteen chapters, nine diagrams, eight anti-patterns, eight
  troubleshooting areas) is present.

A document that points at a renamed file, or promises an outcome that is no longer true, fails here.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from core.dataset import Dataset
from rdflib import XSD, Graph, Literal, Namespace
from rdflib import RDFS

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
HC = Namespace("http://example.org/healthcare-hospital.owl#")
NEW_DOCS = ["README.md", "reader-journey.md", "book-chapter-mapping.md", "architecture-diagrams.md",
            "anti-patterns.md", "troubleshooting.md", "core-vs-ai-architecture.md"]


@pytest.fixture(scope="module")
def graph():
    return Dataset.default().graph()


def read(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


# ---- the exercises ---------------------------------------------------------------------------------

def test_e01_the_model_has_no_indicates_relation():
    for path in Dataset.default().paths:
        assert "indicates" not in path.read_text(encoding="utf-8")


def test_e02_e10_a_broken_table_stops_the_generator_and_writes_nothing(tmp_path):
    shutil.copytree(ROOT / "data" / "source", tmp_path / "bad_source")
    shutil.copy(ROOT / "data" / "invalid_source" / "metformin_analgesic" / "medications.csv", tmp_path / "bad_source")
    out = tmp_path / "bad.owl"
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_sample_data.py"), "--source-dir",
                           str(tmp_path / "bad_source"), "--output", str(out)], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 2 and not out.exists()
    assert "[INVALID_CLASSIFICATION] medications.csv:4 Metformin: categories ['Analgesic'] disagree with the reference ['Antidiabetic']" in done.stderr


def test_e03_superclasses(graph):
    supers = lambda cls: sorted(str(o).split("#")[-1] for o in graph.transitive_objects(cls, RDFS.subClassOf) if o != cls)
    assert supers(HC.Diagnosis) == ["Condition", "Thing"]
    assert supers(HC.Doctor) == ["Person", "Practitioner", "Thing"]


def test_e04_adding_a_specialty_adds_one_vocabulary_individual_to_the_schema(tmp_path):
    code = (
        "import sys; sys.path.insert(0, 'scripts'); sys.path.insert(0, '.')\n"
        "from services import reference_vocab as v\n"
        "v.SPECIALTIES['Dermatology'] = 'Dermatology'\n"
        "import generate_hc_ontology as g\n"
        f"g.generate({str(tmp_path / 'derm.ttl')!r}, validate_output=False)\n"
        "print(len(list(g.onto.individuals())))\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stderr[-500:]
    assert done.stdout.strip().splitlines()[-1] == "31"  # 30 vocabulary individuals + Dermatology


def test_e05_triple_counts(graph):
    from rdflib import Graph as G

    schema, data = G().parse(Dataset.default().schema, format="turtle"), G().parse(Dataset.default().data, format="turtle")
    assert (len(schema), len(data), len(graph)) == (1422, 593, 2015)  # the combined graph adds the 5-triple data header


def test_e07_shacl_violation_and_a_conforming_fixture(validator):
    bad = validator.validate_data_file(ROOT / "data" / "sample_instances" / "invalid_patient_missing_dob.ttl")
    assert bad.summary.conforms is False
    assert [v.message for v in bad.violations if v.severity == "Violation"] == ["Patient must have a dateOfBirth."]
    good = validator.validate_data_file(ROOT / "data" / "sample_instances" / "valid_encounter.ttl")
    assert good.summary.conforms is True


def test_e08_cq04_with_a_snomed_code(graph):
    query = (ROOT / "sparql" / "cq04_patients_by_condition_code.rq").read_text(encoding="utf-8")
    snomed = Literal("http://snomed.info/sct", datatype=XSD.anyURI)
    rows = graph.query(query, initBindings={"system": snomed, "code": Literal("44054006", datatype=XSD.string)})
    assert sorted(str(r[0]).split("#")[-1] for r in rows) == ["PatientAlice", "PatientBob"]
    none = graph.query(query, initBindings={"system": snomed, "code": Literal("Z99", datatype=XSD.string)})
    assert list(none) == []


def test_e09_projection_plan(graph):
    from services.graph_projection import build_projection

    info = build_projection(graph).summary()
    assert (info["nodes"], info["classes"], info["relationships"]) == (124, 58, 476)


def test_e12_a_corrupted_snomed_code_is_rejected(tmp_path):
    from services import sample_data

    case = ROOT / "data" / "invalid_source" / "snomed_bad_check_digit"
    shutil.copytree(ROOT / "data" / "source", tmp_path / "s")
    shutil.copy(case / "codes.csv", tmp_path / "s")
    problems = sample_data.check_dataset(sample_data.load_dataset(tmp_path / "s"), sample_data.load_drug_reference(),
                                         source_dir=tmp_path / "s")
    assert any(p.code == "INVALID_CODE" and "Verhoeff" in p.message for p in problems)


def test_e13_lexical_scores():
    from enterprise.lexical_memory import extract_tokens, overlap_score

    tokens = extract_tokens("which patients take metformin for diabetes")
    scores = {n: overlap_score(tokens, n) for n in ("Metformin", "Amlodipine", "Diagnosis")}
    assert scores["Metformin"] > 0 and scores["Amlodipine"] == 0 and scores["Diagnosis"] == 0


def test_e14_abstention_decisions():
    from enterprise.abstention import decide_abstention

    grounded = {"query_type": "sparql", "validated_query": "SELECT ?p WHERE { ?p a hc:Patient }",
                "results": [{"p": "PatientJohn"}] * 6, "validation_ok": True,
                "retrieved_concepts": [{"name": "Patient", "rerank_score": 0.9}]}
    assert decide_abstention(grounded)["refusal_reason"] is None
    assert decide_abstention(dict(grounded, results=[]))["refusal_reason"] == "missing_provenance"
    assert decide_abstention(dict(grounded, human_decision="rejected"))["refusal_reason"] == "human_rejected"


def test_every_exercise_in_the_mapping_is_listed_in_the_table_and_described():
    text = read("book-chapter-mapping.md")
    for n in range(1, 15):
        tag = f"E{n:02d}"
        assert f"**{tag}**" in text or (n == 12 and "**E12**" in text), f"{tag} missing from the table"
        assert f"### {tag}" in text, f"{tag} has no description"


# ---- structure the documents promise -------------------------------------------------------------------

CHAPTERS = ["01 Domain", "02 Vocabulary", "03 Taxonomy", "04 Ontology", "05 RDF", "06 OWL", "07 SHACL", "08 SPARQL",
            "09 Knowledge graph", "10 Validation", "11 API", "12 Interoperability", "13 RAG", "14 Agentic AI"]


def test_both_chapter_documents_cover_all_fourteen_chapters():
    mapping, journey = read("book-chapter-mapping.md"), read("reader-journey.md")
    for chapter in CHAPTERS:
        assert f"| {chapter} |" in mapping, chapter
        assert f"## {chapter}" in journey, chapter


def test_chapter_mapping_has_the_required_columns():
    header = next(l for l in read("book-chapter-mapping.md").splitlines() if l.startswith("| Chapter"))
    assert [c.strip() for c in header.strip("|").split("|")] == [
        "Chapter", "Concept", "Repository Location", "Example", "Exercise", "Expected Outcome"]


def test_every_journey_chapter_answers_why_what_how_tradeoffs_mistakes():
    sections = re.split(r"(?m)^## (?=\d\d )", read("reader-journey.md"))[1:]
    assert len(sections) == 14
    for section in sections:
        for label in ("**WHY.**", "**WHAT.**", "**HOW.**", "**TRADE-OFFS.**", "**COMMON MISTAKES.**"):
            assert label in section, (section.splitlines()[0], label)


def test_nine_diagrams():
    titles = re.findall(r"(?m)^## (\d)\. (.+)$", read("architecture-diagrams.md"))
    assert [t[1] for t in titles] == ["Overall architecture", "Ontology lifecycle", "RDF pipeline", "SHACL validation",
                                      "Competency-question flow", "RDF to Neo4j projection",
                                      "Healthcare interoperability", "RAG architecture (optional layer)",
                                      "Agent architecture (optional layer)"]
    assert read("architecture-diagrams.md").count("```text") == 9


def test_eight_anti_patterns_each_with_the_same_parts():
    text = read("anti-patterns.md")
    entries = re.split(r"(?m)^## (?=\d\. )", text)[1:]
    assert len(entries) == 8
    for entry in entries:
        for label in ("**The mistake.**", "**Why tempting.**", "**What goes wrong.**", "**What this project does", "**Evidence.**", "**Trade-offs.**"):
            assert label in entry, (entry.splitlines()[0], label)


def test_troubleshooting_covers_the_eight_areas():
    headings = re.findall(r"(?m)^## \d\. (.+)$", read("troubleshooting.md"))
    assert headings == ["Dependency setup", "RDF parsing", "SHACL validation", "SPARQL", "Neo4j", "Docker", "API",
                        "Environment configuration"]


def test_docs_index_lists_every_document():
    index = read("README.md")
    for path in DOCS.glob("*.md"):
        if path.name != "README.md":
            assert path.name in index, f"docs/README.md does not list {path.name}"


# ---- nothing points at something that is not there ---------------------------------------------------------

def _links(text: str):
    return re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text)


@pytest.mark.parametrize("name", sorted(p.name for p in DOCS.glob("*.md")))
def test_markdown_links_resolve(name):
    for target in _links(read(name)):
        if re.match(r"^[a-z]+:", target):
            continue
        assert (DOCS / target).resolve().exists(), f"docs/{name} links to {target}, which does not exist"


def test_the_readme_links_resolve():
    for target in _links((ROOT / "readme.md").read_text(encoding="utf-8")):
        if re.match(r"^[a-z]+:", target):
            continue
        assert (ROOT / target).exists(), f"readme.md links to {target}"


TOP = {p.name for p in ROOT.iterdir() if not p.name.startswith(".")}
PATHLIKE = re.compile(r"^[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-*]+)*/?$")


@pytest.mark.parametrize("name", NEW_DOCS)
def test_repository_paths_named_in_backticks_exist(name):
    for token in re.findall(r"`([^`\n]+)`", read(name)):
        token = token.strip()
        if "/" not in token or not PATHLIKE.match(token) or token.split("/")[0] not in TOP:
            continue
        if "*" in token:
            assert list(ROOT.glob(token)), f"{name}: glob {token} matches nothing"
        else:
            assert (ROOT / token).exists(), f"{name}: {token} does not exist"


def _defined_tests() -> set[str]:
    found = set()
    for path in (ROOT / "tests").glob("*.py"):
        found |= {n.name for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(n, ast.FunctionDef)}
    return found


@pytest.mark.parametrize("name", NEW_DOCS)
def test_test_names_mentioned_in_the_documents_exist(name):
    defined = _defined_tests()
    for token in set(re.findall(r"`(test_[a-z0-9_]+)`", read(name))):
        assert token in defined, f"{name} cites {token}, which does not exist"
