"""Documentation that states a fact about the ontology must state the CURRENT fact.

The stdlib half (stale suite sizes, retired names, dead links and paths, competency-question and fixture counts) is in
scripts/ci_checks.py and runs in CI's hygiene job. This half needs the ontology itself: it reads the schema and compares
every "N classes / object properties / datatype properties / inverse pairs" claim with what the schema really contains.
Add a new kind of claim to CLAIMS and it is enforced from then on.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from rdflib import OWL, RDF, Graph

from core.dataset import HC, Dataset

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ci_checks as cc  # noqa: E402


@pytest.fixture(scope="module")
def facts():
    g = Graph().parse(Dataset.default().schema, format="turtle")
    pairs = {frozenset((str(a), str(b))) for a, b in g.subject_objects(OWL.inverseOf)}
    return {
        # The ontology's own named classes: not the SKOS terms it references, nor the anonymous class expressions of defined classes.
        "classes": len({c for c in g.subjects(RDF.type, OWL.Class) if str(c).startswith(HC)}),
        "object properties": len(set(g.subjects(RDF.type, OWL.ObjectProperty))),
        "datatype properties": len(set(g.subjects(RDF.type, OWL.DatatypeProperty))),
        "inverse pairs": len(pairs),
    }


# (regex capturing the number, the fact it must equal). The schema's own class count is quoted next to its property counts.
CLAIMS = [
    (re.compile(r"\b(\d+) classes, \d+ object properties"), "classes"),
    (re.compile(r"\b(\d+) object properties"), "object properties"),
    (re.compile(r"\b(\d+) (?:datatype|data) properties"), "datatype properties"),
    (re.compile(r"\b(\d+) inverse pairs"), "inverse pairs"),
]


def current_docs():
    return cc.current_docs(cc.committable(ROOT))


def test_there_are_current_documents_to_check():
    docs = current_docs()
    assert "readme.md" in docs and "docs/ontology-engineering.md" in docs and len(docs) >= 15


def test_every_ontology_count_stated_in_the_documentation_is_true(facts):
    wrong = []
    checked = 0
    for rel in current_docs():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            for pattern, fact in CLAIMS:
                for match in pattern.finditer(line):
                    checked += 1
                    if int(match.group(1)) != facts[fact]:
                        wrong.append(f"{rel}:{number} says {match.group(1)} {fact}; the schema has {facts[fact]}")
    assert checked >= 6, "the claims are no longer being found: has the wording changed?"
    assert wrong == []


def test_the_property_split_in_the_chapter_table_is_true(facts):
    text = (ROOT / "docs" / "book-chapter-mapping.md").read_text(encoding="utf-8")
    match = re.search(r"\b(\d+) classes, (\d+) \+ (\d+) properties", text)
    assert match, "the chapter table no longer states the model size"
    assert tuple(map(int, match.groups())) == (facts["classes"], facts["object properties"], facts["datatype properties"])


def test_a_stale_count_would_be_caught(facts):
    """The detector must fail on a wrong number, not just pass on right ones."""
    line = f"{facts['classes']} classes, {facts['object properties'] + 1} object properties"
    wrong = [int(m.group(1)) for pattern, fact in CLAIMS for m in pattern.finditer(line) if int(m.group(1)) != facts[fact]]
    assert wrong == [facts["object properties"] + 1]


def test_documented_statistics_that_are_derived_from_files_match_the_files():
    """Competency questions and invalid fixtures are counted from the directories by the hygiene check."""
    assert cc.count_claim_findings(ROOT, current_docs()) == []
