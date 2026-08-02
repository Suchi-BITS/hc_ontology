# Healthcare Ontology Platform — System Design

## 1. Overview

The platform delivers ontology-driven healthcare intelligence using semantic web technologies, graph databases, and local LLMs (Ollama).

**Capabilities:**
- OWL ontology exploration
- RDF/SPARQL querying
- Natural language → SPARQL / Cypher
- Neo4j export and execution
- Semantic vector search
- **Enterprise multi-agent orchestration (LangGraph)** — Planner, Ontology, Query,
  Validation, Execution, Response agents with shared state, retries, HITL, and KG memory

---

## 2. Architecture

```
                    User / Streamlit UI
                            │
                            ▼
                      FastAPI (api.py)
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
  HealthcareOntology   SparqlGenerator    EmbeddingService
        │                   │                   │
        ▼                   ▼                   ▼
   Owlready2            Ollama LLM         Ollama Embeddings
        │                   │                   │
        ▼                   ▼                   ▼
 healthcare.owl         SPARQL            Neo4j Vector Index
        │                   │                   │
        ▼                   ▼                   ▼
     RDFLib              Validation         Similarity Search

  SparqlToCypher ──► Neo4j (Cypher)
  CypherGenerator ──► Neo4j (Cypher)

  /agent/query ──► LangGraph multi-agent (shared AgentState)
       Planner → Ontology → Query → Validation ⇄ retry
                         → Human Gate (HITL) → Execution → Response
                         → Neo4j AgentSession / AgentTurn memory
```

---

## 3. Project layout

| Path | Role |
|------|------|
| `api.py` | Application factory, router registration |
| `streamlit_app.py` | Course demo UI |
| `core/` | Config, auth, schemas, SHACL, dependencies |
| `services/load_ontology.py` | OWL loading & SPARQL |
| `services/sparql_generator.py` | NL → SPARQL + validation |
| `services/sparql_to_cypher.py` | SPARQL → Cypher |
| `services/cypher_generator.py` | NL → Cypher |
| `services/embedding_service.py` | Embeddings + vector search |
| `services/neo4j_exporter.py` | OWL → Neo4j bulk export |
| `agents/` | LangGraph multi-agent system (state, nodes, memory, graph) |
| `routers/` | HTTP route modules |
| `scripts/` | Ontology generation / data seeding / setup |
| `shapes/` | SHACL constraints |
| `data/sample_instances/` | RDF fixtures for SHACL tests |

---

## 4. API categories

### System — `routers/system.py`
- `GET /`, `/health`, `/stats`

### Ontology — `routers/ontology.py`, `patients.py`, `doctors.py`, `clinical.py`
- Metadata, domain resources, text search (`/search?q=`)

### SPARQL — `routers/sparql.py`
- `POST /sparql`, `/llm-query`, `/nl-query` (deprecated)

### Neo4j — `routers/neo4j.py`
- `/neo4j/*`, `/sparql-to-cypher`, `/nl-to-cypher`, `/execute-cypher`

### Embeddings — `routers/embedding.py`
- `/embedding/sync`, `/embedding/health`, `/embedding/search`, `/embedding/similar/{concept}`

---

## 5. Data flows

### NL → Answer (Cypher path)
```
Question → CypherGenerator → Cypher → Neo4j → JSON results
```

### NL → Answer (SPARQL path)
```
Question → SparqlGenerator → SPARQL → RDFLib → JSON results
```

### Semantic search
```
OWL annotations → Ollama embed → Neo4j OntologyConcept nodes
Query text → embed → vector index → ranked concepts
```

---

## 6. Deployment

```
Docker Compose
├── ollama:11434
├── api:8000
└── streamlit:8501

Neo4j Desktop (host) :7687  ← bolt://host.docker.internal
```

---

## 7. Configuration

See `.env.example`. Critical variables:

| Variable | Purpose |
|----------|---------|
| `NEO4J_DATABASE` | Target DB name (not instance name) |
| `OLLAMA_MODEL` | LLM for SPARQL/Cypher generation |
| `EMBEDDING_MODEL` | Ollama embedding model |
| `API_KEY` | Optional request authentication |

---

## 8. Known limitations

- SPARQL→Cypher translator supports a subset of SPARQL (no full SPARQL 1.1)
- LLM endpoints are synchronous and slow (1–3 min)
- Embedding sync is full-batch, not incremental
- `nl-query` deprecated in favor of `llm-query`

---

## 9. Testing & CI

```bash
pytest tests/ -v
```

GitHub Actions workflow: `.github/workflows/ci.yml`
