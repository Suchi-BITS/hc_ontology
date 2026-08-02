# Healthcare Ontology Platform

Ontology-powered healthcare intelligence using **FastAPI**, **Owlready2**, **Ollama**, **Neo4j**, and **SPARQL**.

Built as a hands-on **Udemy course** project: from OWL ontology to natural-language graph queries and semantic search.

---
How to Run
uvicorn api:app --reload --host 127.0.0.1 --port 8000
streamlit run streamlit_app.py
## Features

| Layer | Capability |
|-------|------------|
| Ontology | Classes, individuals, graph traversal, RDF triples |
| SPARQL | Query OWL/RDF directly |
| LLM | Natural language → SPARQL (Ollama + LangChain) |
| Neo4j | Export, SPARQL→Cypher, NL→Cypher, execute Cypher |
| Embeddings | Ollama `nomic-embed-text` + Neo4j vector index |
| Multi-agent | LangGraph: Planner → Ontology → Query → Validation → HITL → Execution → Response |

---

## Quick start

### 1. Clone and configure

```bash
git clone <repo>
cd healthcare_ontology
cp .env.example .env   # edit Neo4j password & database name
```

**Windows:** `.\scripts\setup.ps1`  
**Linux/macOS:** `bash scripts/setup.sh`

### 2. Ollama

```bash
ollama pull qwen2.5:latest
ollama pull nomic-embed-text:latest
ollama serve
```

### 3. Neo4j Desktop

- Create/start an instance (e.g. instance name `hc`)
- Note the **database name** inside it (e.g. `hcontology`) — this is `NEO4J_DATABASE` in `.env`, not the instance name
- Set `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` in `.env`

### 4. Run API

```bash
.\venv\Scripts\activate          # Windows
python -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

- Swagger: http://127.0.0.1:8000/docs
- Streamlit UI: `streamlit run streamlit_app.py` → http://127.0.0.1:8501

### 5. First-time embedding setup

```http
POST /embedding/sync
```

Then try semantic search:

```http
GET /embedding/search?query=diabetes&top_k=5
```

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
| GET | `/neo4j/export` | Export ontology as Cypher |

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
| POST | `/validate/ontology` | Validate project `healthcare_ontology.owl` |
| GET | `/validation/report` | Last validation report (`?format=html`) |
| GET | `/validation/health` | SHACL engine / shapes health |

### Query safety & jobs
| Method | Path | Description |
|--------|------|-------------|
| GET | `/metrics` | Validation / LLM counters |
| GET | `/jobs/{id}` | Async LLM job status |
| POST | `/llm-query/async` | Enqueue NL→SPARQL |
| POST | `/nl-to-cypher/async` | Enqueue NL→Cypher |

### Multi-agent (LangGraph)
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

Headers: `X-Tenant-ID`, `X-Role` (`viewer`/`analyst`/`approver`/`admin`), `X-User-ID`, optional `X-API-Key`.

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

Shapes are merged by `load_all_shapes()` from `shapes/` (see `shapes/shapes_manifest.ttl`). Shared `Person` constraints live in `shapes/common/person_shapes.ttl` and are composed via `sh:node`. Fixture graphs for targeted tests live under `data/sample_instances/`.

Set `SHACL_VALIDATION_MODE=warn` (default) or `strict` in `.env`.

---

## Project structure

```
healthcare_ontology/
├── api.py                 # FastAPI entry point (uvicorn api:app)
├── streamlit_app.py       # UI entry (streamlit run streamlit_app.py)
├── core/                  # Config, auth, schemas, SHACL engine, dependencies
├── services/              # Ontology, SPARQL/Cypher, Neo4j, embeddings
├── routers/               # Route modules including shacl.py
├── scripts/               # generate_hc_ontology.py, add_data.py, setup.*
├── shapes/
│   ├── shapes_manifest.ttl
│   ├── common/            # prefixes.ttl, person_shapes.ttl
│   └── *_shapes.ttl
├── data/
│   └── sample_instances/  # valid/invalid RDF fixtures for tests
├── validation_reports/    # generated output only (.gitkeep)
├── healthcare_ontology.owl
├── tests/                 # conftest.py + SHACL/API tests
├── requirements.txt
└── …
```

---

## Docker

```bash
docker compose -f docker_compose.yaml up --build
```

API: http://localhost:8000  
Streamlit: http://localhost:8501  
(Neo4j still runs via Neo4j Desktop or a separate container.)

---

## Security (optional)

Set `API_KEY` in `.env`. Requests must include header:

```
X-API-Key: your-key
```

Leave `API_KEY` empty to disable authentication (default for local development).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| 500 on `/neo4j/health` | Check `NEO4J_DATABASE` matches an existing DB (not instance name) |
| Stale server after code change | Stop uvicorn fully (`Ctrl+C` twice), check `netstat` for port 8000 |
| Empty embedding search | Run `POST /embedding/sync` first |
| Missing vector index | Auto-created on sync/search; ensure Neo4j 5.11+ |
| LLM timeout | `/llm-query` and `/nl-to-cypher` can take 1–3 minutes |

See [COURSE_SETUP.md](COURSE_SETUP.md) for full student setup.

---

## Course materials

- [COURSE_STRUCTURE.md](COURSE_STRUCTURE.md) — suggested Udemy module outline
- [system_design.md](system_design.md) — architecture reference
- [COURSE_SETUP.md](COURSE_SETUP.md) — step-by-step student guide

---

## License

Internal / course project.
