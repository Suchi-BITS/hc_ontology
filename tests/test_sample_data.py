"""Sample data -> contract -> RDF -> SHACL: the data pipeline's regression tests.

Valid data is `data/source/*.csv`. Each directory under `data/invalid_source/` holds ONE broken table
and an EXPECT file naming the problem code the contract must report. Nothing here needs Neo4j.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import RDF, Graph, Namespace

from core.dataset import Dataset
from services import sample_data
from services import reference_vocab as V

ROOT = Path(__file__).resolve().parent.parent
INVALID = ROOT / "data" / "invalid_source"
CASES = sorted(p for p in INVALID.iterdir() if p.is_dir())
HC = Namespace("http://example.org/healthcare-hospital.owl#")


def overlay(case: Path, target: Path) -> Path:
    """Copy the valid source to `target`, then replace the table(s) the case provides."""
    shutil.copytree(sample_data.SOURCE_DIR, target)
    for csv_file in case.glob("*.csv"):
        shutil.copy(csv_file, target / csv_file.name)
    for marker in case.glob("*.csv.absent"):  # a case that deletes a table
        (target / marker.name.removesuffix(".absent")).unlink()
    return target


def problems_for(source_dir: Path) -> list[sample_data.Problem]:
    return sample_data.check_dataset(sample_data.load_dataset(source_dir), sample_data.load_drug_reference(),
                                     source_dir=source_dir)


def test_valid_source_satisfies_the_contract():
    assert problems_for(sample_data.SOURCE_DIR) == []


def test_every_source_table_is_in_the_schema_and_vice_versa():
    on_disk = {p.stem for p in sample_data.SOURCE_DIR.glob("*.csv")}
    assert on_disk == set(sample_data.SCHEMA)


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_invalid_fixture_is_rejected_with_its_named_problem(case, tmp_path):
    expected = (case / "EXPECT").read_text(encoding="utf-8").splitlines()[0]
    found = problems_for(overlay(case, tmp_path / "src"))
    assert expected in {p.code for p in found}, (
        f"{case.name}: expected {expected}, contract reported {[str(p) for p in found] or 'nothing'}")


def test_every_problem_code_is_demonstrated_by_a_fixture():
    """A check nobody has ever seen fail is a check nobody knows works."""
    declared = {(c / "EXPECT").read_text(encoding="utf-8").splitlines()[0] for c in CASES}
    emitted = {m for m in _codes_in_source()}
    assert emitted - declared == set(), f"checks without an invalid fixture: {sorted(emitted - declared)}"


def _codes_in_source() -> set[str]:
    import re

    text = Path(sample_data.__file__).read_text(encoding="utf-8")
    return set(re.findall(r'add\("([A-Z_]+)"', text))


def test_invalid_fixtures_do_not_all_fail_for_the_same_reason():
    assert len({(c / "EXPECT").read_text(encoding="utf-8").splitlines()[0] for c in CASES}) >= 9


def test_contract_reports_every_problem_not_just_the_first(tmp_path):
    src = overlay(INVALID / "metformin_analgesic", tmp_path / "src")
    (src / "patients.csv").write_text((INVALID / "patient_missing_dob" / "patients.csv").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(sample_data.DataContractError) as err:
        sample_data.require_valid(sample_data.load_dataset(src), sample_data.load_drug_reference())
    assert {"INVALID_CLASSIFICATION", "MISSING_REQUIRED"} <= {p.code for p in err.value.problems}


# ---- classification: the audit's errors and the whole class of them ---------------------------------

def test_reference_covers_every_medication_and_agrees_with_the_data():
    reference = sample_data.load_drug_reference()
    for med in sample_data.load_dataset()["medications"]:
        assert reference[med["name"].lower()] == set(sample_data.split(med["categories"])), med["id"]


def test_reference_uses_only_known_categories():
    for cats in sample_data.load_drug_reference().values():
        assert cats <= set(V.MEDICATION_CATEGORIES)


def test_committed_ontology_classifies_medications_like_the_reference():
    """Checked on the generated RDF itself, so a bug in the CSV->RDF mapping cannot hide."""
    graph = Dataset.default().graph()
    reference = sample_data.load_drug_reference()
    seen = 0
    for med in graph.subjects(RDF.type, HC.Medication):
        name = str(graph.value(med, HC.medicationName))
        cats = {str(c).split("MedCategory")[-1] for c in graph.objects(med, HC.medicationCategory)}
        assert cats == reference[name.lower()], name
        seen += 1
    assert seen == len(reference)


def test_no_medication_is_asserted_as_a_category_subclass():
    """The audit's root cause: categories were hand-assigned classes. They are SKOS concepts now."""
    graph = Dataset.default().graph()
    for med in graph.subjects(RDF.type, HC.Medication):
        types = {t for t in graph.objects(med, RDF.type)}
        assert not any(str(t).endswith(("Analgesic", "Antidiabetic")) for t in types), med


# ---- the pipeline refuses bad data before writing anything ---------------------------------------------

def _generate(source: Path, out: Path):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_sample_data.py"), "--output", str(out),
                           "--source-dir", str(source)], capture_output=True, text=True, cwd=ROOT)


@pytest.mark.parametrize("case", ["metformin_analgesic", "patient_missing_dob", "encounter_unknown_patient"])
def test_generator_stops_on_a_contract_violation_and_writes_nothing(case, tmp_path):
    out = tmp_path / "out.owl"
    done = _generate(overlay(INVALID / case, tmp_path / "src"), out)
    assert done.returncode == 2, done.stderr[-400:]
    assert (INVALID / case / "EXPECT").read_text(encoding="utf-8").splitlines()[0] in done.stderr
    assert not out.exists()


def test_a_failed_run_leaves_an_existing_ontology_untouched(tmp_path):
    out = tmp_path / "out.owl"
    out.write_text("previous good content", encoding="utf-8")
    _generate(overlay(INVALID / "metformin_analgesic", tmp_path / "src"), out)
    assert out.read_text(encoding="utf-8") == "previous good content"
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".owl"] == ["out.owl"]  # no stray temp files


def test_shacl_gate_catches_what_the_contract_missed(tmp_path):
    """Defence in depth: with the contract bypassed, a Diagnosis without a code still cannot be written (DiagnosisShape)."""
    src = overlay(INVALID / "diagnosis_without_code", tmp_path / "src")
    out = tmp_path / "out.owl"
    script = (
        "import sys; sys.path.insert(0, 'scripts'); import generate_sample_data as g; "
        "from services import sample_data as s; s.require_valid = lambda *a, **k: None; "
        f"g.generate({str(out)!r}, {str(src)!r})"
    )
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode != 0
    assert "fails SHACL" in done.stderr
    assert not out.exists()


def test_generator_output_is_deterministic_for_a_valid_source(tmp_path):
    a, b = tmp_path / "a.ttl", tmp_path / "b.ttl"
    assert _generate(sample_data.SOURCE_DIR, a).returncode == 0
    assert _generate(sample_data.SOURCE_DIR, b).returncode == 0
    assert a.read_bytes() == b.read_bytes()  # byte-for-byte
    from rdflib.compare import isomorphic

    assert isomorphic(Graph().parse(a, format="turtle"), Graph().parse(b, format="turtle"))


def test_seed_validates_the_contract_before_touching_anything(monkeypatch):
    from services import seed_demo_data

    def boom(*a, **k):
        raise sample_data.DataContractError([sample_data.Problem("DUPLICATE_ID", "patients", 2, "X", "dup")])

    monkeypatch.setattr(sample_data, "require_valid", boom)
    with pytest.raises(sample_data.DataContractError):
        seed_demo_data.verify_source_data()


def test_seed_has_no_switch_to_skip_validation():
    import inspect

    from services import seed_demo_data

    assert "validate" not in inspect.signature(seed_demo_data.seed_demo_ontology_and_neo4j).parameters


# ---- PatientJohn, at the layer where it belongs ---------------------------------------------------------

def test_patient_john_is_complete_in_the_source_and_conforms_in_rdf(validator):
    john = next(r for r in sample_data.load_dataset()["patients"] if r["id"] == "PatientJohn")
    assert john["date_of_birth"] and john["gender"] and john["blood_group"] and john["mrn"]
    result = validator.validate_ontology()
    assert not [v for v in result.violations if v.focus_node.endswith("PatientJohn") and v.severity != "Info"]


def test_patient_shape_was_not_weakened_for_the_sample_data():
    """The shape still demands what it demanded: the data was fixed, not the rule."""
    text = (ROOT / "shapes" / "patient_shapes.ttl").read_text(encoding="utf-8")
    assert "dateOfBirth" in text and "sh:minCount 1" in text
