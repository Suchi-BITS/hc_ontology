"""Generate docs/competency-questions.md from sparql/catalog.json and sparql/*.rq.

    python scripts/build_cq_doc.py           # write the document
    python scripts/build_cq_doc.py --check   # exit 1 if the committed document is stale

The prose is here; every table row and query in the document comes from the catalog and the .rq files,
so the document cannot disagree with what the tests execute.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "sparql" / "catalog.json"
OUT = ROOT / "docs" / "competency-questions.md"
TEST_FILE = "tests/test_sparql_competency.py"

INTRO = """# Competency questions: the questions the ontology must answer

*Ontology engineering should start with questions the system must answer.*

Most ontology projects begin with classes: Patient, Encounter, Medication. That feels like progress, but a class list cannot be wrong, because nothing asks it anything. A **competency question** is a question the finished system must be able to answer. It makes the model falsifiable: if a question cannot be answered from the data, the model, the data or the question is wrong, and you find out in a test instead of in front of a user.

This project follows one chain for every question:

```text
BUSINESS / DOMAIN QUESTION     "Which medication/allergy combinations require attention?"
        |
COMPETENCY QUESTION            the same question, made precise enough to be answered from the model
        |
ONTOLOGY MODEL                 the classes and properties that must exist (shapes/ and the generator)
        |
RDF DATA                       data/source/*.csv -> data/sample_data.ttl (schema: ontology/healthcare_schema.ttl)
        |
SPARQL QUERY                   sparql/cqNN_*.rq
        |
EXPECTED RESULT                written by hand from the sample data, before running the query
        |
TEST                           tests/test_sparql_competency.py
```

Two rules keep the chain honest. **Expected results are written by hand**, not pasted from the engine's output, otherwise the test only proves the query agrees with itself. And **a question that returns nothing must be shown capable of returning something**: CQ10 and CQ19 return nothing on clean data, so a test inserts a real conflict and watches them find it.

Only questions the ontology supports are asked. Where a natural question is *not* supported (section "What the questions taught us") the project says so instead of faking an answer.
"""

OUTRO = """## What the questions taught us

Writing the questions first exposed decisions that a class diagram hides.

- **"Which observations indicate a condition?" cannot be answered, and should not be.** The ontology has no `indicates` relation, and adding one would assert clinical causation the data does not carry. CQ18 asks the supportable question (what was measured in the encounter where the condition was diagnosed) and the catalog says plainly that this is co-occurrence.
- **Link, don't assume.** Alice's HbA1c result belongs to her but is not linked to her encounter, so CQ16 correctly does not return it. A test links it and shows the answer change. If you want it in the answer, the fix is a data link, not a cleverer query.
- **Diagnosis versus Condition (CQ21).** The data says `Diagnosis`; the question says `Condition`. On the asserted graph the answer is empty. Applying the class hierarchy (the subclass closure here; a full reasoner gives the same answer) returns all five patients. This is the smallest honest demonstration of why RDF needs reasoning.
- **Empty answers need proof (CQ10, CQ19).** Absence of a conflict means something only if the query can find a conflict. Mutation tests supply one.
- **Open world.** CQ15 ("appointments with no encounter") means *no encounter is recorded*, not *none exists*.

## How to add a competency question

1. Write the domain question and the purpose in plain language in `sparql/catalog.json`.
2. Write the expected result by hand from the sample data **before** running anything.
3. Add `sparql/cq<NN>_name.rq`. The first line is `# CQNN: <the question>?`.
4. Add the expected rows to `CASES` in `tests/test_sparql_competency.py` (or a dedicated test for `ASK`/`CONSTRUCT`), and a mutation test showing the answer depends on the modelled fact.
5. List the concepts, properties and tests in the catalog, then run `python scripts/build_cq_doc.py`.

The suite fails if a query has no catalog entry, if the catalog names a term the query does not use or the ontology does not define, if a cited test does not exist, or if this document is stale.

## Limits

- The queries run against the RDF graph with no reasoner, except CQ21, which applies the subclass closure. A full OWL reasoner (HermiT, needs Java) is exercised separately in `tests/test_ontology.py`.
- Answers are checked against the sample data (47 CSV rows). They show that the model can answer the questions, not that it scales.
- The Cypher equivalents over the Neo4j projection are not part of this chain; the projection is a derived view and is tested against the RDF separately.
"""


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def build() -> str:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["questions"]
    out = [INTRO, f"## The {len(catalog)} questions at a glance\n"]
    out.append("| ID | Domain Question | Ontology Concepts | Properties | SPARQL Query | Expected Result | Test |")
    out.append("|---|---|---|---|---|---|---|")
    for q in catalog:
        cid = q["id"].split("_")[0].upper()
        concepts = ", ".join(f"`{c}`" for c in q["concepts"]) or "—"
        props = ", ".join(f"`{p}`" for p in q["properties"]) or "—"
        tests = "; ".join(f"`{t}`" for t in q["tests"])
        out.append(f"| {cid} | {cell(q['domain_question'])} | {concepts} | {props} | "
                   f"[{q['form']}](../sparql/{q['id']}.rq) | {cell(q['expected'])} | {tests} |")
    out.append(f"\nAll tests are in [{TEST_FILE}](../{TEST_FILE}). Each query has the same prefix block; `hc:` is "
               "`http://example.org/healthcare-hospital.owl#`.\n")
    out.append("## Each question in detail\n")
    for q in catalog:
        cid = q["id"].split("_")[0].upper()
        query = (ROOT / "sparql" / f"{q['id']}.rq").read_text(encoding="utf-8").strip()
        out.append(f"### {cid}. {q['domain_question']}\n")
        out.append(f"**Purpose.** {q['purpose']}\n")
        out.append(f"**Form.** {q['form']}" + ("; needs the class hierarchy applied before querying" if q.get("requires_entailment") else "") + "\n")
        out.append("```sparql\n" + query + "\n```\n")
        out.append(f"**Expected result.** {q['expected']}\n")
        out.append(f"**Why it works.** {q['explanation']}\n")
        out.append("**Tests.** " + "; ".join(f"`{t}`" for t in q["tests"]) + "\n")
    out.append(OUTRO)
    return "\n".join(out).rstrip("\n") + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if docs/competency-questions.md is stale")
    args = parser.parse_args()
    text = build()
    if args.check:
        current = OUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUT.exists() else ""
        if current != text:
            print("docs/competency-questions.md is stale; run: python scripts/build_cq_doc.py")
            return 1
        print("docs/competency-questions.md is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
