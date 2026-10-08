# Healthcare Ontology Platform

Ontology-powered healthcare intelligence using **FastAPI**, **Owlready2**, **rdflib/pySHACL**, **Neo4j**, **SPARQL** and (optionally) **OpenAI**.

RDF/OWL/SHACL is the **authority**; Neo4j is a **derived projection** of it
([why](docs/semantic-authority-and-graph-projection.md)). Built as a hands-on course and book companion:
from an OWL ontology to validated data, competency-question queries, a property-graph projection, and (optionally) natural-language access.

---

---

## Where to start

This repository is a reference implementation for a book on healthcare ontologies and knowledge graphs. [docs/README.md](docs/README.md) is the index; [docs/reader-journey.md](docs/reader-journey.md) walks fourteen steps from the domain to the agent, and [docs/book-chapter-mapping.md](docs/book-chapter-mapping.md) maps each chapter to files and exercises. [docs/architecture-diagrams.md](docs/architecture-diagrams.md) has nine diagrams, [docs/anti-patterns.md](docs/anti-patterns.md) the mistakes it demonstrates or avoids, and [docs/troubleshooting.md](docs/troubleshooting.md) the fixes for the failures you will meet.

## Core and optional AI layer

The semantic foundation (ontology, RDF/OWL, SHACL, SPARQL, the graph projection and the HTTP API) needs no LLM, LangChain, LangGraph, vector index or agent framework. Embeddings, GraphRAG, the agent, memory, human approval and abstention are an optional advanced layer built on top of it. Core only: `pip install -r requirements-core.txt -c constraints.txt`, or `ENABLE_AI_LAYER=false`. See [docs/core-vs-ai-architecture.md](docs/core-vs-ai-architecture.md).

## Features

| Layer | Capability |
|-------|------------|
| Ontology | Classes, individuals, graph traversal, RDF triples |
| SPARQL | Query OWL/RDF directly |
| LLM *(optional AI layer)* | Natural language → SPARQL (OpenAI + LangChain) |
| Neo4j | Derived projection of the RDF (verified live against Neo4j Desktop), SPARQL→Cypher, NL→Cypher, execute Cypher |
| Embeddings *(optional AI layer)* | OpenAI embeddings (`text-embedding-3-small`) + Neo4j vector index |
| Multi-agent *(optional AI layer)* | LangGraph: Planner → Ontology → Query → Validation → HITL → Execution → Response |

---

---

## Setup, step by step

Fast path: `python scripts/dev.py quickstart` runs sections 3, 4, 8, 9 and the demo for you, offline, with no Docker, Neo4j or API key.
Every command below is `python scripts/dev.py <command>` (Windows: `py scripts\dev.py <command>`; Linux/macOS: `make <command>` also works).

### 1. Prerequisites

| Needed for | Requirement |
|---|---|
| Everything | **Python 3.11** (verified on 3.11.8; newer versions are untested), **git** |
| Neo4j graph (`load`) | **A local Neo4j 5.x**: Neo4j Desktop is the verified reference ([docs/neo4j-desktop.md](docs/neo4j-desktop.md)). Docker (`up`) is an optional, unverified alternative |
| OWL reasoner checks | **Java** (any recent JRE); without it 6 tests are skipped |
| Natural-language queries, embeddings, GraphRAG, agent | An **OpenAI API key** (optional) |

Ollama is not used. Windows, macOS and Linux are supported; the first install needs access to PyPI.

### 2. Clone

```bash
git clone https://github.com/Suchi-BITS/hc_ontology.git
cd hc_ontology
```

### 3. Environment setup and 4. Dependency installation

```bash
python scripts/dev.py setup
```

This creates `venv/`, installs `requirements.txt` pinned by `constraints.txt`, and creates `.env` from `.env.example` with a generated local `NEO4J_PASSWORD` (`.env` is git-ignored; never commit it). `OPENAI_API_KEY` stays empty; add one to `.env` only if you want the OpenAI-backed features. Then:

```bash
python scripts/dev.py doctor     # PASS/WARN/FAIL for each prerequisite, with the fix
```

Without the helper: `python -m venv venv`, activate it, `pip install -r requirements-dev.txt -c constraints.txt`, `cp .env.example .env` and fill in the placeholders.
Behind a proxy or antivirus that breaks TLS, `setup` recovers by itself (see [troubleshooting](#12-troubleshooting)).

### 5. Service startup

**Reference path: Neo4j Desktop** ([setup and what was verified](docs/neo4j-desktop.md)). Create and start a local database in Neo4j Desktop, then set `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` and `NEO4J_DATABASE` in `.env` (use an *empty* database) and check it:

```bash
python scripts/dev.py doctor --neo4j     # read-only: connects, reports version, database, node and relationship counts
```

Optional alternative (not verified): `python scripts/dev.py up` starts a Neo4j 5.26 container with Docker. Skip this section entirely if you do not need the graph database. To run the API and the UI in Docker, see [Docker](#docker).

### 6. Ontology setup

The **schema** (`ontology/healthcare_schema.ttl`) and the synthetic **sample data** (`data/sample_data.ttl`) are separate, **generated** files, both committed; nothing needs to be built to use them. Why they are separate: [docs/schema-and-sample-data.md](docs/schema-and-sample-data.md). To regenerate after changing `scripts/generate_hc_ontology.py` or `data/source/`:

```bash
python scripts/generate_hc_ontology.py    # the schema
python scripts/generate_sample_data.py    # the sample data
```

RDF/OWL/SHACL is the authority; Neo4j is derived from it ([why](docs/semantic-authority-and-graph-projection.md)). The modelling decisions are in [docs/ontology-engineering.md](docs/ontology-engineering.md).

### 7. Data loading

```bash
python scripts/dev.py load       # needs Neo4j (step 5); loads into the CONFIGURED endpoint, for example Neo4j Desktop
```

Projects the RDF into Neo4j: SHACL-gated, idempotent (safe to run again), scoped to the projection (it never touches agent memory, documents or embeddings), then verifies the node and relationship counts. `python scripts/dev.py load --dry-run` shows the plan without a database. `python scripts/dev.py verify-neo4j --projection` then compares the live database with the RDF. The loader refuses a database that already holds nodes from another graph domain (see [docs/neo4j-desktop.md](docs/neo4j-desktop.md)). The sample data is already inside the ontology file (5 patients, 4 doctors, encounters, diagnoses with ICD-10 codes, medications, an allergy, observations).

### 8. Validation

```bash
python scripts/dev.py validate               # parse, generator equals file, SHACL, projection plan
python scripts/dev.py validate --reasoner    # also the OWL reasoner (needs Java)
```

### 9. Tests

```bash
python scripts/dev.py test                   # whole suite; no Neo4j or API key needed (count it with: python -m pytest --collect-only -q | tail -1)
python scripts/dev.py test -m shacl          # one level (see docs/testing-strategy.md)
python scripts/dev.py test -m "not reasoner" # skip the Java-dependent tests
```

### 10. API startup

```bash
python scripts/dev.py serve
```

Swagger UI: http://127.0.0.1:8000/docs. Optional UI: `venv/bin/streamlit run streamlit_app.py` (Windows: `venv\Scripts\streamlit run streamlit_app.py`). Run the guided tour with `python scripts/dev.py demo` (add `--neo4j` after step 7 to query the graph).

### 11. Query examples

With the API running (these work without Neo4j or an OpenAI key):

```bash
# the patients
curl http://127.0.0.1:8000/patients

# SPARQL: which patients have a diagnosis coded ICD-10 E11 (type 2 diabetes)?
curl -s http://127.0.0.1:8000/sparql -H "Content-Type: application/json" -d '{
  "query": "PREFIX hc: <http://example.org/healthcare-hospital.owl#> SELECT DISTINCT ?patient WHERE { ?patient hc:hasDiagnosis/hc:hasCode ?c . ?c hc:codeValue \"E11\" }"
}'
# -> PatientAlice, PatientBob

# validate your own RDF against the SHACL shapes
curl -s http://127.0.0.1:8000/validate -H "Content-Type: application/json" -d '{
  "data": "@prefix hc: <http://example.org/healthcare-hospital.owl#> . hc:P a hc:Patient .",
  "format": "turtle", "shape_files": ["patient_shapes.ttl"]
}'
# -> violations: Patient must have a firstName / lastName / dateOfBirth / bloodGroup

# what would be loaded into Neo4j (no database needed)
curl http://127.0.0.1:8000/neo4j/projection
```

PowerShell: `Invoke-RestMethod http://127.0.0.1:8000/patients`. More requests: [examples/requests.http](examples/requests.http).

The 21 competency questions are plain SPARQL files in [sparql/](sparql/) (`cq01_patients.rq` ... `cq21_patients_with_a_condition.rq`), each with a tested answer and a catalog entry. The chain from domain question to ontology concepts, query, expected result and test is in [docs/competency-questions.md](docs/competency-questions.md).

After step 7, in Neo4j Browser (superclass labels and inverse relationships are part of the projection):

```cypher
MATCH (p:Patient)-[:HASCONDITION]->(c:Condition) RETURN p.name, c.diagnosisName ORDER BY p.name;
MATCH (d:Doctor)-[:HASSPECIALTY]->(s:Specialty) RETURN d.name, s.name;
MATCH (p:Patient)<-[:PRESCRIBEDFOR]-(:Prescription)-[:CONTAINSMEDICATION]->(m:Medication)-[:MEDICATIONCATEGORY]->(c)
WHERE c.name = 'MedCategoryAntidiabetic' RETURN DISTINCT p.name, m.medicationName;
```

With an `OPENAI_API_KEY`: `POST /llm-query` (natural language to SPARQL), `POST /nl-to-cypher`, `POST /embedding/sync` then `GET /embedding/search?query=diabetes`, and the agent at `POST /agent/query`.

What needs what:

| Capability | Needs |
|---|---|
| Ontology, SHACL, SPARQL, projection plan, tests, demo | Python only |
| Neo4j projection (`up`, `load`, `demo --neo4j`) | Neo4j 5.x (Docker or your own) and `NEO4J_PASSWORD` |
| OWL reasoner checks | Java |
| Natural-language queries, embeddings, GraphRAG, agent | `OPENAI_API_KEY` |

What has been verified on a fresh clone, and what has not: [docs/fresh-clone-verification.md](docs/fresh-clone-verification.md).

---

## API overview

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service info |
| GET | `/health` | API health |
| GET | `/stats` | Ontology counts |

### Ontology & domain
| Method | Path | Description |
|--------|------|-------------|
| GET | `/classes`, `/individuals`, … | Metadata |
| GET | `/patients`, `/doctors`, … | Domain data |
| GET | `/search?q=` | **Text** search on individual names |

### SPARQL & LLM
| Method | Path | Description |
|--------|------|-------------|
| POST | `/sparql` | Run SPARQL |
| POST | `/llm-query` | NL → SPARQL (recommended) |
| POST | `/nl-query` | Alias (deprecated) |

### Neo4j
| Method | Path | Description |
|--------|------|-------------|
| GET | `/neo4j/health` | Neo4j connectivity |
| POST | `/sparql-to-cypher` | SPARQL → Cypher → execute |
| POST | `/nl-to-cypher` | NL → Cypher |
| POST | `/execute-cypher` | Run Cypher |
| GET | `/neo4j/projection` | Preview the RDF→Neo4j projection (no database access) |
| GET | `/neo4j/export` | The projection as idempotent Cypher MERGE statements |
| POST | `/neo4j/load` | Synchronize Neo4j from the RDF (SHACL-gated, scoped, idempotent) |

### Embeddings
| Method | Path | Description |
|--------|------|-------------|
| POST | `/embedding/sync` | Sync ontology → Neo4j vectors |
| GET | `/embedding/health` | Embedding model health |
| GET | `/embedding/search?query=&top_k=` | Semantic search |
| GET | `/embedding/similar/{concept}?top_k=` | Similar concepts |

### SHACL
| Method | Path | Description |
|--------|------|-------------|
| POST | `/validate` | Validate inline RDF against shapes |
| POST | `/validate/file` | Validate uploaded OWL/RDF file |
| POST | `/validate/ontology` | Validate the project dataset (schema + sample data) against the shapes |
| GET | `/validation/report` | Last validation report (`?format=html`) |
| GET | `/validation/health` | SHACL engine / shapes health |

### Query safety & jobs
| Method | Path | Description |
|--------|------|-------------|
| GET | `/metrics` | Validation / LLM counters |
| GET | `/jobs/{id}` | Async LLM job status |
| POST | `/llm-query/async` | Enqueue NL→SPARQL |
| POST | `/nl-to-cypher/async` | Enqueue NL→Cypher |

### Multi-agent (LangGraph) — optional AI layer
| Method | Path | Description |
|--------|------|-------------|
| GET | `/agent/health` | Graph + feature flags |
| POST | `/agent/query` | Run Planner→…→Response pipeline (may pause for HITL) |
| POST | `/agent/query/async` | Background agent run → poll `/agent/jobs/{id}` |
| POST | `/agent/resume` | Approve/reject a paused execution |
| GET | `/agent/state/{thread_id}` | Inspect checkpointed state |
| GET | `/agent/memory/{session_id}` | KG conversation memory |

### Enterprise
| Method | Path | Description |
|--------|------|-------------|
| GET | `/enterprise/health` | Capability + LangSmith/OTEL status |
| GET | `/enterprise/tenants` | Multi-tenant catalog |
| GET | `/enterprise/ontologies` | Multi-ontology + versions (tenant-scoped) |
| POST | `/enterprise/hybrid-search` | Graph + vector hybrid retrieval |
| POST | `/enterprise/eval/run` | Offline agent evaluation |
| POST | `/enterprise/workflows/run` | Background workflows |
| GET | `/enterprise/monitoring` | Alerts + latency/cost snapshot |
| GET | `/enterprise/metrics` | Prometheus metrics scrape |

Identity, role and tenant come from your **API credential** (`X-API-Key` or `Authorization: Bearer`), looked up on the server. `X-Role`, `X-User-ID` and `X-Tenant-ID` are **not trusted**: a role header is ignored, and naming another tenant is refused with 403. Create a credential with `python scripts/dev.py credential add --user suchismita --tenant abhigya-ai-lab --role admin`. See [docs/security-architecture.md](docs/security-architecture.md).

`POST /sparql` and `POST /execute-cypher` run the shared validator (safety → syntax → schema → LIMIT) before execution.

Example requests: [`examples/requests.http`](examples/requests.http)

---

## SHACL vs OWL — who owns which check?

The OWL file may encode cardinality via `owl:Restriction`. SHACL duplicates *some* of that for instance validation, but the layers have different jobs:

| Concern | Authoritative layer |
|---------|---------------------|
| Class hierarchy, reasoning, inferred facts | OWL + reasoner |
| Instance well-formedness (required fields, patterns, closed shapes) | SHACL |
| Business rules (e.g. “no prescription may contain a medication the patient is allergic to”) | SHACL (`sh:SPARQLConstraint` in `medication_shapes.ttl`) |

Shapes are merged by `load_all_shapes()` from `shapes/` (see `shapes/shapes_manifest.ttl`). Shared `Person` constraints live in `shapes/common/person_shapes.ttl` and are composed via `sh:node`. Fixture graphs for targeted tests live under `data/sample_instances/`. Sample data is CSV under `data/source/`, checked by a data contract before it becomes RDF: see [docs/sample-data-and-semantic-mapping.md](docs/sample-data-and-semantic-mapping.md).

Set `SHACL_VALIDATION_MODE=warn` (default) or `strict` in `.env`.

---

## Project structure

```
hc_ontology/
├── api.py                 # FastAPI entry point (uvicorn api:app)
├── streamlit_app.py       # UI entry (streamlit run streamlit_app.py)
├── core/                  # Config, auth, schemas, SHACL engine, dependencies
├── services/              # Ontology, SPARQL/Cypher, Neo4j, embeddings
├── scripts/               # dev.py (setup/doctor/validate/test/demo/up/load), generate_hc_ontology.py, validate.py,
│                          #   load_graph.py, demo.py, seed_neo4j_demo.py (dev only)
├── sparql/                # competency questions as .rq files (executed by the tests)
├── routers/               # Route modules including shacl.py
├── shapes/
│   ├── shapes_manifest.ttl
│   ├── common/            # prefixes.ttl, person_shapes.ttl
│   └── *_shapes.ttl
├── data/
│   ├── sample_data.ttl    # the synthetic instances (ABox): generated from source/
│   ├── source/            # sample data as CSV (validated, then mapped to RDF)
│   ├── reference/         # independent drug-classification reference
│   ├── invalid_source/    # one deliberately broken table per case, with EXPECT
│   └── sample_instances/  # valid/invalid RDF fixtures for tests
├── validation_reports/    # generated output only (.gitkeep)
├── ontology/
│   └── healthcare_schema.ttl   # the schema (TBox): generated
├── tests/                 # conftest.py + SHACL/API tests
├── requirements.txt       # runtime dependencies
├── requirements-dev.txt   # + test tools
├── constraints.txt        # exact tested versions (pip -c)
├── Makefile               # wrapper for scripts/dev.py
└── …
```

---

## Docker

```bash
python scripts/dev.py setup                              # once: creates .env with a generated NEO4J_PASSWORD
export API_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")   # the API container requires credentials
docker compose -f docker_compose.yaml up -d --build      # Neo4j + API + Streamlit (production mode, ports on 127.0.0.1)
docker compose -f docker_compose.yaml run --rm api python scripts/load_graph.py --wait 60 --verify
```

The API container is **production-mode by default**: it refuses to start without credentials. For local work without
credentials there is one explicit command: add `-f docker_compose.dev.yaml` (open admin, loopback only). See
[docs/security-policy.md](docs/security-policy.md).

API: http://localhost:8000/docs
Streamlit: http://localhost:8501
Neo4j Browser: http://localhost:7474 (user `neo4j`, password from `.env`)

Compose includes Neo4j and starts the API only after Neo4j is healthy. `NEO4J_PASSWORD` is required (no default; compose stops with a clear message if it is unset). `OPENAI_API_KEY` is optional. `.env` is excluded from the image by `.dockerignore`; values are passed at runtime. The image runs as an unprivileged user. If a port is taken (for example by Neo4j Desktop on 7687), set `NEO4J_BOLT_PORT`, `NEO4J_HTTP_PORT`, `API_PORT` or `STREAMLIT_PORT` in `.env`.

---

## Security (optional)

Set `API_KEY` in `.env` (strongly recommended anywhere the API is reachable by others). Requests must include header:

```
X-API-Key: your-key
```

Leave `API_KEY` empty only for local development - set it anywhere the API is reachable by others. See [docs/security-and-configuration.md](docs/security-and-configuration.md).

---

## 12. Troubleshooting

| Problem | Fix |
|---------|-----|
| `pip` retries / `CERTIFICATE_VERIFY_FAILED` | `python scripts/dev.py setup` handles this automatically (installs `pip-system-certs`, which uses the OS certificate store). See [docs/reproducibility.md](docs/reproducibility.md) |
| Anything else on first run | `python scripts/dev.py doctor` tells you what is missing and how to fix it |
| `No module named langchain_openai` after `pip install` | **Wrong venv.** Run `python -c "import sys; print(sys.executable)"` — pip and uvicorn must use the same path. Use `python -m pip` and `python -m uvicorn`, not bare `pip`/`uvicorn` |
| Mixed venv (`D:\healthcare_ontology\venv` in traceback) | Deactivate all venvs, `cd hc_ontology`, activate only `.\venv\Scripts\activate`, delete stray `PYTHONPATH` env var |
| `WinError 10013` on uvicorn start | Port **8000 already in use**. Run `netstat -ano \| findstr :8000`, then `taskkill /PID <pid> /F`. Or use another port: `python -m uvicorn api:app --port 8001` |
| `{"detail":"Connection error."}` in Streamlit | HTTPS/SSL to OpenAI failed. Run `python -m pip install truststore` in `hc_ontology\venv`, restart API. Or use diagnosis shortcut: `GET /patients/PatientJohn/diagnoses` (Streamlit tab 2 does this automatically for John Doe diagnosis questions) |
| Inspect memory context in API terminal | Set `MEMORY_DEBUG_CONTEXT=true` in `.env`, restart API. Use **`POST /agent/query`** (not Streamlit NL→Cypher) with a stable `session_id`. Optional: `MEMORY_DEBUG_CONTEXT_FULL=true` for longer previews. See [Memory cycle testing](#memory-cycle-testing) below. |
| 500 on `/neo4j/health` | Check `NEO4J_DATABASE` matches an existing DB (not instance name) |
| Stale server after code change | Stop uvicorn fully (`Ctrl+C` twice), check `netstat` for port 8000 |
| Empty embedding search | Run `POST /embedding/sync` first |
| Missing vector index | Auto-created on sync/search; ensure Neo4j 5.11+ |
| LLM timeout | `/llm-query` and `/nl-to-cypher` can take 1–3 minutes |

See [COURSE_SETUP.md](COURSE_SETUP.md) for full student setup.

---

## Memory cycle testing

Memory layers only run on **`POST /agent/query`**. Streamlit NL→Cypher shortcuts bypass the LangGraph memory pipeline.

### Enable terminal debug logs

```env
MEMORY_DEBUG_CONTEXT=true
# optional — longer working_context / ontology previews
MEMORY_DEBUG_CONTEXT_FULL=true
```

Restart uvicorn. Each query prints labeled blocks in the API terminal (default off — no behavior change when disabled).

### Log phases per turn

| Phase | What to inspect |
|-------|-----------------|
| `assemble_context (before)` | `meta_recall_plan`: `episodic_limit`, `similar_limit`, `max_chars`, `recall_confidence`, `context_pressure`, `signals.scored_turns` |
| `assemble_context (after)` | `episodic.recent_text_preview`, `similar_episodes`, `procedural` (name + `template_query`), `working_context` |
| `enrich_semantic (before/after)` | `semantic.concepts`, `hybrid_meta`, `retrieval_meta`, `ontology_context` |
| `query (grounded_context)` | Full grounded prompt sent to NL→Cypher; `repair_context` on validation retry |
| `query (procedure_template)` | `procedure_template_reused: true` when a learned pattern is reused |
| `validation (fail → retry)` | `validation_error`, `draft_query_preview`, `will_retry` |
| `commit_turn (after)` | `turn_id`, `procedure_learned_id`, `meta_post_turn` (archive/decay) |

### Test sequences (reuse `session_id`)

Use `examples/requests.http` or Swagger. Save `session_id` from the first response and send it on every follow-up turn.

1. **Episodic** — Q1: *What is the patient diagnosis for John Doe?* → Q2 (same session): *What diagnosis did we discuss for John Doe earlier?* → Look for `similar_episodes` / `recent_text_preview` in `assemble_context (after)`.
2. **Procedural** — Q1: *Show me all patients diagnosed with diabetes.* → Q2: *Show me all patients diagnosed with hypertension.* → Look for `query (procedure_template)` or high `match_score` in `procedural`.
3. **Semantic** — *What is the relationship between a patient and a diagnosis?* → Inspect `enrich_semantic (after)` concepts + `ontology_context`.
4. **Working memory** — Progressive turns in one session (*My patient is John Doe* → *John Doe was diagnosed with diabetes* → *What treatment…*) → `recent_text_preview` grows in `assemble_context (after)`.
5. **Meta-memory** — Long session (4+ turns) → `context_pressure`, lower limits in `meta_recall_plan`.
6. **Repair** — Question that yields invalid Cypher → on retry, `query (grounded_context)` shows `repair_context.present: true`.
7. **Full lifecycle** — Diabetes patients → medications → concepts → new session *What did we previously query…* → hypertension with same approach → trace `commit_turn` → next turn `procedural`.

---

## Course materials

- [COURSE_STRUCTURE.md](COURSE_STRUCTURE.md) — suggested Udemy module outline
- [docs/UDEMY_REASONING_SCRIPT.md](docs/UDEMY_REASONING_SCRIPT.md) — Udemy video script (reasoning, inference, SHACL, multi-hop)
- [docs/UDEMY_GRAPH_ALGORITHMS_SCRIPT.md](docs/UDEMY_GRAPH_ALGORITHMS_SCRIPT.md) — Udemy video script (graph algorithms: k-NN, RRF, traversal, GraphRAG)
- [docs/semantic-authority-and-graph-projection.md](docs/semantic-authority-and-graph-projection.md) — RDF/OWL/SHACL as authority, Neo4j as derived projection
- [docs/ontology-engineering.md](docs/ontology-engineering.md) — ontology modeling decisions (Encounter, specialty, time, identifiers, codes, OWL vs SHACL)
- [system_design.md](system_design.md) — architecture reference
- [COURSE_SETUP.md](COURSE_SETUP.md) — step-by-step student guide

---

## License

Internal / course project.
