# Neo4j Desktop live verification

**Date:** 2026-10-08
**Verdict: PASS WITH LIMITATIONS** (section 12)

This report records a verification of the RDF → SHACL → Neo4j projection against a **real Neo4j Desktop database running on the verifier's machine**. Everything below was observed by running the commands in section 11 against that database. Where something was not exercised, it says so. The password is never shown.

## 1. Environment

| | |
|---|---|
| OS | Windows 11 Pro, 10.0.26200 |
| Python | 3.11.8 (shared virtual environment, not the project's own `venv/`) |
| Neo4j Python driver | 6.2.0 |
| Neo4j server | **5.20.0, enterprise edition** (Neo4j Desktop's development build; the Desktop application's own version was not queried) |
| Server address | 127.0.0.1:7687, protocol 5.4 |
| Databases present | `system`, `neo4j` (default), `hcontology`, all online |
| Database used for the verification | **`neo4j`** (empty before the load). See section 3 for why not `hcontology` |

## 2. Connection

| | |
|---|---|
| Configured URI (no credentials) | `bolt://localhost:7687` |
| User | `neo4j` |
| Configuration mechanism | the project's own `core/config.py` (`NEO4J_URI`, `NEO4J_USERNAME` or alias `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`), read from the git-ignored `.env`; the database was selected for these commands by the `NEO4J_DATABASE` environment variable only, and `.env` was **not** edited |
| `RETURN 1 AS ok` | `1` |
| Result | **Connected.** `verify_connectivity()` succeeded; `SHOW DATABASES` and `CALL dbms.components()` returned as expected |

## 3. What was already in the user's Neo4j, and what was left alone

The configured database (`NEO4J_DATABASE=hcontology`) was **not empty**. A read-only inspection found 124 nodes and 145 relationships:

- 65 nodes written by an **older exporter** (name-keyed, no `iri`; labels such as `Patient`, `Neurologist`, `Surgeon`, `Physician`, `Analgesic` on four nodes, `LabResult`), i.e. exactly the defects the redesign fixed;
- 59 nodes of **agent memory** (`AgentEvent` 54, `AgentTurn` 3, `AgentSession` 2), real usage, and a vector index and constraints belonging to the agent layer.

Loading the new projection there would have placed two different representations of the same patients side by side. So:

- **`hcontology` was not modified.** Before and after this work it holds 124 nodes, 145 relationships and 0 `Resource` nodes (checked again at the end).
- The verification ran in the **empty `neo4j` database** that the same Neo4j Desktop DBMS already had. No database was created, no Docker container started, no existing setup changed.
- The exporter now **refuses to load into a database that holds nodes outside the project's graph domains** (`ForeignDataPresent`), and the guard was exercised live: pointed at `hcontology` it reports `65` foreign nodes and the live test suite skips instead of writing. This is a correction made because of this verification (section 10).

## 4. Projection

Loaded with `python scripts/dev.py load` into `neo4j`: *124 nodes, 58 classes, 476 relationships*.

| | Count |
|---|---|
| Total nodes | **183** (124 `Resource` + 58 `OntologyClass` + 1 `ProjectionMeta`) |
| Total relationships | **476** |
| Graph domains | projection = 183; agent memory, documents, semantic index, other = 0 |

Labels (top): `Resource` 124, `OntologyClass` 58, `Concept` 26, `CodeConcept` 12, `Location` 11, `Person` 11, `Specialty` 11, `Organization` 8, `Department` 7, `MedicationCategory` 7, `Encounter` 6, `Medication` 6, `Practitioner` 6, `Condition` 5, `Diagnosis` 5, `Identifier` 5, `MedicalRecord` 5, **`Patient` 5**, `Prescription` 5, `Doctor` 4, `Observation` 4, `Nurse` 2, `Allergy` 1, `Hospital` 1, `ProjectionMeta` 1.

Relationship types (top): `INSTANCE_OF` 124, `SUBCLASS_OF` 31, `INSCHEME` 26, `HASCODE` 15, `ADMINISTRATIVEGENDER` 11, `HASSPECIALTY` 10, `HASPARTICIPANT` 9, `PARTICIPATESIN` 9, `PARTOFLOCATION` 8, … 78 types in all, e.g. `HASDIAGNOSIS` 5, `PRESCRIBEDFOR` 5, `HASALLERGY` 1, `ALLERGYFORPATIENT` 1. Of the 321 non-structural relationships, 208 are asserted and 113 are inferred inverses or super-properties (marked `inferred: true`).

Core entities, as the projection represents them (the labels are the ontology's classes, with superclasses): Patient 5, Practitioner 6 (Doctor 4, Nurse 2), Organization 8 (Hospital 1, Department 7), Location 11 (Ward, Room, Bed), Encounter 6, Condition 5 (Diagnosis), Observation 4, Medication 6, Prescription 5, Allergy 1.

**Automated comparison with the RDF** (`python scripts/dev.py verify-neo4j --projection`): nodes 124/124, classes 58/58, relationships 476/476, **label mismatches 0, property mismatches 0**, `ProjectionMeta.fingerprint` equals the RDF projection's (`83f2c99b…`). Loading a second time changed nothing (identical counts and fingerprint).

## 5. Identity

| | |
|---|---|
| Identity key | the **`iri` property**, with a `UNIQUENESS` constraint on `(:Resource {iri})`, `(:OntologyClass {iri})` and `(:ProjectionMeta {id})` |
| Source IRI | the RDF individual's IRI, e.g. `http://example.org/healthcare-hospital.owl#PatientJohn` |
| Display name | the separate `name` property (`PatientJohn`); never a key |
| Duplicates | none: no `iri` appears twice, no `Resource` lacks an `iri`, no two nodes share a `name` |
| Same display name, different entities | `DiagnosisDiabetesAlice` and `DiagnosisDiabetesBob` both read "Diabetes" and remain **two nodes** |

## 6. Multi-valued properties and relationships

Compared with the RDF; none collapsed.

| Entity | RDF | Neo4j |
|---|---|---|
| `Aspirin` | two `medicationCategory` values | two `MEDICATIONCATEGORY` edges (Analgesic, Antiplatelet) |
| `DiagnosisHypertension` | two codes | two `HASCODE` edges (ICD-10 I10, SNOMED 38341003) |
| `Prescription002` | two medications | two `CONTAINSMEDICATION` edges |
| `Encounter001`, `Encounter003` | two participants each | two `PARTICIPATESIN` edges each |
| Doctors | licence identifiers | four `HASIDENTIFIER` edges, `DOC1001`–`DOC1004` |
| Allergy | `PatientBob` → Amoxicillin | one `HASALLERGY`/`ALLERGYTOMEDICATION` path |

The full automated comparison also checks every node's property map, including list-valued ones.

## 7. Semantic projection

| Feature | Result |
|---|---|
| RDF/OWL remains the authority; Neo4j derived | Yes: the database's fingerprint is the RDF's; `/sparql` is answered from the RDF; `load` rebuilds Neo4j from it |
| Class hierarchy | **Preserved**: `SUBCLASS_OF` between 31 class pairs (`Doctor → Practitioner → Person`); individuals carry superclass labels (`MATCH (p:Person)` returns 11) and an `INSTANCE_OF` edge to their class |
| Object-property semantics | Each property is a relationship type; targets are not collapsed |
| Inverse relationships | Projected and **marked inferred** (`HASALLERGY` asserted, `ALLERGYFORPATIENT` `inferred: true`) |
| Datatype properties | Typed: `dateOfBirth` → `DATE`, `encounterStart` → `ZONED DATETIME`, `observationValue` → `FLOAT`, names → `STRING` |
| **Not projected (intentional)** | OWL restrictions and `equivalentClass` definitions (the two defined classes are flagged on their class node), domain/range, disjointness, property chains, anything a reasoner derives beyond inverse and super-property edges. Reported by the projection itself |

## 8. API → Neo4j

The real API was started with `uvicorn` (production mode, temporary hashed credentials kept outside the repository, `NEO4J_DATABASE=neo4j`) and queried over HTTP.

| Check | Result |
|---|---|
| `GET /neo4j/health` (analyst) | `200 {database: neo4j, nodes: 183, status: healthy}`: the live node count, which no mock could return |
| `POST /execute-cypher` `MATCH (p:Patient) RETURN count(p)` | `200`, `5` |
| `MATCH (p:Person) RETURN count(p)` | `200`, `11` (superclass label, live) |
| Operational label (`ProjectionMeta`) via the API | `400`, schema stage: outside the query whitelist, by design |
| `POST /sparql` | `200`, 5 patients, answered from the RDF dataset, not Neo4j |

The API is therefore reading the live Neo4j Desktop database, not a mock, SQLite, an in-memory graph, a Docker Neo4j or a fixture. (Query results are returned as strings; see section 10.)

## 9. Security against the live database

25 of 25 checks passed in the scripted run; the same checks are the automated live tests (`tests/test_neo4j_live.py`).

| # | Check | Result |
|---|---|---|
| 1 | Unauthenticated request, wrong key | `401` |
| 2 | Viewer cannot call a Neo4j-backed read endpoint (`query:execute`) or write (`POST /neo4j/load`) | `403` |
| 3 | A forged `X-Role: admin` does not elevate a viewer | `403` |
| 4 | Destructive Cypher (`MATCH (n) DETACH DELETE n`), even for an admin | `400`, **refused by the application; never sent to Neo4j**; node count unchanged afterwards |
| 5 | Multi-statement (`…; MATCH (m) DETACH DELETE m`), `SET`, `LOAD CSV`, procedure call, comment smuggling | all `400` |
| 6 | Unbounded traversal `[*]` | `400` |
| 7 | Query timeout (`QUERY_TIMEOUT_SECONDS=1`), a deliberately expensive read | `504` with a short message, **terminated by the database** (`TransactionTimedOutClientConfiguration`), no driver text leaked, no transaction left running, API serves the next request |
| 8 | Tenant restriction: another tenant's identity cannot name this tenant, and a viewer cannot switch tenant | `403`, `403` |
| 9 | The database itself refuses a write from a `READ_ACCESS` session, whatever the application checks say | refused; nothing created |

No security test deleted or wrote anything; rejected queries were only ever sent to the application.

## 10. Bugs found by the live run, and the changes made

A recording fake driver cannot find these; a real server did.

1. **`/execute-cypher` was broken against a real server.** It passed a `Query(cypher, timeout=…)` object to `tx.run` inside `execute_read`, which the driver rejects (`Query object is only supported for session.run`); every user query returned `503`. The unit test's fake accepted it. **Fixed** (`services/sparql_to_cypher.py`): the timeout is now carried by the transaction (`unit_of_work(timeout=…)`), and the test fake now rejects non-string queries like the real driver does.
2. **A database timeout leaked as a raw `503` driver message.** Now a controlled `504` ("exceeded the N-second limit and was terminated by the database").
3. **Mixing hazard.** Loading into a database holding an older exporter's nodes would silently duplicate entities. The exporter now refuses (`ForeignDataPresent`, HTTP `422` on the API, exit `2` on the CLI, `--allow-foreign-data` to override).
4. **`NEO4J_USER`** is accepted as an alias for `NEO4J_USERNAME`, and two modules that read `NEO4J_*` straight from the environment now use the one configuration mechanism.
5. **`scripts/dev.py` assumed a project-local `venv/`** and (together with `demo` and the loader's hints) a Docker-first Neo4j. It now works inside any active virtual environment and points at Neo4j Desktop first. New: `doctor --neo4j` and `verify-neo4j`.

## 11. Exact commands used

```bash
# configuration and connectivity (the project's own settings; password never printed)
python scripts/dev.py doctor --neo4j
NEO4J_DATABASE=neo4j python scripts/dev.py verify-neo4j --census
# load, verify, validate, demo
NEO4J_DATABASE=neo4j python scripts/dev.py load
NEO4J_DATABASE=neo4j python scripts/dev.py load                     # again: idempotency
NEO4J_DATABASE=neo4j python scripts/dev.py verify-neo4j --projection --census
python scripts/dev.py validate
NEO4J_DATABASE=neo4j python scripts/dev.py demo --neo4j
# the live test suite (opt-in)
RUN_LIVE_NEO4J=1 NEO4J_DATABASE=neo4j python -m pytest tests/test_neo4j_live.py -v
# the full suite, with live tests enabled
RUN_LIVE_NEO4J=1 NEO4J_DATABASE=neo4j python -m pytest -q
```

Read-only probes (`SHOW DATABASES`, `CALL dbms.components()`, label and relationship censuses, `SHOW CONSTRAINTS`, `SHOW TRANSACTIONS`, identity and multi-value queries) were run with `READ_ACCESS` sessions.

## 12. Test results

| Run | Result |
|---|---|
| Full suite **with** the live tests (`RUN_LIVE_NEO4J=1 NEO4J_DATABASE=neo4j python -m pytest -q`) | **1231 passed**, 0 failed, 0 skipped (the 26 live tests executed against the real database) |
| Full suite, default (no live environment variable) | **1205 passed, 26 skipped** (the live tests skip, which is the safe default) |
| Live tests alone, against the configured `hcontology` database | all skipped: the guard saw 65 foreign nodes and wrote nothing |
| Unit, ontology, SHACL, SPARQL, projection, security and API tests | included in the 1205/1231 above (markers `unit`, `ontology`, `shacl`, `sparql`, `projection`, `api`, `integration`, `e2e`) |
| Scripted API + security run against the live database | 25 of 25 checks passed |
| `doctor --neo4j`, `load`, `validate`, `demo`, `demo --neo4j` | all exit 0 (`validate`: VALIDATION PASSED; `demo --neo4j` executed Cypher against the live database) |

After all runs: `neo4j` holds 183 nodes and 476 relationships (the projection, loaded repeatedly without change); `hcontology` still holds its original 124 nodes and 145 relationships with 0 `Resource` nodes.

## 13. Known limitations

- **One server, one edition, one OS.** Neo4j 5.20.0 (Desktop, enterprise-licensed development build) on Windows 11. Community edition, Linux, macOS, Aura, Docker Neo4j and Kubernetes were **not** tested. The Compose file's `neo4j` service was not started.
- **The user's `hcontology` database holds older data** and was deliberately not written to. The projection was verified in the empty `neo4j` database. A user who wants the projection in `hcontology` must first move or clear the old nodes themselves; the project will not do that.
- **API result values are strings** (`{"patients": "5"}`): `/execute-cypher` stringifies non-map values. Not changed here.
- **The expensive-query timeout is enforced by the database, but not instantly**: a pathological query was terminated about 4.5 s after a 1 s limit (the server checks at operator boundaries). It is bounded, not immediate.
- **Operational labels are outside the query whitelist** (`ProjectionMeta` cannot be queried through the API); use `verify-neo4j` or Neo4j Browser.
- **The AI layer's Neo4j paths** (agent memory, embeddings, documents) were not exercised here; the verification covers the projection, the Cypher API and the security controls only.
- The Neo4j Desktop application's own version was not queried (the server's was).

## 14. Final verdict

**PASS WITH LIMITATIONS.** The application connected to the running Neo4j Desktop database, loaded the projection into it, and executed real queries against it through its driver, its CLI and its HTTP API. The live graph matches the RDF projection exactly (124/124 nodes, 58/58 classes, 476/476 relationships, no label or property differences), identity is the IRI with no duplicates, multi-valued data is intact, the class hierarchy and inverse edges are projected as designed, and the security controls held against the live database. The limitations are scope (one server and edition; the user's existing database left untouched; Docker, Kubernetes and Aura unverified), not failures.
