# The reader journey

This repository is a reference implementation for a book on healthcare ontologies and knowledge graphs. It is organised the way the book teaches: from the questions a hospital needs answered, up through a validated knowledge graph and its API, and only then to the optional AI layer.

The fourteen steps below use the project's **actual structure**. There are no `01-domain/` ... `14-agentic-ai/` directories, because the files that teach each idea also have to *work together*, and splitting them by chapter would break the one pipeline that connects them. Instead each step names where its material lives, what to run, and what to expect. The same information as a table, with exercises, is in [book-chapter-mapping.md](book-chapter-mapping.md).

```text
 Part I  Foundations        01 domain -> 02 vocabulary -> 03 taxonomy -> 04 ontology
 Part II Semantics          05 RDF -> 06 OWL -> 07 SHACL -> 08 SPARQL
 Part III The graph         09 knowledge graph -> 10 validation -> 11 API -> 12 interoperability
 ------------------------------------------------------------- everything above works with no LLM
 Part IV Advanced (opt.)    13 RAG -> 14 agentic AI
```

How to read each step: **WHY** is the reason the idea exists, **WHAT** is the thing itself, **HOW** is where to see it in this repository, **TRADE-OFFS** is what it costs, and **COMMON MISTAKES** are the ones this project actually made or avoided. The anti-patterns in [anti-patterns.md](anti-patterns.md) go deeper on eight of them.

Before you start: `python scripts/dev.py quickstart` sets up, checks, validates and tests the project with no Docker and no API keys. If anything fails, [troubleshooting.md](troubleshooting.md).

---

## 01 Domain

**WHY.** A model nobody can test against a requirement cannot be wrong, and so cannot be right. Start from what the hospital must be able to *ask*.
**WHAT.** A bounded domain (people, organisation, encounters, conditions, observations, medication, terminology) and 21 competency questions.
**HOW.** [competency-questions.md](competency-questions.md) (the chain from business question to test); scope and limits in [ontology-engineering.md](ontology-engineering.md) section 12.
**TRADE-OFFS.** A small, bounded scope is teachable and testable; it is not a clinical system and says so.
**COMMON MISTAKES.** Modelling everything you can think of; starting from classes instead of questions; asking a question the model cannot support (CQ18 deliberately stops at co-occurrence, because the ontology has no "indicates" relation).

## 02 Vocabulary

**WHY.** "Male", "male" and "M" are three values to a computer. Free text cannot be queried or validated.
**WHAT.** Controlled vocabularies as SKOS concepts (gender, encounter type, specialty, medication category), plus the `CodeConcept` pattern that *refers to* ICD-10, SNOMED CT, LOINC and RxNorm without copying them.
**HOW.** `services/reference_vocab.py` (one definition, shared by generator and checker); [ontology-engineering.md](ontology-engineering.md) sections 7 and 8.
**TRADE-OFFS.** A vocabulary concept is one more node than a string; it buys synonyms, labels and validation.
**COMMON MISTAKES.** Copying a licensed terminology into your ontology; storing a code without its system; treating a display name as a code.

## 03 Taxonomy

**WHY.** A class hierarchy lets one question cover many things: "all people" without listing doctors, nurses and patients.
**WHAT.** `subClassOf` hierarchies (`Doctor` -> `Practitioner` -> `Person`; `Diagnosis` -> `Condition`) and **defined classes** whose members a reasoner derives (`AntidiabeticMedication`).
**HOW.** The `CLASSES` table in `scripts/generate_hc_ontology.py`; competency questions 14 and 21.
**TRADE-OFFS.** Deep hierarchies are expensive to keep right; keep only distinctions that change an answer.
**COMMON MISTAKES.** Using subclasses for things that are *data* (a medication's category), which was the original defect.

## 04 Ontology

**WHY.** The ontology fixes what exists and how things relate before any data arrives.
**WHAT.** 56 classes, 86 object properties (27 inverse pairs), 74 data properties, with labels, comments, domains and ranges, inverse pairs and functional properties.
**HOW.** `scripts/generate_hc_ontology.py` generates the schema, `ontology/healthcare_schema.ttl`; a test fails if the committed file and the generator disagree. The schema holds the model and the vocabularies, never a patient ([schema-and-sample-data.md](schema-and-sample-data.md)). Design decisions: [ontology-engineering.md](ontology-engineering.md); the lifecycle is diagram 2 in [architecture-diagrams.md](architecture-diagrams.md).
**TRADE-OFFS.** Generating the file from code makes review easy and hand-editing impossible. That is intended.
**COMMON MISTAKES.** Treating the ontology as a database schema; hand-editing generated output; leaving classes without labels.

## 05 RDF

**WHY.** RDF is a universal, tool-neutral way to state facts: subject, predicate, object, with global names.
**WHAT.** The schema (1,422 triples) and the sample data (593 triples, 94 individuals) are RDF graphs; together they form the 2,015-triple dataset every tool reads. Individuals have IRIs, typed literals and links to other IRIs.
**HOW.** [sample-data-and-semantic-mapping.md](sample-data-and-semantic-mapping.md) walks `data/source/patients.csv` to `PatientJohn`; `data/sample_instances/*.ttl` are small Turtle examples.
**TRADE-OFFS.** Verbose, and plain and typed literals are different terms. Worth it for interchange.
**COMMON MISTAKES.** Strings for dates; names as identity; comparing literals without their datatype.

## 06 OWL

**WHY.** Some facts follow from others; a reasoner can find them and can find contradictions.
**WHAT.** Property characteristics (inverse, transitive, functional), disjointness, defined classes, and what OWL does **not** do: validate required data.
**HOW.** `tests/test_ontology.py` (the reasoner group needs Java and checks consistency, that Metformin is classified as antidiabetic, that inpatient encounters are inferred, and that inverse edges appear); `tests/reasoning.py`.
**TRADE-OFFS.** Reasoning adds power and a runtime dependency; the project keeps it optional.
**COMMON MISTAKES.** Using cardinality restrictions as validation (open-world); declaring roles disjoint when one person can hold both.

## 07 SHACL

**WHY.** Real data must be checked for completeness and shape; the open world will never reject anything.
**WHAT.** Shapes with severities (Violation, Warning, Info) for patient, doctor, diagnosis, encounter, observation, medication and the allergy safety rule.
**HOW.** `shapes/`, `core/shacl_validator.py`; valid and invalid fixtures in `data/sample_instances/`; mutation-style tests in `tests/test_shape_contracts.py`. Diagram 4.
**TRADE-OFFS.** A second language to learn; it states rules where OWL cannot.
**COMMON MISTAKES.** Letting the validator infer types (anti-pattern 5); weakening a shape to make sample data pass instead of fixing the data.

## 08 SPARQL

**WHY.** A query is a testable statement of a question.
**WHAT.** 21 queries (`SELECT`, `ASK`, `CONSTRUCT`, aggregation, negation, property paths), each with a hand-written expected answer.
**HOW.** `sparql/*.rq`, `sparql/catalog.json`, `tests/test_sparql_competency.py`; the API runs `SELECT` only.
**TRADE-OFFS.** Querying the RDF directly shows the model's meaning; the projection is faster for traversal but is derived.
**COMMON MISTAKES.** Believing an empty answer without showing the query can return something; forgetting the hierarchy (CQ14, CQ21).

## 09 Knowledge graph

**WHY.** Data becomes a *knowledge* graph when it is connected, typed and checkable.
**WHAT.** CSV -> data contract -> RDF -> SHACL gate -> authoritative file -> derived Neo4j projection.
**HOW.** [semantic-authority-and-graph-projection.md](semantic-authority-and-graph-projection.md); `services/graph_projection.py`; diagrams 1, 3 and 6. `python scripts/validate.py` step 4 plans the projection with no database. The reference run against a real database is [neo4j-desktop.md](neo4j-desktop.md) (`python scripts/dev.py doctor --neo4j`, `load`, `verify-neo4j --projection`).
**TRADE-OFFS.** Two stores (RDF and Neo4j) means one must be the authority; here it is RDF, and Neo4j is rebuildable.
**COMMON MISTAKES.** Editing the property graph by hand; exporting only the first type of each node (anti-pattern 6).

## 10 Validation

**WHY.** Invalid data should fail early, where the error is cheapest to explain.
**WHAT.** Layered gates: the **data contract** on the source rows, **SHACL** on the RDF, the **projection gate** before Neo4j, and a test pyramid over all of it.
**HOW.** `services/sample_data.py`, 50 broken tables in `data/invalid_source/`, `scripts/validate.py`, [testing-strategy.md](testing-strategy.md).
**TRADE-OFFS.** Overlapping gates cost a little duplication and buy defence in depth (`test_shacl_gate_catches_what_the_contract_missed`).
**COMMON MISTAKES.** Loading first and hoping a downstream system complains; a check no fixture has ever failed.

## 11 API

**WHY.** Other systems and people need the same capabilities over a stable boundary.
**WHAT.** A FastAPI service: ontology, patients, SPARQL, SHACL, projection; authentication, authorization and tenant scoping from a server-side credential; read-only query execution.
**HOW.** `api.py`, `routers/`, `core/security.py`, `core/authz.py`, `examples/requests.http`, [security-architecture.md](security-architecture.md).
**TRADE-OFFS.** API keys are a floor, not OIDC; the clinical graph is shared across tenants.
**COMMON MISTAKES.** Trusting a role header (anti-pattern 7); exposing a destructive endpoint (anti-pattern 8).

## 12 Interoperability

**WHY.** Healthcare data crosses systems; a model that cannot map to the standards is an island.
**WHAT.** Standards-shaped modelling: code binding by system + value + display, standard identifiers (system + value + type), check-digit validation of SNOMED CT and LOINC, RDF interchange. The classes mirror FHIR's (Encounter, Condition, Observation, Medication).
**HOW.** `CodeConcept` in the generator; `data/source/codes.csv`; diagram 7. CQ04 finds the same patients by ICD-10 or SNOMED.
**TRADE-OFFS.** Aligning to the standards costs some purity.
**COMMON MISTAKES.** Claiming FHIR conformance this project does not have: **there is no FHIR/HL7 mapper here**. Building one is exercise 12b.

## 13 RAG

**WHY.** A language model that writes queries must be told which terms exist.
**WHAT.** Hybrid retrieval of *ontology concepts* (lexical, graph and vector channels), reranking, query generation, validation, read-only execution and provenance.
**HOW.** `enterprise/hybrid_retrieval.py`, `enterprise/retrieval_pipeline.py`; [core-vs-ai-architecture.md](core-vs-ai-architecture.md) section 6; diagram 8. Optional.
**TRADE-OFFS.** More moving parts and an API key; the lexical channel works with neither.
**COMMON MISTAKES.** Retrieving prose and calling it grounded; letting generated queries run without the same validator the public API uses.

## 14 Agentic AI

**WHY.** Multi-step questions need planning, retries and a person in the loop for risky operations.
**WHAT.** A LangGraph state machine with four memories, a human approval gate and **abstention**: the system declines when it has no evidence.
**HOW.** `agents/`, `enterprise/abstention.py`, [core-vs-ai-architecture.md](core-vs-ai-architecture.md) sections 5, 7 and 8; diagram 9. Optional.
**TRADE-OFFS.** Autonomy is limited on purpose; refusing is cheaper than being fluently wrong.
**COMMON MISTAKES.** Letting the agent bypass the validators; turning an empty result into a confident "no".
