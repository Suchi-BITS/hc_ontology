# Book chapter mapping

How each chapter of the book maps onto this repository. The journey in prose, with WHY / WHAT / HOW / TRADE-OFFS / COMMON MISTAKES for every chapter, is [reader-journey.md](reader-journey.md); the diagrams are in [architecture-diagrams.md](architecture-diagrams.md).

Run commands from the project root with the project's Python (`python scripts/dev.py setup` creates it). Exercises E01 to E14 are run in section 2; their expected outcomes are checked by `tests/test_book_exercises.py`, so they cannot drift without a test failing. Exercises marked *(needs Java)* or *(optional layer)* are not part of that test.

## 1. The mapping

| Chapter | Concept | Repository Location | Example | Exercise | Expected Outcome |
|---|---|---|---|---|---|
| 01 Domain | Competency questions drive the model | [docs/competency-questions.md](competency-questions.md), `sparql/catalog.json` | CQ10: medication/allergy conflicts | **E01** Find the question the model cannot answer | "indicates" is not in the ontology; CQ18 asks the supportable question instead |
| 02 Vocabulary | SKOS vocabularies; code binding; reference data | `services/reference_vocab.py`, `data/source/codes.csv`, `data/reference/drug_classification.csv` | `Icd10_E11`, `MedCategoryAntidiabetic` | **E02** Misclassify Metformin as an analgesic | The data contract rejects it before any RDF is built (exit 2, `INVALID_CLASSIFICATION`) |
| 03 Taxonomy | Class hierarchy; defined classes | `CLASSES` in `scripts/generate_hc_ontology.py` | `Doctor` -> `Practitioner` -> `Person` | **E03** List the superclasses of `Diagnosis` and `Doctor` | `Condition` and `Person, Practitioner` (plus `Thing`) |
| 04 Ontology | A generated, reviewed TBox | `scripts/generate_hc_ontology.py`, [docs/ontology-engineering.md](ontology-engineering.md) | 56 classes, 86 + 74 properties | **E04** Add a specialty and regenerate | One more vocabulary individual in the schema (30 -> 31); the sample data does not change |
| 05 RDF | Triples, IRIs, typed literals; schema versus instances | `ontology/healthcare_schema.ttl`, `data/sample_data.ttl`, [docs/schema-and-sample-data.md](schema-and-sample-data.md) | `PatientJohn` | **E05** Parse the files and count | 1,422 + 593 triples; 2,015 combined |
| 06 OWL | Inference, consistency, open world | `tests/test_ontology.py` (reasoner group), `tests/reasoning.py` | Metformin classified as antidiabetic | **E06** Run the reasoner tests *(needs Java)* | 4 pass: consistent; antidiabetic and inpatient classified; inverses inferred |
| 07 SHACL | Shapes, severities, closed-world checks | `shapes/`, `core/shacl_validator.py`, `data/sample_instances/` | `invalid_patient_missing_dob.ttl` | **E07** Validate the invalid patient | Not conforming; `Patient must have a dateOfBirth.` |
| 08 SPARQL | Queries as tested questions | `sparql/*.rq`, `tests/test_sparql_competency.py` | CQ04: patients by code | **E08** Run CQ04 with the SNOMED code for diabetes | `PatientAlice`, `PatientBob` |
| 09 Knowledge graph | Authority vs derived projection | `services/graph_projection.py`, [docs/semantic-authority-and-graph-projection.md](semantic-authority-and-graph-projection.md) | RDF -> Neo4j plan | **E09** Plan the projection with no database | 124 nodes, 58 classes, 476 relationships |
| 10 Validation | Data contract, SHACL gate, test pyramid | `services/sample_data.py`, `data/invalid_source/`, [docs/sample-data-and-semantic-mapping.md](sample-data-and-semantic-mapping.md) | `metformin_analgesic` | **E10** Feed a broken table to the generator | Exit code 2, the problem is named, no output file |
| 11 API | Authentication, authorization, tenancy | `api.py`, `routers/`, `core/security.py`, [docs/security-architecture.md](security-architecture.md), `examples/requests.http` | Forged `X-Role: admin` | **E11** Run the forged-role tests | 8 pass: the header grants nothing |
| 12 Interoperability | Codes, identifiers, check digits, RDF interchange | `data/source/codes.csv`, `services/reference_vocab.py`, `CodeConcept` in the generator | ICD-10 `E11` and SNOMED `44054006` | **E12** Corrupt a SNOMED code. **E12b** Sketch a FHIR mapping | `INVALID_CODE` (Verhoeff). E12b has no shipped answer: it is a design task |
| 13 RAG | Hybrid retrieval of ontology concepts | `enterprise/hybrid_retrieval.py`, `enterprise/lexical_memory.py` | The lexical channel | **E13** Score concept names against a question | `Metformin` scores above zero; `Amlodipine` scores zero |
| 14 Agentic AI | Planning, approval, abstention | `agents/`, `enterprise/abstention.py` | `decide_abstention` | **E14** Decide for grounded, ungrounded and rejected states | Allowed; refused `missing_provenance`; refused `human_rejected` |

## 2. The exercises

Each one: **goal**, **steps**, **expected outcome**, and **what it teaches**.

### E01 The question the model cannot answer
Goal: see why a competency question can be refused.
Steps: read CQ18 in [competency-questions.md](competency-questions.md). The natural question is "which observations *indicate* a condition?". Search the ontology for an `indicates` relation: `python -c "from core.dataset import Dataset; print(any('indicates' in p.read_text(encoding='utf-8') for p in Dataset.default().paths))"`.
Expected: `False`. CQ18 therefore asks which measurements were taken in the encounter where the condition was diagnosed, and says it is co-occurrence.
Teaches: only ask questions the model supports; do not invent causation.

### E02 Misclassify a medication
Goal: watch the data contract stop the original audit defect.
Steps:
```bash
python -c "import shutil; shutil.copytree('data/source', 'bad_source'); shutil.copy('data/invalid_source/metformin_analgesic/medications.csv', 'bad_source/medications.csv')"
python scripts/generate_sample_data.py --source-dir bad_source --output bad.ttl
```
Expected: exit code `2` (`echo $?`, or `$LASTEXITCODE` in PowerShell); `[INVALID_CLASSIFICATION] medications.csv:4 Metformin: categories ['Analgesic'] disagree with the reference ['Antidiabetic']`; `bad.ttl` does not exist. Delete the `bad_source` directory afterwards.
Teaches: check against an independent reference, and fail before writing.

### E03 Walk up the taxonomy
Steps:
```python
from rdflib import Graph, RDFS, Namespace
from core.dataset import Dataset
HC = Namespace("http://example.org/healthcare-hospital.owl#")
g = Dataset.default().graph()          # the schema and the sample data, merged
for cls in (HC.Diagnosis, HC.Doctor):
    print(sorted(str(o).split("#")[-1] for o in g.transitive_objects(cls, RDFS.subClassOf) if o != cls))
```
Expected: `['Condition', 'Thing']` and `['Person', 'Practitioner', 'Thing']`.
Teaches: why CQ14 and CQ21 need the hierarchy.

### E04 Extend a vocabulary
Steps: add `"Dermatology": "Dermatology",` to `SPECIALTIES` in `services/reference_vocab.py`, then `python scripts/generate_hc_ontology.py --output derm.ttl`. Revert the edit afterwards.
Expected: the last line reads `vocabulary_individuals=31` (was 30), and `python scripts/validate.py` would report the committed schema as different until you regenerate it. The sample data does not change.
Teaches: vocabulary is data in one place; the committed artifact must follow the generator.

### E05 Count the triples
Steps: `python -c "from rdflib import Graph; from core.dataset import Dataset as D; d = D.default(); print(len(Graph().parse(d.schema)), len(Graph().parse(d.data)), len(d.graph()))"`.
Expected: `1422 593 2015` (the combined graph has the 5-triple data header). Try serialising the combined graph as `format="nt"`: the same graph in another syntax.
Read [schema-and-sample-data.md](schema-and-sample-data.md) for why there are two files.
Teaches: RDF is the graph, not the file format.

### E06 Ask the reasoner *(needs Java)*
Steps: `python -m pytest tests/test_ontology.py -k reasoner -v`.
Expected: 4 passed. Read `test_reasoner_classifies_antidiabetic_medication` to see a class membership no one asserted.
Teaches: inference, and why the project keeps it optional.

### E07 See a SHACL violation
Steps:
```python
from core.shacl_validator import ShaclValidator
r = ShaclValidator().validate_data_file("data/sample_instances/invalid_patient_missing_dob.ttl")
print(r.summary.conforms, [v.message for v in r.violations if v.severity == "Violation"])
```
Expected: `False ['Patient must have a dateOfBirth.']`. Now validate `valid_encounter.ttl` the same way: `True`.
Teaches: required data is a SHACL rule, not an OWL axiom.

### E08 Run a competency question with a parameter
Steps: bind `?system` and `?code` and run `sparql/cq04_patients_by_condition_code.rq` (see `test_code_query_is_driven_by_its_parameters`):
```python
from rdflib import Literal, XSD
from core.dataset import Dataset
g = Dataset.default().graph()
q = open("sparql/cq04_patients_by_condition_code.rq", encoding="utf-8").read()
rows = g.query(q, initBindings={"system": Literal("http://snomed.info/sct", datatype=XSD.anyURI),
                                "code": Literal("44054006", datatype=XSD.string)})
print(sorted(str(r[0]).split("#")[-1] for r in rows))
```
Expected: `['PatientAlice', 'PatientBob']`. Change the code to `Z99`: an empty list.
Teaches: parameterised queries, and typed literals.

### E09 Plan a projection without a database
Steps: `python scripts/validate.py` and read step 4.
Expected: `124 nodes, 58 classes, 476 relationships`, then `VALIDATION PASSED`.
Teaches: the projection is a pure function of the RDF.

### E10 Break the data on purpose
Steps: pick any directory in `data/invalid_source/`, copy it over a copy of `data/source/`, run the generator with `--source-dir`. Read its `EXPECT` file first and predict the code.
Expected: exit `2`, the predicted problem code, no output file.
Teaches: every check has a case that makes it fail.

### E11 Forge a role
Steps: `python -m pytest tests/test_security_architecture.py -k forged -v`.
Expected: 8 passed, including `test_a_forged_admin_role_header_grants_nothing`.
Teaches: roles come from the server-side credential.

### E12 Corrupt a code; E12b map to FHIR
E12: change `Snomed_38341003`'s code in a copy of `codes.csv` to `38341004` (fixture `snomed_bad_check_digit`) and run the contract. Expected: `INVALID_CODE ... fails the SNOMED CT Verhoeff check digit`.
E12b (design task): sketch how `Encounter`, `Diagnosis` and `Observation` map to FHIR `Encounter`, `Condition` and `Observation`; where would `CodeConcept` become `CodeableConcept`? There is no shipped answer and no code; this is the honest gap in this chapter.
Teaches: a check digit catches typos, not non-existence; interoperability is a mapping table.

### E13 Score concepts lexically *(no model needed)*
Steps:
```python
from enterprise.lexical_memory import extract_tokens, overlap_score
tokens = extract_tokens("which patients take metformin for diabetes")
print({n: overlap_score(tokens, n) for n in ("Metformin", "Amlodipine", "Diagnosis")})
```
Expected: `Metformin` greater than 0; `Amlodipine` and `Diagnosis` exactly 0.
Teaches: the cheapest retrieval channel, and what the others add.

### E14 Decide whether to answer
Steps:
```python
from enterprise.abstention import decide_abstention
grounded = {"query_type": "sparql", "validated_query": "SELECT ?p WHERE { ?p a hc:Patient }",
            "results": [{"p": "PatientJohn"}] * 6, "validation_ok": True,
            "retrieved_concepts": [{"name": "Patient", "rerank_score": 0.9}]}
print(decide_abstention(grounded)["refusal_reason"])                              # allowed
print(decide_abstention(dict(grounded, results=[]))["refusal_reason"])            # no evidence
print(decide_abstention(dict(grounded, human_decision="rejected"))["refusal_reason"])
```
Expected: `None`, `missing_provenance`, `human_rejected`.
Teaches: refusing is a designed outcome with a reason, and it needs no model.

## 3. A suggested path

A reader with one weekend: chapters 01 to 08 and exercises E01, E03, E05, E07, E08. With a week: add 09 to 12 and E09 to E12. The optional layer (13 and 14) assumes all of the above and is best read last. Every exercise runs without Docker or an API key, except where marked.
