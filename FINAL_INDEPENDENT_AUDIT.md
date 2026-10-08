# Final Independent Technical and Book-Readiness Audit

**Repository:** `hc_ontology/`
**Audit date:** 2026-10-08
**Compares against:** [PROJECT_ARCHITECTURE_AND_BOOK_READINESS_AUDIT.md](PROJECT_ARCHITECTURE_AND_BOOK_READINESS_AUDIT.md) and [BOOK_REFERENCE_GAP_ANALYSIS.md](BOOK_REFERENCE_GAP_ANALYSIS.md)
**Rule applied:** credit only for what is **implemented, tested and documented**. A statement in a design document earns nothing. Where a previous fix is claimed, it was re-checked against the current tree, not against the earlier work log.

## 0. Method and limits

**What was done in this audit (all executed, this session):**
- Counted the ontology directly with rdflib (classes, properties, inverses, labels, datatypes, characteristics, individuals).
- Counted the shapes directly (node shapes, constraint kinds).
- Ran the full suite: **881 passed, 0 failed, 0 skipped** (Java is installed, so the six reasoner tests ran).
- Ran adversarial probes against the Cypher read-only policy (23 inputs) and the SPARQL validator and endpoint (13 inputs), including a deliberately expensive query.
- Listed the live route table of the FastAPI app.
- Searched code, configuration and documentation for the specific residues named in the task.
- Checked git state (`git ls-files`, `git status`, history).

**What could not be verified here, and therefore earns no credit as "working":**
- Anything that needs a **Neo4j server**, **Docker**, or an **OpenAI key**. The projection is verified against a recording fake and an independent in-memory oracle, never against a live database.
- **CI/CD.** The workflows exist and look sensible, but nothing in this repository has ever run them (see finding F5).
- Linux and macOS; Python other than 3.11.

**Important framing.** The repository is a git repository whose `HEAD` (`dc43f5ed`, "Agent included") is the *pre-remediation* state. Every improvement described below lives in an **uncommitted working tree** (15,914 changed paths, mostly the removal of a tracked `venv/`). This audit assesses the working tree.

---

## 1. Verification of the previous findings

Status key: **FIXED** (implemented, tested, documented), **PARTIAL**, **NOT FIXED**. "Evidence" is what I actually looked at.

| # | Finding | Status | Evidence in the current tree | Remaining gap |
|---|---|---|---|---|
| 1 | Ontology behaving like a database schema | **PARTIAL (largely fixed)** | 56 classes (was 75); `Encounter`, `Condition` > `Diagnosis`, `Observation`, `CodeConcept`, `Identifier`; vocabularies are SKOS concepts; `AntidiabeticMedication` is a *defined* class (2 `equivalentClass` axioms); `docs/ontology-engineering.md`; 122 ontology tests | `Patient`/`Doctor`/`Nurse` are still subclasses of `Person`: role-as-class remains for people. Billing, claims and invoices are still table-shaped. TBox and ABox are still **one file** |
| 2 | Missing inverse properties | **PARTIAL** | 32 `owl:inverseOf` pairs, tested (`test_inverse_properties`), inverse edges projected as inferred | **42 of 75 object properties have no inverse** (for example `diagnosedBy`, `prescribedBy`, `hasAllergy`, `reportsTo`). Some are deliberate (`hasCode`, `medicationCategory` point at reference data), but the 42 are not individually justified anywhere |
| 3 | String dates | **FIXED** | All 13 temporal properties are `xsd:date` or `xsd:dateTime`; `test_no_temporal_property_is_a_string`; SHACL requires a time zone; data contract rejects impossible dates | None found |
| 4 | Specialty modelling | **FIXED** | No `Cardiologist`/`Surgeon` subclasses; `Specialty` is a SKOS concept; `hasSpecialty` property; 11 specialty concepts | None found |
| 5 | Missing Encounter | **FIXED** | `Encounter` with type (SKOS), start/end `dateTime`, location, provider; 6 encounters; `InpatientEncounter` defined class; shape + tests | No status/class lifecycle; modest |
| 6 | Missing labels | **FIXED** | Counted: **0** classes, properties without `rdfs:label`; **0** of 149 properties and 0 classes without `rdfs:comment`; test enforces both | Comments are present; their *quality* varies |
| 7 | Metformin / insulin classification | **FIXED** | Both `Antidiabetic`; independent `data/reference/drug_classification.csv`; contract rejects mismatch; 2 fixtures reproduce the original defect; test reads the RDF itself | Reference has six drugs |
| 8 | PatientJohn validation failure | **FIXED** | `ShaclValidator().validate_ontology(...)`: conforms, 0 violations (2 Info messages); `PatientShape` unchanged and a test pins that | None found |
| 9 | Client-controlled `X-Role` | **FIXED** | Role resolved from a server-side hashed credential; 8 forged-role tests pass; `X-Role` appears in `core/security.py` only in the code that ignores and logs it | Development-open mode is still admin for everyone (F3) |
| 10 | Client-controlled `X-Tenant-ID` | **FIXED** | Tenant comes from the identity; naming another tenant is 403; tested | The clinical graph itself is shared across tenants (documented) |
| 11 | Destructive seed endpoint | **FIXED** | Live route table (78 routes): **no** route containing `seed` or `reset`; seeding is a CLI guarded by `require_demo_allowed()` | None found |
| 12 | Whole-database `DETACH DELETE` | **FIXED** | Every `DETACH DELETE` in code was inspected: the exporter's three are label-scoped to projection labels, the episodic one is scoped to one session's failed turns, the rest are test strings or the validator's blocklist; `test_every_delete_is_scoped_to_projection_labels` | Behaviour against a live server unverified |
| 13 | `.dockerignore` | **FIXED** | Present; excludes `.env`, `.env.*`, credential files, `venv`; tested | None found |
| 14 | Committed `venv` | **PARTIAL** | `git ls-files`: **0** `venv/` paths tracked, 0 `__pycache__`, `.env` not tracked | **Still in history**: `.git` is 94 MB and `HEAD` still contains it. Nothing is committed (F5) |
| 15 | Missing `.env.example` | **FIXED** | Present; a test fails if code reads an undocumented variable | None found |
| 16 | Ollama / OpenAI inconsistency | **MOSTLY FIXED** | `readme.md`, `COURSE_SETUP.md`, config and compose all say OpenAI; Ollama appears only as "not used" | The three legacy course scripts in `docs/` still mention Ollama |
| 17 | Lossy OWL to Neo4j exporter | **FIXED in code, UNVERIFIED live** | Rewritten (`services/graph_projection.py`): all superclass labels, typed literals, multi-values, inferred edges; 70 projection tests plus an independent oracle with seeded defects | **Never run against a real Neo4j** |
| 18 | Name-based graph identity | **FIXED in code, UNVERIFIED live** | Merge on IRI; IRI uniqueness constraint declared and tested; relationships connect by IRI with endpoint labels | Same as 17 |
| 19 | Missing ontology tests | **FIXED** | `ontology` marker: 122 tests (labels, inverses, datatypes, functional properties, vocabularies, reasoner) | None found |
| 20 | Weak / vacuous validation test | **PARTIAL** | The original weak tests were replaced | **A vacuous assertion still exists**: `tests/test_ontology.py:279` ends with `... or True` |
| 21 | Missing SPARQL tests | **FIXED** | 21 competency questions, hand-written expected answers, mutation tests, catalog consistency tests, 41 `sparql` tests | None found |
| 22 | Missing graph projection tests | **FIXED** | 70 `projection` tests, oracle, recording-driver sync tests | Offline only |

**Tally:** 15 fixed outright, 2 fixed in code but unverified against the real system, 5 partial (one of them "mostly fixed"), 0 not fixed.

---

## 2. New and residual findings

Ranked by what they cost a book that presents this as a reference implementation. Severity is mine.

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| **F1** | **High** | **The SPARQL endpoint has no execution timeout.** The validator allows `SELECT` and injects `LIMIT`, but an aggregate over a cartesian product never returns. | I sent `SELECT (COUNT(*) AS ?n) WHERE { ?a ?b ?c . ?d ?e ?f . ?g ?h ?i . ?j ?k ?l }` to `/sparql` through the real app: it did not complete within the 280 s test window, while a three-pattern cartesian with `LIMIT` took 0.2 s. A single request can pin a worker. There is no `*timeout*` setting for query execution in `get_settings()` |
| **F2** | **High** | **The default Docker Compose configuration exposes an unauthenticated admin API.** | `docker_compose.yaml`: `ENVIRONMENT: ${ENVIRONMENT:-development}`, `API_KEY: ${API_KEY:-}`, port `8000` published. With no credential, development-open mode treats every caller as admin, and nothing restricts that mode to loopback. It is announced in the log, which is not a control |
| **F3** | **High (for publication)** | **None of the remediation is committed and no CI run has ever happened.** | `git status`: 15,914 changed paths; `HEAD` is the old state; history still contains the 15,736-file `venv`. A reader cloning this repository today gets the unremediated code |
| **F4** | Medium | **Kubernetes manifest contradicts the project's own security guidance.** | `k8s/deployment.yaml`: `LANGCHAIN_TRACING_V2: "true"` and `OTEL_ENABLED: "true"` in the production ConfigMap (the docs warn tracing sends prompts and answers to a third party), image `healthcare-ontology-api:latest`, no `securityContext`, legacy `API_KEY` secret. It was not touched by any remediation |
| **F5** | Medium | **`execute_sparql` re-parses the whole OWL file and rewrites every string literal on every call.** | `services/load_ontology.py:409-428`. The original audit raised the re-parse; it was never fixed |
| **F6** | Medium | **Documentation drift.** | `docs/reproducibility.md` says "480 passed, 7 expected failures"; `docs/fresh-clone-verification.md` says "526 passed, 7 expected failures"; `readme.md` says "~500 tests". Actual: 881 passed, no xfail. The three legacy course scripts and parts of `system_design.md` and `graph_schema_design.md` predate the redesign. `docs/README.md` says so, but a reader meets the contradiction first |
| **F7** | Medium | **Scope imbalance is unchanged.** | Advanced layer (agents, enterprise, embeddings, generators, UI) is **8,623 of 17,593** non-test Python lines (**49%**); `services/embedding_service.py` is 1,485 lines. That code was classified, isolated and made optional, but not re-audited or substantially tested beyond fakes |
| **F8** | Medium | **TBox and ABox are one generated RDF/XML file; there is no Turtle source, no `owl:versionIRI`, no changelog.** | `healthcare_ontology.owl` holds 124 individuals with the schema. The original audit asked for this to be separated and versioned. Ontology IRI is `example.org` |
| **F9** | Medium | **SHACL has no temporal or cross-property rules and no closed shapes.** | Counted: `sh:closed` 0, `sh:lessThan` 0, `sh:minInclusive` 0, `sh:sparql` 2, `sh:in` 2. "Encounter ends before it starts" and "born after the encounter" are enforced only by the *data contract* (before RDF), not by SHACL, so RDF that bypasses the CSV path is not protected from them |
| **F10** | Low | **A vacuous assertion survives.** | `tests/test_ontology.py:279` `... or True` |
| **F11** | Low | **No linter, formatter or type checker is configured**, and some modules remain hard to read. | Neither `ruff` nor `pyflakes` is installed or configured; `services/load_ontology.py` still has irregular formatting. Python quality was not systematically improved |
| **F12** | Low | **`valid_patient.ttl` is misnamed**: it conforms to `patient_shapes.ttl` only and has violations against the full set. | Documented in troubleshooting; not renamed |
| **F13** | Low | **Healthcare model depth.** | Dosage is a free-text string on the order; no consent, provenance, care-team roles, medication strength/form/route; five patients |

**Things I tried to break that held up (credit given):**
- The Cypher read-only policy blocked all 19 malicious or evasive inputs I tried (SET, MERGE, nested `CALL { DELETE }`, `FOREACH`, `LOAD CSV`, `apoc.*`, `dbms.*`, comment tricks, Unicode non-breaking space, newline-split keywords, statement chaining, `UNION CREATE`, `USE`, `SHOW`, `REMOVE`, unbounded paths). It allowed the benign query, a string literal containing "DELETE" and a label named `` `DELETE` ``. It is strict to a fault: it also blocks the harmless `CALL db.labels()`, because all procedure calls are refused.
- The SPARQL validator blocked `SERVICE` (including nested in `OPTIONAL` and a sub-select), `FROM`, `ASK`, `CONSTRUCT`, `DESCRIBE`, and all write/update/`LOAD` keywords.
- No `seed`/`reset` route exists.

---

## 3. Area-by-area reassessment

| Area | Before | Now | Why |
|---|---|---|---|
| Ontology | 3 | **7** | Questions-first, Encounter/Condition/Observation, SKOS, code binding, defined classes, 100% labelled. Held back by the mixed TBox/ABox file, no versioning, 42 un-justified one-way properties, role subclasses |
| Healthcare modelling | 3 | **6.5** | Sound core and standards-shaped (system + value + display, check digits). Shallow beyond the core and tiny data; no FHIR mapper (documented) |
| RDF | 4 | **7** | Authoritative, typed, deterministic generation, isomorphism-tested, SHACL-gated writes. RDF/XML only |
| OWL | 3 | **6.5** | Real inverses, characteristics, disjointness, defined classes, an actual reasoner in tests and CI. Only 2 restrictions; modest use |
| SHACL | 6 | **7** | Best original area, now 15 node shapes with mutation tests and a deliberately narrow entailment. Missing temporal logic and closed shapes (F9) |
| SPARQL | 3 | **6.5** | 21 tested competency questions, parameterised, ASK/CONSTRUCT/aggregates. The endpoint has no timeout (F1) and re-parses per call (F5) |
| Knowledge graph | 2.5 | **6.5** | CSV, contract, RDF, gate, projection with an oracle. Small dataset, no provenance or entity resolution, **unverified against live Neo4j** |
| Neo4j projection | (lossy) | **6.5** | Correct by construction and tests; zero live verification |
| Python | 5 | **6** | Better seams (lazy imports, composition root), but 49% of the code is the untouched advanced layer; no static analysis |
| API | 4 | **6.5** | Real authn/authz, boundaries tested, layer switch, 503 on missing AI stack. No versioning/pagination; no query timeout |
| Security | 2 | **6** | The main original holes are closed and tested. Remaining: F1, F2, F4, shared clinical graph, API-key only |
| Testing | 5 | **8** | 881 passing tests, mutation and oracle methods, pyramid, architecture and documentation tests, known gaps closed. No live-system tests; one `or True`; CI never run |
| DevOps | 3 | **5** | One-command workflow, pinned constraints, non-root image with healthcheck, `.dockerignore`. Unrun CI, unrun Docker, F2 and F4 |
| Reproducibility | 2 | **7** | Simulated pristine clone, TLS fallback, core-only install actually built and tested. Windows-only evidence; uncommitted |
| Documentation | 4 | **7** | Substantial, honest about limits, tested links and exercises. Drift (F6) |
| RAG | (doc-stated) | **5** | Isolated and documented, retrieval channels explained; not independently verified beyond fakes and no live run |
| Agentic AI | (doc-stated) | **6** | Abstention and human approval are real, deterministic and tested offline, which is genuinely good. The graph, memory and LLM nodes are not independently verified live |
| Educational quality | 5 | **7.5** | Competency-question chain, anti-patterns tied to real defects and tests, 14 tested exercises |
| Packt book readiness | 3 | **6.5** | See section 5 |

---

## 4. Final scorecard

| Dimension | Before | **After** |
|---|---|---|
| PROJECT QUALITY | 4.5 | **7.0** |
| ONTOLOGY QUALITY | 3 | **7.0** |
| HEALTHCARE MODEL QUALITY | 3 | **6.5** |
| RDF/OWL QUALITY | 3.5 (4 and 3) | **7.0** |
| SHACL QUALITY | 6 | **7.0** |
| SPARQL QUALITY | 3 | **6.5** |
| KNOWLEDGE GRAPH QUALITY | 2.5 | **6.5** |
| SECURITY | 2 | **6.0** |
| TESTING | 5 | **8.0** |
| REPRODUCIBILITY | 2 | **7.0** |
| DOCUMENTATION | 4 | **7.0** |
| EDUCATIONAL VALUE | 5 | **7.5** |
| PRODUCTION READINESS | 2 | **4.0** |
| BOOK READINESS | 3 | **6.5** |

**Against the original headline numbers:**

```
PROJECT:     4.5 -> 7.0
BOOK:        3.0 -> 6.5
PRODUCTION:  2.0 -> 4.0
```

These are not 9s on purpose. The semantic spine is now real, tested and honest about its limits, but three things hold the scores down: nothing is committed or CI-verified (F3), the system has never been run against Neo4j, Docker or an LLM, and about half of the code is an advanced layer that was isolated rather than re-engineered.

---

## 5. Packt assessment

**1. Is the repository now credible as a companion repository for a Packt book?**
Yes for the core chapters, with conditions. Chapters 1 to 12 (domain to interoperability) are backed by working, tested, reproducible material, with competency questions as regression tests, a data contract with 50 deliberate failures, SHACL as a gate and a tested projection. Chapters 13 and 14 are credible as *advanced* material but are not independently verified. It is not credible until F3 (commit, CI run, history) and F2 are resolved: a reviewer who clones it today gets the old tree.

**2. Strongest distinctive technical contributions.**
- **Competency questions as a traceability chain with mutation tests**, and a document generated from, and tested against, the same catalog (CQ10/CQ19 are shown capable of returning something before an empty answer is trusted).
- **A narrow, explained SHACL entailment** that avoids RDFS `range` typing a wrong target into validity (a real defect found by building the tests).
- **Authority-and-projection with an independent oracle**: the projection is tested against a second implementation with seeded defects.
- **Layered validation with named failure fixtures** (contract, SHACL, projection gate), each check paired with a case that makes it fail, enforced by a meta-test.
- **Abstention and provenance as deterministic, model-free logic.**
- **Architecture-boundary tests** that prove the core runs with the AI libraries unimportable, backed by a real core-only install.

**3. What remains weak.** F1 to F9 above: no query timeout, exposed dev-open Compose default, uncommitted state, unverified live paths, doc drift, the large unreviewed advanced layer, mixed TBox/ABox, thin SHACL temporal rules, small data.

**4. Genuine expertise is visible in:** the OWL-versus-SHACL split and the entailment boundary; competency-question engineering; projection design (IRI identity, superclass labels, inferred edges marked as such, scoped deletes); the security layering (identity, authentication, authorization, tenant, read-only execution, structural allow-list); and the way tests are designed (mutation, oracle, meta-tests).

**5. Still looks like tutorial or prototype code.** `services/embedding_service.py` and `services/document_ingestor.py`; `streamlit_app.py` (739 lines); the agent memory modules; the in-memory job store, tenant registry and metrics; the enterprise evaluation/workflows; the Kubernetes manifest; the legacy course scripts; the single-key authentication model.

**6. What to improve before publication (in order).**
1. Commit the work, remove `venv/` from history (or start a clean repository), run CI and CD for real, record the result.
2. Add a SPARQL execution timeout and a result/pattern complexity guard (F1); cache the parsed graph (F5).
3. Make Compose and Kubernetes safe by default: bind development-open mode to loopback or refuse it when the port is published; fix the manifest (F2, F4).
4. Verify the Neo4j, Docker and OpenAI paths once, on a real machine, and record the results the way `fresh-clone-verification.md` records the offline ones.
5. Reconcile documentation numbers and retire or clearly archive the legacy scripts (F6).
6. Separate the TBox (Turtle, versioned, with a changelog) from the sample ABox (F8).
7. Add SHACL temporal rules so the shapes protect RDF that bypasses the CSV path (F9).
8. Remove the `or True` assertion; add `ruff`/`mypy` to CI (F10, F11).

**7. What can intentionally remain simplified.** One hospital and five patients, English only, `example.org` IRIs, API-key authentication labelled as a floor, the in-memory job store, a six-drug reference, no FHIR mapper if the chapter says so, a shared clinical graph across tenants (stated), RDF/XML as the interchange file if the Turtle source exists.

**8. What should become advanced chapters.** Hybrid retrieval and rerank; query generation with validation; the agent graph, memory, human approval and abstention; evaluation and tracing; multi-tenant deployment; vector search over the graph.

**9. What should become exercises.** The 14 already in `docs/book-chapter-mapping.md`, plus: add a SHACL rule for encounter ordering; add a missing inverse and justify the rest; write a FHIR mapping table (E12b); add a SPARQL timeout and a test that proves it fires; add a new competency question with its mutation test; make Compose refuse development-open on a published port.

**10. What should become architecture diagrams.** The nine in `docs/architecture-diagrams.md` are right. Add: the validation-gate sequence with the failing fixture beside each gate; the security request path (credential, identity, permission, tenant, read-only execution); and a deployment diagram that shows where development-open mode is and is not allowed.

---

## 6. Conclusion

The repository has moved from a prototype with a thin semantic layer to a tested, documented reference implementation of the core semantic pipeline. That improvement is real and verifiable: I re-derived it from counts, probes and a clean test run rather than from the work log. It is not yet a finished book companion, because the work is uncommitted, the live-system paths are unverified, one realistic denial-of-service remains, and half the code is an advanced layer that was fenced off rather than re-engineered. Fixing the eight items in section 5.6 would move book readiness toward 8 and production readiness to about 5.5; going beyond that is a different project.

---

## 7. Addendum: remediation of the HIGH findings (P12)

Findings F1, F2 and F4 were addressed after this audit; F3 (nothing committed, CI never run) was not, and is not something a code change can fix.

| Finding | Status | What changed | Evidence |
|---|---|---|---|
| F1 SPARQL has no timeout | **Fixed and tested** | Queries run in killable worker processes; the limit (`SPARQL_QUERY_TIMEOUT_SECONDS`, default 15, never unlimited) terminates the process. The old thread-based "timeout" is removed; the natural-language path now uses the same bounded execution. F5 (re-parse per call) is fixed as a side effect: each worker keeps the parsed graph | `tests/test_sparql_timeout.py` (30 tests, real processes); the audit's four-way cartesian `COUNT(*)` now returns 504 at the limit |
| F2 Compose defaults to open admin | **Fixed and tested (statically)** | Compose is production-mode with literal `ENVIRONMENT`/`ALLOW_OPEN_DEVELOPMENT_MODE`, loopback-bound ports, and an explicit `docker_compose.dev.yaml` for open local work. One policy module decides; open mode needs credentials absent + non-production + explicit opt-in | `tests/test_security_policy.py` (exhaustive matrix), `tests/test_deployment_hardening.py`, `docs/security-policy.md`. **No container was started** |
| F4 Kubernetes manifest | **Fixed and tested (statically)** | Pinned version tag, tracing off, non-root, no privilege escalation, read-only root filesystem, capabilities dropped, resources, no Secret object | `tests/test_deployment_hardening.py`. **No cluster was used** |

Revised scores are deliberately not re-issued here: the independent re-audit above stands, and these fixes address three of its findings. They would move Security from 6.0 toward 7.0 and Production readiness from 4.0 toward 5.0 once the work is committed and the Docker and Kubernetes paths are exercised for real.

---

## 8. Addendum: semantic quality review (P14)

A correction first. **F9 was wrong in part.** It said encounter ordering was "enforced only by the data contract" and that SHACL had no temporal rules. `shapes/clinical_shapes.ttl` already carried `sh:lessThanOrEquals hc:encounterEnd` on `encounterStart` (with a passing and a failing test). The audit counted `sh:lessThan` and missed `sh:lessThanOrEquals`. What was true: no other temporal rule exists, and the rule had no tests for time zones, zero-length encounters or the real sample data. The review added those (`tests/test_semantic_review.py`) and documents the OWL / SHACL / data-contract split in `docs/ontology-engineering.md`, section 18.

| Audit item | Outcome |
|---|---|
| Inverses (42 of 75 without one) | Every object property is classified A to D in `ontology/inverse_decisions.csv`. 11 inverse pairs were added (27 pairs in total); 32 properties deliberately keep none, each with a reason (14 B, 13 C, 5 D). Tested, including reasoner inference and the projection |
| Person / Patient / Doctor / Nurse as subclasses | Defended and documented: overlapping role types, no `PractitionerRole`. Tested with a doctor who is also a patient (SHACL passes, reasoner consistent) |
| Vacuous assertion (`or True`) and others | All fixed with real assertions; a guard test (`test_the_suite_contains_no_vacuous_assertions`) scans every test and itself caught one new offender during this work |
| Closed shapes | Two (`CodeConceptShape`, `IdentifierShape`) are closed; entity shapes stay open; tested both ways |
