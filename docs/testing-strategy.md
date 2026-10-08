# Testing Strategy for an Ontology and Knowledge-Graph Project

A test suite for semantic software has to prove things that ordinary unit tests never touch: that the *model* says what we mean, that the *data* obeys the model, that *queries* answer the questions we built the system to answer, that a *derived graph* has lost nothing, and that the *API* does not let anyone bypass all of that. This chapter describes how this repository does it, and why the tests are written the way they are.

The one rule behind everything below: **a test is only worth having if it can fail.** A suite of 500 assertions that cannot fail proves nothing. Every group of tests here has a way to demonstrate that it detects the defect it is for.

## 1. The test pyramid

Run any level on its own with a pytest marker, for example `pytest -m shacl`. The level of each module is declared once, in `tests/levels.py`; `tests/test_strategy.py` fails if a new test file is not classified.

| Level (marker) | Question it answers | Modules | Speed |
|---|---|---|---|
| `unit` | Does this function behave? | `test_query_validation`, `test_governance`, `test_enterprise`, `test_agent_graph`, `test_cypher_generation`, `test_memory*`, `test_lexical_memory`, `test_devtools` | milliseconds |
| `ontology` | Is the model what we intended? | `test_ontology` | fast (reasoner tests are slower) |
| `rdf` | Is the RDF artifact well-formed and is it the generator's output? | `test_ontology` | fast |
| `shacl` | Does each shape accept valid and reject invalid data? | `test_shape_contracts`, `test_clinical_shapes`, `test_patient_shapes`, `test_doctor_shapes`, `test_shacl_validation` | seconds |
| `sparql` | Can we answer the competency questions? | `test_sparql_competency` | fast |
| `projection` | Does RDF to graph lose or invent anything? | `test_graph_projection`, `test_projection_oracle`, `test_neo4j_sync` | fast |
| `api` | Who may do what, and what happens on bad input? | `test_api`, `test_api_validation`, `test_api_boundaries` | seconds |
| `integration` | Do the components agree with each other (and README, scripts, Docker, config)? | `test_ontology_service`, `test_sample_data`, `test_architecture_boundaries`, `test_audit_regressions`, `test_consistency`, `test_security_architecture` | seconds |
| `e2e` | Does the whole pipeline hold together? | `test_pipeline_e2e` | seconds |
| `reasoner` | Is the ontology consistent; do axioms infer what we claim? Needs Java; skipped without it | tests marked with `needs_java` | several seconds each |

Shape of the pyramid: many fast, narrow tests at the bottom (`unit`, `shacl`, `sparql`, `projection`: pure functions and in-memory graphs); fewer, broader tests above (`api`, `integration`); a handful of `e2e` tests that run the real pipeline. Neo4j is never required: it is replaced by a recording driver, so the suite runs anywhere.

## 2. How the suite demonstrates six kinds of correctness

### 2.1 Ontology correctness (`ontology`, `rdf`, `reasoner`)

*Is the model right?* `tests/test_ontology.py` reads the OWL file with rdflib and checks structure, not the engine's opinion of it:

* **Required classes and properties exist.** A named core of 27 classes, and the relationships that make up the Encounter model, with the correct domain and range.
* **Known anti-patterns stay gone.** A list of removed classes (`Cardiologist`, `Analgesic`, `Admission`, `LabResult`, ...) and removed properties (`specialization`, `diagnosisCode`, string dates). If someone reintroduces specialty-as-subclass, a test names it.
* **Inverses, hierarchy, characteristics.** Sixteen inverse pairs, the sub-property chain, the transitive property, and the single-valued attributes declared functional.
* **Datatypes.** Calendar dates are `xsd:date`; instants are `xsd:dateTime`; no property whose name ends in `Date`/`Time`/`Start`/`End` may be a string. Instants in the data must carry a time zone.
* **Documentation.** Every class has a label and a real definition (at least 25 characters, which caught a 21-character comment); every property has a label and comment; the header has a version.
* **The artifact equals its source.** The generator is run and its output compared, as an RDF graph, with the committed file.
* **Semantics, by a reasoner (`reasoner`).** The ontology is consistent, `Metformin` and `InsulinGlargine` are *inferred* to be antidiabetic medications, `Encounter006` is inferred to be inpatient, inverse and transitive relations are derived. The reasoner also rejects a medication that "has an encounter", because the domain plus a disjointness axiom make it inconsistent (`test_audit_regressions`).

### 2.2 Data correctness (`shacl`)

*Does data obey the model?* The pattern is **mutation testing for data** (`tests/test_shape_contracts.py`):

1. Start from a document that conforms (`valid_encounter.ttl`, `valid_medication_safety.ttl`). Assert it has no violations. This proves a rule is not simply always firing.
2. Change **exactly one thing**: delete a required property, wrong datatype, impossible date, a link to the wrong kind of entity, a second owner for a record.
3. Require **the specific rule that owns that defect** to fire, with the expected severity.

There are 37 such mutations covering Patient, Condition/Diagnosis, Encounter, Observation, Medication, Allergy and the prescription/allergy safety rule, at Violation, Warning and Info severities. The same idea is applied to the **real sample data** (`test_audit_regressions`): remove each required property of a real individual and the specific violation must appear.

### 2.3 Semantic correctness (regression and reasoning)

*Does it mean the right thing, not just parse?* `tests/test_audit_regressions.py` holds one test per audit finding, written so that it fails if the finding returns:

| Finding | Guarded at |
|---|---|
| Metformin / insulin typed as `Analgesic` | RDF types, projection labels, API class list and instances |
| `PatientJohn` failed his own shape | shape check on the real data, plus a mutation proving the check is not vacuous |
| Dates stored as strings | five invalid date forms must fail |
| Relationships could point at the wrong kind of thing | eight wrong-target mutations on real data, plus an OWL-reasoner version |
| One `Diagnosis` shared by two patients | shape on real data |
| Allergy conflict undetected | shape on real data |

### 2.4 Query correctness (`sparql`)

*Can we answer the questions the system exists to answer?* Each competency question is a file in `sparql/` (`cq01_patients.rq` ... `cq21_patients_with_a_condition.rq`; traceability in [competency-questions.md](competency-questions.md)). The expected answers in `tests/test_sparql_competency.py` were written **by hand from the sample data**, not copied from the engine's output. Further tests make the queries earn their place:

* every query file has an expected answer and vice versa (no untested query);
* every `hc:` term a query uses must exist in the ontology (no invented queries);
* the **conflict query** (CQ10) returns nothing on clean data and must return the offending prescription on mutated data;
* the **code query** (CQ04) is parameterised and must change its answer with its parameters;
* a plain `?x a hc:Person` returns nothing while the subclass path in CQ14 returns eleven people, which shows *why* the path is needed;
* `sparql/catalog.json` is checked against the queries, the ontology and the tests (every cited test exists, every listed term is real), and `docs/competency-questions.md` is generated from it and tested for staleness;
* `ASK` (CQ19) and `CONSTRUCT` (CQ20) have tests of their own, and CQ21 shows an answer that appears only after the class hierarchy is applied;
* two competency questions are also run through the real `POST /sparql` endpoint.

### 2.5 Graph correctness (`projection`)

*Does the derived graph keep the meaning?* There are three layers.

* **Direct tests** of the mapping: all classes appear, multiple types and values are kept, the hierarchy is kept, identity is the IRI, same-named individuals in two namespaces stay two nodes, repeated and reordered builds give the same fingerprint, invalid RDF is rejected with every problem listed.
* **An independent oracle** (`test_projection_oracle.py`). From the raw triples alone, it computes what must be present in the projection: every asserted type, every literal value, every relationship between individuals, every subclass link. It shares no code with the builder.
* **The oracle is itself tested** by feeding it *deliberately degraded* projections that reproduce the old exporter's defects: first type only, first value only, flattened hierarchy, identity by name, dropped relationships. The oracle must catch each one, and for the right reason. A verifier that was never shown a defect cannot be trusted to find one.

The writer is tested against a recording fake driver: statements are parameterised (no data values in Cypher text), every `DELETE` is scoped to projection labels, a resync sends the same statements, validation failure stops everything before the first database call, and the development reset is refused in production.

### 2.6 API correctness (`api`)

`tests/test_api_boundaries.py` covers, with the real FastAPI app:

* **Authentication.** Eight endpoints return 401 without the key and with a wrong key; a rejected key never reveals the expected one.
* **Authorization.** Viewer, analyst and admin permissions; an unknown role is treated as least privilege.
* **Tenant isolation.** Each tenant lists only its own ontologies; unknown and inactive tenants are 404.
* **Invalid input.** Field-level 422s, unparseable RDF is a 400 not a 500, empty uploads, 404 for unknown resources, 405 for write methods on read resources.
* **Safe queries.** Eight SPARQL update forms and nine Cypher write/admin forms are refused before execution with a stable error shape; a keyword inside a string value is not mistaken for a command.
* **Forbidden operations.** No reset/clear/wipe route exists.
* **Error hygiene.** Server errors never echo credentials.

## 3. Known gaps are tests too

*Update:* all seven gaps listed below were closed by the security hardening ([security-architecture.md](security-architecture.md)); their tests are now ordinary passing tests and no `xfail` remains. The mechanism is kept for the next gap. The original table is kept to show the pattern.

Seven tests were marked `xfail(strict=True)`. Each states the behaviour the system *should* have, fails today, and carries the reason. They document real, current weaknesses instead of hiding them:

| Test | Gap |
|---|---|
| a client cannot grant itself admin with a header | roles come from `X-Role` (audit PY-C1) |
| a tenant cannot read another tenant's ontology by id | missing tenant check on `GET /enterprise/ontologies/{id}` |
| Cypher procedure calls are rejected | keyword blocklist lets `apoc.*` through (PY-H1) |
| SPARQL `SERVICE` is rejected | federated queries are not blocked (SEC-5) |
| `/validate/ontology` refuses arbitrary server paths | caller-supplied path is read (SEC-6) |
| rate-limit key cannot be chosen by the caller | `X-Forwarded-For` is trusted |
| the API accepts a valid property-path query | the schema check misreads `rdfs:subClassOf` |

`strict=True` means the day a gap is fixed the test *fails* ("unexpectedly passed"), forcing someone to remove the marker. The list of known gaps cannot rot.

## 4. What the tests found while being written

Good tests teach you about the system. Writing these found, besides the original audit findings:

1. **Range inference defeated validation.** With the schema in the data graph and pySHACL's RDFS inference on, `rdfs:range` is applied as an *entailment*: pointing `hasEncounter` at a Doctor made the Doctor "an Encounter", so the `sh:class` check passed. Eight wrong-relationship mutations failed for this reason. Fix: `entail_hierarchy()` entails only subclass and sub-property closure, never domain or range.
2. **A label collision.** The ontology class `Procedure` and agent memory's `:Procedure` shared a Neo4j label.
3. **rdflib canonicalises typed literals** (`"2026-03-01 09:30:00Z"^^xsd:dateTime` becomes a standard dateTime), so some lexical defects are invisible to SHACL and must be caught at the source.
4. **`xsd:date` is outside the OWL 2 datatype map**, so the reasoner needs a date-stripped view.
5. **Weak shapes:** a missing `AllergyShape`, no relationship-type guards on `Patient`, and a time-zone pattern that was too permissive.
6. **Validator false positive:** `rdfs:subClassOf` is rejected as an "unknown hc term".

## 5. Weak tests found and replaced

A scan for `>= 0`, `is not None`, `isinstance(...)`, `"key" in json`, `len(x) > 0`, `assert True` and branching assertions found these. Each was replaced by an assertion that fails for a specific wrong answer.

| Before | Why it proved nothing | After |
|---|---|---|
| `total_violations >= 0` | true for any number | zero Violations on the shipped data, plus a mutation that must fail |
| `/validate/ontology` returns keys `conforms`, `summary` | keys exist even if the result is wrong | `conforms is True`, zero violations, data source named |
| inline-patient validation returns `"summary"` | any response passes | must be non-conforming, with the exact `lastName` and `xsd:date` messages |
| `/validation/report` has `"conforms"` | stale or wrong report passes | same `validated_at` as the run that produced it |
| HTML report contains `"SHACL"` | static heading | contains the actual finding text |
| `len(shapes_graph) > 0` (twice) | any file passes | 15 expected shape names are all present |
| `/patients` is a list | empty list passes | exact five patients, John's name and blood group |
| `/search` has `"results"` | key only | exact names, all matching, `DrSmith` excluded |
| hallucinated property: stage in `("schema","syntax")` | two outcomes accepted | stage must be `schema`, names the term |
| delete endpoint: `if dict ... else ...` | the weaker branch could pass | one deterministic assertion on stage and forbidden words |
| `/metrics` has `"counters"` | key only | two rejected calls increase the counter by exactly two |
| guardrail `redacted_text is not None` | any text passes | exact redacted string and `pii` flag |
| registry `assert path` | any non-empty string | the file exists and is the ontology |
| `tenant_registry.get(...) is not None` | existence only | exact ontology ids per tenant |
| eval runner has `"avg_score"` | key only | exact case counts and pass count |
| `graph is not None` | redundant | removed |

Not changed, because they assert real outcomes: `is not None` before further checks in `test_governance` and `test_enterprise`, and the `>= 0.3` confidence threshold tests.

## 6. Running it

```bash
pytest                         # everything (reasoner tests skip without Java)
pytest -m "not reasoner"       # fast path
pytest -m shacl                # one level
pytest -m "projection or sparql"
pytest -ra                     # list skips (and any expected failures) with reasons
```

CI runs the whole suite; the GitHub runner has Java, so the reasoner tests run there.

## 6b. Data-pipeline tests

`test_sample_data.py` covers the CSV -> contract -> RDF -> SHACL path ([sample-data-and-semantic-mapping.md](sample-data-and-semantic-mapping.md)): one parametrized test per directory in `data/invalid_source/`, a meta-test that every check has a fixture that triggers it, generator refusal with no output written, the SHACL gate with the contract bypassed, and a comparison of the committed RDF's medication categories with the independent reference.

## 6c. Architecture-boundary tests

`test_architecture_boundaries.py` enforces the core/advanced split ([core-vs-ai-architecture.md](core-vs-ai-architecture.md)): an import-graph analysis (no core module imports an AI library or an advanced module at import time; the lazy exceptions are an exact allow-list), a runtime run in an interpreter where the AI libraries and the Neo4j driver cannot be imported (the real API, SHACL, the data contract and the projection plan still work), `ENABLE_AI_LAYER=false`, abstention without a model, and the requirements split.

## 6d. Documentation tests

`test_book_exercises.py` treats the book material as code: every offline exercise in [book-chapter-mapping.md](book-chapter-mapping.md) is run and its stated outcome asserted; every relative link, every repository path in backticks and every test name cited in the new documents must exist; and the promised structure (fourteen chapters, nine diagrams, eight anti-patterns, eight troubleshooting areas, the six-column mapping table) is checked. A renamed file or a stale claim fails the build.

## 6e. Hardening tests

`test_sparql_timeout.py` starts real worker processes, runs a query that never ends on its own, and asserts that it is cut off at the limit, that the process is gone afterwards, that other workers keep answering, that the API returns a short 504 with no internals, and that invalid configuration fails by name. `test_security_policy.py` runs the policy over every combination of environment, credentials, opt-in and RBAC setting and asserts that unauthenticated admin never occurs in production. `test_deployment_hardening.py` reads the Compose and Kubernetes YAML and asserts what it says (production mode, loopback ports, non-root, dropped capabilities, no `:latest`, no secrets). Those last tests prove the files' contents, not the behaviour of Docker or a cluster, neither of which was run.

## 6f. Schema/data separation tests

`test_schema_and_data.py` pins the TBox/ABox boundary ([schema-and-sample-data.md](schema-and-sample-data.md)): the schema parses alone and contains no individual that is not a vocabulary concept (and a mutation shows that a synthetic patient injected into it is detected); the sample data contains the expected 94 individuals with their original IRIs, declares no schema, and is described entirely in the schema's terms; the combined graph passes SHACL, is isomorphic to the frozen pre-split graph (`tests/fixtures/combined_before_split.nt`), projects to the identical Neo4j plan (pinned fingerprint), and works with the OWL reasoner; the platform runs on the schema alone; and the two generators are deterministic byte for byte. The competency-question tests now run against the combined dataset, not against any one file.

## 6g. Live Neo4j tests

`test_neo4j_live.py` (marker `live`) runs against a REAL Neo4j and is opt-in: `RUN_LIVE_NEO4J=1 NEO4J_DATABASE=<empty database> python -m pytest tests/test_neo4j_live.py`. It loads the projection, compares the database with the RDF (nodes, labels, properties, relationships, fingerprint), checks identity, multi-valued data, the class hierarchy, inferred inverses and datatypes, the read-only guarantee of the database itself, and the API's authentication, authorization, destructive-query refusal, timeout and tenant controls against the live database. It SKIPS, writing nothing, if the target database holds nodes from another graph domain. `test_neo4j_desktop.py` covers, with no database, the configuration contract, the foreign-data guard and the timeout mapping; its fake driver rejects a `Query` object in `tx.run` as a real server does, because a lenient fake once hid a bug that made `/execute-cypher` fail against Neo4j.

## 6h. Live AI-layer tests

`test_ai_live.py` (marker `live`, opt-in with `RUN_LIVE_AI=1`, normally together with `RUN_LIVE_NEO4J=1` and an empty `NEO4J_DATABASE`) calls the real OpenAI API and the real agent: the smallest chat and embedding calls, natural-language SPARQL that may not invent patients, embeddings stored and retrieved, a grounded agent answer with provenance, refusal of an out-of-domain and a no-rows question, a rejected approval that executes nothing, a destructive instruction blocked, and the projection unchanged afterwards. `conftest.py` forces a placeholder OpenAI key and tracing off unless `RUN_LIVE_AI=1`, so an ordinary run can never spend money or reach a third party. `test_ai_layer_fixes.py` holds the no-network regression tests for the defects that run found (prompt grounding, embedding storage, ontology-only abstention, key redaction).

## 7. What is not tested

* **A live Neo4j.** The writer is verified with a recording driver (what would be sent, in what order, within what scope). Running `POST /neo4j/load` against a real instance is still a manual step.
* **The LLM paths.** Generated queries are validated, but no test calls a model.
* **Concurrency and scale.** One process, hundreds of triples.
* **Real clinical correctness.** The data is synthetic.

## 8. Adding a test: a checklist

1. Which level is it? Add the module to `tests/levels.py` (a test, `test_strategy`, will remind you).
2. Can it fail? Show it failing against a deliberately broken input or implementation before you rely on it.
3. Does it assert the exact expected value, not just that something came back?
4. If it documents a gap, use `xfail(strict=True)` with the reason, not a skip.
5. If it uses sample data, does it state the expected answer independently of the code under test?
