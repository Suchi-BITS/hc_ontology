# Book Reference Gap Analysis

**Repository:** `hc_ontology/`
**Companion to:** [PROJECT_ARCHITECTURE_AND_BOOK_READINESS_AUDIT.md](PROJECT_ARCHITECTURE_AND_BOOK_READINESS_AUDIT.md)
**Audit date:** 2026-10-08
**Scope:** What a Packt book on healthcare ontology engineering and knowledge graphs needs, what this repository provides, what is missing, and what to build. This document does not repeat the full audit. Section references like "Audit §8" point to the main report.

**Caveat:** Tests, the reasoner, Neo4j and the LLM were not run (no Python interpreter was available). Statements about agent, memory and embedding internals come from the project's design doc where marked *(doc-stated)*.

---

## 1. What the book needs

The book teaches a progression: domain → vocabulary → metadata → taxonomy → ontology → RDF → OWL → SHACL → SPARQL → KG construction → graph querying → validation → APIs → visualization → production → interoperability → RAG → agents.

For a companion repository to *reinforce* that book, each chapter needs five things:

1. **A runnable artifact** (file or script) that a reader can open and change.
2. **A known-good state and a known-bad state** (so the reader sees what validation or reasoning catches).
3. **A test** that proves the artifact does what the chapter says.
4. **One command** that reproduces it from a fresh clone.
5. **A deliberate, explained simplification** (so the reader knows what the book leaves out).

Measured against those five needs, the repository supplies the artifact (sometimes) and little of the rest.

---

## 2. What the repository currently provides

| Provided | Evidence | Quality for book use |
|---|---|---|
| A hospital OWL ontology (75 classes, 52 object properties, 76 datatype properties, 65 individuals) | `healthcare_ontology.owl` | Usable as a *starting point*. Shallow (Audit §5). |
| A generator script for the ontology | `scripts/generate_hc_ontology.py` (1,568 lines) | Useful for teaching Owlready2, but the OWL file is also edited by `seed_demo_data.py`, so the "source of truth" is unclear. |
| SHACL shapes, validator wrapper, HTML report | `shapes/*`, `core/shacl_*` | **Best chapter material in the repo** (Audit §8). |
| One cross-entity business rule as `sh:sparql` | `shapes/medication_shapes.ttl` | Excellent teaching artifact with a failing fixture. |
| Positive/negative RDF fixtures | `data/sample_instances/*.ttl` (4 files) | Good pattern; too few. |
| Staged query validation (safety → syntax → schema → limit) | `core/query_validator.py`, `sparql_validator.py`, `cypher_validator.py` | Clean pattern; the Cypher implementation has bypasses (Audit §12, §15). |
| REST API over the ontology | `routers/*` | Prototype quality. |
| NL→SPARQL / NL→Cypher generators with a repair loop | `services/sparql_generator.py`, `cypher_generator.py` | Reasonable AI-chapter material. |
| OWL→Neo4j exporter | `services/neo4j_exporter.py` | Lossy; a good *anti-example*, not a model to copy. |
| Embeddings, hybrid retrieval, GraphRAG ingestion *(doc-stated internals)* | `services/embedding_service.py`, `enterprise/hybrid_retrieval.py`, `services/document_ingestor.py` | Present; not anchored to a validated graph. |
| LangGraph agent with HITL, abstention, provenance, four-part memory *(doc-stated internals)* | `agents/*`, `enterprise/*` | Large and interesting; far from the book's core. |
| Docker, compose, K8s, CI/CD | `Dockerfile`, `docker_compose.yaml`, `k8s/`, `.github/` | Present; not reproducible or safe as shipped (Audit §17). |
| About 83 tests | `tests/` | SHACL/validators/memory covered; ontology, graph and SPARQL not (Audit §14). |
| Course scripts | `docs/UDEMY_*`, `YOUTUBE_*`, `COURSE_*.md` | Video-oriented; reusable as raw narrative, not as book text. |

---

## 3. Gap matrix by chapter

Status key: **Strong** / **Partial** / **Weak** / **Missing**.

| # | Chapter topic | Status | What exists | What is missing | What to implement |
|---|---|---|---|---|---|
| 1 | Healthcare domain & scope | Weak | Class list implies scope | Domain narrative, personas, competency questions, scope statement, glossary | `ontology/competency-questions.md` with 15–25 CQs; scope and non-goals page |
| 2 | Vocabulary | **Missing** | — | Any controlled vocabulary or glossary | SKOS `ConceptScheme`s for gender, blood group, encounter class, appointment/treatment status, allergy severity |
| 3 | Metadata | **Missing** | 12 `rdfs:label`/`comment` | Annotation policy, definitions, provenance of terms, versioning metadata | Annotation guidelines; `skos:definition`, `dcterms:source`, `owl:versionInfo`; ontology header |
| 4 | Taxonomy | Weak | Subclass tree (mixes role/specialty/regulatory status) | Taxonomy design rules; a refactor example | A before/after taxonomy refactor ("Cardiologist as class" → "Doctor + Specialty") |
| 5 | Ontology | Partial | OWL with qualified cardinality and disjointness | Inverses, property hierarchy, defined classes, typed dates, Encounter/Condition/Observation, annotations | Rebuilt TBox in Turtle (Audit R-03) |
| 6 | RDF | Partial | RDF/XML; typed literals; hash namespace | Turtle authoring, IRI strategy, TBox/ABox split, named graphs | Turtle files; separate schema vs instance namespaces; short RDF primer tied to real triples |
| 7 | OWL & reasoning | Weak | Constructs only | Any reasoner run; open-world vs closed-world demonstration | Reasoner step (OWL-RL or ELK/HermiT), consistency test, "inferred vs asserted" demo |
| 8 | SHACL | **Strong** (relative) | Shapes, SPARQL constraint, fixtures, tests, HTML report | Closed shapes, `maxCount`, `in`, date logic, drug-class rule, CI gate, ontology-quality shapes | Rework and extend (Audit §8.3) |
| 9 | SPARQL | Weak | Free-form endpoint; LLM generator | Query library, expected results, ASK/CONSTRUCT/aggregate/path examples, parameterization | `sparql/*.rq` plus `expected/*.json` plus pytest runner |
| 10 | KG construction | **Missing** | Hand-authored individuals; seed script that edits OWL | Source data, mapping, entity resolution, provenance, repeatable load | Synthetic CSV cohort → deterministic mapping → Turtle → SHACL gate |
| 11 | Graph querying | Partial | SPARQL, Cypher, SPARQL→Cypher subset | Property-path and traversal examples; RDF vs LPG comparison | Paired SPARQL/Cypher query set for the same CQs |
| 12 | Graph validation | Partial | SHACL on demand | Pipeline gate; Neo4j-side checks; ontology consistency check | Three-gate validation (ontology, instances, CQ regression) wired into CI and load |
| 13 | APIs | Partial | FastAPI routers | AuthN/Z, pagination, versioning, ID-based paths, safe error handling | Slim read-only API; auth chapter exercise |
| 14 | Visualization | Weak *(Streamlit not examined in depth)* | Streamlit demo | Graph/ontology visualization (class tree, instance neighborhood, SHACL report view) | Notebook or small viewer; generated class-hierarchy and instance diagrams |
| 15 | Production architecture | Weak | Compose, K8s, CI/CD | Secrets handling, `.dockerignore`, non-root, TLS, pinned deps, externalized state, scanning | Fix deployment basics; state limitations honestly |
| 16 | Semantic interoperability | **Missing** | — | Code-system binding, terminology mapping, FHIR mapping | ICD-10 binding + SKOS mapping; one FHIR resource mapped (Observation or Patient) |
| 17 | RAG / AI integration | Partial | Embeddings, hybrid retrieval, GraphRAG *(doc-stated)* | Grounding on a validated, reasoned graph; evaluation against CQs | Rebase retrieval on the validated graph; CQ-based eval set |
| 18 | Agentic AI | Partial (large) | LangGraph, HITL, abstention, provenance, memory *(doc-stated)* | Tie to ontology semantics; trim scope; evaluation | Reduce to a minimal governed agent (plan → generate → validate → approve → execute → cite) |

---

## 4. Missing items that block the book

These are the gaps without which the repository cannot honestly accompany the book. Implementation order matters: each depends on the previous.

| Order | Missing item | Why it blocks | Effort |
|---|---|---|---|
| 1 | Repo hygiene (untrack `venv/`, add `.env.example`, `.dockerignore`, fix README paths and the Ollama-vs-OpenAI claim) | Readers cannot clone and run (Audit §17) | S |
| 2 | Competency questions | Nothing else can be evaluated without them | S |
| 3 | Rebuilt ontology (Turtle, inverses, typed dates, SKOS schemes, Encounter/Observation, annotations) | It is the book's central artifact | L |
| 4 | Synthetic source data and a deterministic mapping | Chapters 10, 12, 16 have nothing to build on | M |
| 5 | SHACL gate wired into load and CI | Validation must be shown as a pipeline stage | S |
| 6 | SPARQL library with expected results | Chapter 9 and the regression suite | M |
| 7 | Reasoning step | Chapter 7; also fixes SPARQL/SHACL behavior on subclasses | M |
| 8 | Lossless RDF→Neo4j projection with tests | Chapters 11 and 17 depend on a faithful graph | M |
| 9 | Security fixes (identity, destructive routes, read-only Cypher, `SERVICE` blocking) | Cannot publish code with an open wipe endpoint and spoofable roles | M |
| 10 | Ontology/graph/SPARQL/auth tests | The repo should demonstrate that its claims hold | M |

---

## 5. What needs to be implemented, by area

### 5.1 Ontology (Audit R-03, R-11, R-15)
- Rebuild the TBox as Turtle. Separate it from instance data.
- Add `owl:inverseOf` for the paired properties (`hasDiagnosis`/`diagnosisForPatient`, `hasAppointment`/`appointmentForPatient`, `hasPrescription`/`prescribedFor`, `hasDepartment`/`belongsToHospital`).
- Type dates as `xsd:date` / `xsd:dateTime`. Make single-valued attributes functional.
- Replace role/specialty subclasses (`Cardiologist`, `CardiologyDepartment`) with properties pointing to a `Specialty` scheme.
- Introduce `Encounter` (class, period, location, participants), `Condition`, and a value-bearing `Observation` (value, unit, effective time, status).
- Introduce `Identifier` and `Coding` patterns.
- Add labels and definitions to every class and property; ontology header with version, license, creator.
- Fix the Metformin/insulin typing and add a small drug-class model for the allergy examples.

### 5.2 Data and graph construction (R-05, R-08)
- A 10–20 patient synthetic dataset with deliberate defects: duplicate patient, conflicting allergy, missing code, overlapping encounters, out-of-range vital.
- A documented mapping from source rows to RDF, run as one command, producing the same output every time.
- A simple entity-resolution step (block on name + DOB, merge with `owl:sameAs` or canonical IRI).
- PROV-O on imported facts.
- A projection to Neo4j that keeps the class hierarchy (multiple labels or `:SUBCLASS_OF`), uses uniqueness constraints on an IRI/ID property, batches with `UNWIND`, and has a round-trip count test.
- Keep agent memory, embeddings and documents in a separate Neo4j database from the clinical projection.

### 5.3 Validation (R-07)
- Rework the shapes: one declaration per path, `sh:maxCount`, `sh:in` against SKOS schemes, date range and ordering, `sh:closed` on core classes.
- Extend the allergy rule from drug to drug class.
- Add "ontology quality" shapes (every class has a label and definition; every property has domain and range).
- Run shapes automatically before load and in CI against the real data. Make the rule for the sample data explicit (the current `PatientJohn` fails `PatientShape`).
- Document the data-graph requirement for subclass targeting (Audit S-5).

### 5.4 SPARQL (R-04, R-06)
- One `.rq` file per competency question with an expected-result file and a pytest runner.
- Cover: SELECT with joins, `OPTIONAL`, `FILTER NOT EXISTS`, aggregates and `GROUP BY`, property paths (`reportsTo*`, containment chain), `ASK`, `CONSTRUCT`, a subquery, and a parameterized query using `initBindings`.
- Execute against one in-memory graph (not a re-parse per call). Show results with and without inference.

### 5.5 API and security (R-02, R-09, R-17)
- Verified identity (even a teaching-grade key→role table); no role from client headers.
- Remove `POST /neo4j/seed-demo` and the whole-database wipe from the API; provide a guarded CLI instead.
- Cypher: allow-list or parser-based gate, `READ_ACCESS` sessions, block `CALL apoc.*`, subqueries and admin commands. SPARQL: block `SERVICE` and `FROM`/`FROM NAMED`.
- Remove the client-supplied `owl_path` from `/validate/ontology`.
- Pagination, versioned paths, ID-based resource paths, redacted error messages.

### 5.6 DevOps and reproducibility (R-01, R-14)
- `pyproject.toml` with locked dependencies; split runtime and dev dependencies.
- `.env.example`, `.dockerignore`, non-root container user, no bind mount outside a dev profile.
- One command (`make demo` or `docker compose up`) that starts Neo4j with a pre-created database, loads data, validates, and serves the API.
- CI: lint/format, mypy (gating), pytest, SHACL gate, `pip-audit`, container scan, coverage.

### 5.7 AI chapters (R-18)
- Move agent, memory and enterprise code behind an optional install extra so chapters 1–12 install without LangChain/OpenAI.
- Retrieval grounded on the validated graph. Answers return provenance (the SPARQL/Cypher used and the triples that supported the answer).
- Evaluate with a question set derived from the competency questions.
- State plainly that sending patient-like text to a hosted LLM or to LangSmith is a compliance matter, and default tracing to off.

---

## 6. What can become chapter material

| Material in the repo | Becomes |
|---|---|
| `shapes/medication_shapes.ttl` + `invalid_prescription_allergy.ttl` + its test | SHACL chapter centerpiece: "A rule OWL cannot express" |
| OWL-vs-SHACL table in `readme.md` | Opening section of the SHACL chapter; a decision table for the whole book |
| `core/query_validator.py` and the two validators | "Safe query generation" chapter (the pattern, plus the hardening exercise) |
| `healthcare_ontology.owl` hierarchy problems (specialty as subclass, mistyped drugs) | Taxonomy-to-ontology refactoring chapter, with before/after |
| `services/neo4j_exporter.py` | "What a lossy projection looks like" boxed example, then the corrected projection |
| `scripts/generate_hc_ontology.py` | Owlready2 sidebar: programmatic ontology authoring vs authoring in Turtle/Protégé |
| `services/sparql_generator.py` / `cypher_generator.py` repair loop | NL→query chapter within the AI section |
| `enterprise/abstention.py`, `provenance.py`, `agent human_gate` *(doc-stated)* | "Governed AI over a knowledge graph" chapter |
| `graph_schema_design.md` | Reference for the property-graph chapter, once rewritten around the projection |

---

## 7. What can become hands-on exercises

1. Write competency questions; map each to a `.rq` and an expected result.
2. Refactor `Cardiologist ⊑ Doctor` to `Doctor` + `Specialty`; update queries and shapes.
3. Add inverse properties; show one assertion yielding both directions under a reasoner.
4. Convert string dates to `xsd:date`; write the SHACL date rules.
5. Validate an uploaded file with a `Cardiologist` individual, with and without the TBox; explain the difference.
6. Extend the allergy rule from drug to drug class.
7. Map a CSV with two duplicate patients to RDF; implement entity resolution.
8. Project to Neo4j; compare a traversal query in SPARQL and Cypher.
9. Attempt to bypass the Cypher validator with `CALL apoc...`; harden it.
10. Map one FHIR Observation to the ontology and validate it.
11. Add PROV-O to imported facts; query "which source asserted this?".
12. Break the system on purpose: call the seed endpoint (in a throwaway database) and observe the damage; then run the guarded CLI.

---

## 8. What can become case studies

| Case study | Teaches |
|---|---|
| Prescription–allergy safety rule | Open-world OWL vs closed-world SHACL; cross-entity constraints; why exact-match allergy checks miss drug classes |
| "Is a Cardiologist a class or a property?" | Role vs type; subclass explosion; impact on queries and shapes |
| `PatientJohn` fails his own shape | Why sample data needs validation, and why test assertions must be specific (`>= 0` can never fail) |
| The wipe endpoint | How a convenience route in a demo becomes a data-loss path; least privilege |
| Lossy export | What a property graph loses from an ontology, with a before/after on one query |
| Name as identity (`PatientJohn`, alias list in `healthcare_term_aliases.json`) | Why identifiers matter; identity resolution; privacy |

---

## 9. What can become diagrams

See Audit §28 for the twelve diagrams and what each must communicate. Highest value first: the six-part target pipeline, the OWL-vs-SHACL decision diagram (open-world vs closed-world), the RDF-vs-property-graph comparison on one patient, and the validated-graph-grounded AI architecture.

---

## 10. What should become advanced / enterprise sections

Keep these, but out of the core path and clearly labeled as optional:

| Topic | Source in repo | Condition for including |
|---|---|---|
| Multi-tenancy | `enterprise/tenancy.py` | Only if tenants have real ontology packs and isolated graphs; today they are names in a dictionary |
| RBAC | `enterprise/rbac.py` | After identity is real; otherwise it teaches an insecure pattern |
| Guardrails | `enterprise/guardrails.py` | As defence in depth; state clearly that regexes are not a security boundary |
| Cost tracking, workflows, monitoring | `enterprise/cost.py`, `workflows.py`, `monitoring.py` | Appendix; not tied to the semantic core |
| Memory subsystem (working/episodic/procedural/semantic/meta) | `agents/memory/*` | Advanced agent chapter; trim to what the examples use |
| Kubernetes, HPA, Ingress | `k8s/deployment.yaml` | Only after state is externalized and secrets are handled |
| LangSmith/OTEL | `enterprise/observability.py` | Off by default; note data-handling implications |

**Omit** from the book, as unnecessary scope: full SNOMED CT import, OMOP ETL, a full FHIR server, a hyperscale triplestore comparison, and any vector database beyond the Neo4j vector index already in place.

---

## 11. Suggested delivery sequence

| Phase | Deliverable | Unlocks chapters |
|---|---|---|
| A (≈1 week) | Repo hygiene, security fixes, docs sweep, `.env.example`, one-command start | All (readers can run it) |
| B (≈2 weeks) | Competency questions, rebuilt TBox, SKOS schemes, header and annotations | 1–5 |
| C (≈2 weeks) | Synthetic data, mapping, SHACL rework and gate, SPARQL library, reasoning step | 6–10 |
| D (≈1–2 weeks) | RDF→Neo4j projection, separate memory database, query-safety hardening, tests | 11–13 |
| E (≈1–2 weeks) | Terminology binding, FHIR sample, provenance | 16 |
| F (≈2 weeks) | Re-base RAG and agent on the validated graph; trim and move to an optional extra | 17–18 |

These estimates assume one engineer working part-time on a codebase they already know; adjust for your schedule.

---

## 12. Bottom line

The repository has real breadth (API, graph database, RAG, agent) and one genuinely good teaching asset (the SHACL allergy rule). The book needs the opposite weighting: a rigorous, tested semantic spine, with the AI layers resting on top of it. The shortest path is not a rewrite. It is to (1) make the repo cloneable and safe, (2) build the ontology → data → SHACL → SPARQL spine with tests, (3) project to Neo4j faithfully, and (4) re-anchor the existing RAG and agent code to that validated graph.
