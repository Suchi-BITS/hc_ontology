# Udemy course structure (suggested)

**Course title idea:** *Build a Healthcare Knowledge Graph with OWL, FastAPI, Neo4j & Local LLMs*

**Level:** Intermediate  
**Duration:** ~8–12 hours video + labs

---

## Module 1 — Introduction (30 min)

- What is an ontology? Why healthcare?
- Course architecture overview (`system_design.md` diagram)
- Demo: Streamlit capstone preview
- **Lab:** Clone repo, run `setup.ps1`, open `/docs`

---

## Module 2 — Healthcare ontology in OWL (60 min)

- Classes: Patient, Doctor, Diagnosis, Treatment
- Object vs data properties
- **Files:** `scripts/generate_hc_ontology.py`, `ontology/healthcare_schema.ttl`, `scripts/generate_sample_data.py`, `data/sample_data.ttl`
- **Lab:** Open OWL in Protege; `GET /classes`, `/graph-summary`

---

## Module 3 — Owlready2 & FastAPI (75 min)

- Loading ontology in Python (`services/load_ontology.py`)
- REST design with FastAPI routers
- **Lab:** `GET /patients`, `/patients/{name}/diagnoses`

---

## Module 4 — SPARQL querying (60 min)

- RDF triples, PREFIX, SELECT
- **Lab:** `POST /sparql`, `GET /rdf/triples`

---

## Module 5 — Natural language → SPARQL (90 min)

- LangChain + OpenAI prompt engineering
- Validation & repair loop (`services/sparql_generator.py`)
- **Lab:** `POST /llm-query` — *patients with hypertension*
- **Note:** Expect 1–3 min response time

---

## Module 6 — Neo4j graph database (75 min)

- Property graph vs RDF model
- Export ontology (`GET /neo4j/export`, `services/neo4j_exporter.py`)
- **Lab:** `GET /neo4j/health`, inspect graph in Neo4j Browser

---

## Module 7 — SPARQL to Cypher bridge (60 min)

- Translation rules (`services/sparql_to_cypher.py`)
- `rdf:type` → node labels
- **Lab:** `POST /sparql-to-cypher`

---

## Module 8 — Natural language → Cypher (60 min)

- Direct Cypher generation (`services/cypher_generator.py`)
- **Lab:** `POST /nl-to-cypher` → `POST /execute-cypher`

---

## Module 9 — Semantic embeddings (90 min)

- OpenAI `text-embedding-3-small` (1536 dimensions)
- Neo4j vector index
- **Lab:** `POST /embedding/sync`, `GET /embedding/search`
- **Instructor script:** [docs/UDEMY_GRAPH_ALGORITHMS_SCRIPT.md](docs/UDEMY_GRAPH_ALGORITHMS_SCRIPT.md) (k-NN, RRF, hybrid retrieval, GraphRAG — ~30 min)

---

## Module 10 — SHACL validation (45 min)

- Constraints vs schema (SHACL shapes)
- **Files:** `shapes/*.ttl`, `core/shacl_*.py`, `routers/shacl.py`
- **Lab:** `POST /validate/ontology`, `POST /validate`, `GET /validation/report`
- **Instructor script:** [docs/UDEMY_REASONING_SCRIPT.md](docs/UDEMY_REASONING_SCRIPT.md) (deductive reasoning, OWL/RDFS inference, SHACL rules, chaining, graph traversal)

---

## Module 11 — Query validation & safety (60 min)

- Live risk: weak SPARQL checks / unguarded `/execute-cypher`
- Shared validator Strategy pattern (`core/query_validator.py`)
- Four stages: syntax → safety → schema whitelist → LIMIT/timeout
- Wire into NL→SPARQL repair loop + NL→Cypher repair loop
- **Lab:** send `DETACH DELETE` to `/execute-cypher` (blocked); compare `/metrics`
- Rate limits, query cache, async jobs (`/llm-query/async`, `/jobs/{id}`)

---

## Module 12 — Capstone & production (60 min)

- Streamlit demo app walkthrough
- Optional API key auth
- Docker Compose (+ optional Neo4j profile)
- Multi-stage Docker build
- When to use SPARQL vs Cypher vs vector search vs SHACL
- **Capstone:** End-to-end clinical question in Streamlit

---

## Assessments (optional)

| Quiz topic | Question example |
|------------|------------------|
| Ontology | What is the difference between `hasDiagnosis` and `diagnosisName`? |
| SPARQL | Write a query listing all doctors |
| Neo4j | Why is the Neo4j graph a *derived projection* and RDF the authority? |
| LLM | What does the repair loop in `sparql_generator` do? |
| Safety | Why does `/execute-cypher` reject `DETACH DELETE`? |

---

## Repository map per module

| Module | Primary files |
|--------|---------------|
| 2 | `scripts/generate_hc_ontology.py` |
| 3 | `services/load_ontology.py`, `routers/` |
| 4 | `services/load_ontology.py` (execute_sparql) |
| 5 | `services/sparql_generator.py`, `routers/sparql.py` |
| 6 | `services/neo4j_exporter.py`, `routers/neo4j.py` |
| 7 | `services/sparql_to_cypher.py` |
| 8 | `services/cypher_generator.py` |
| 9 | `services/embedding_service.py`, `routers/embedding.py` |
| 10 | `shapes/`, `core/shacl_*.py`, `routers/shacl.py` |
| 11 | `core/query_validator.py`, `sparql_validator.py`, `cypher_validator.py` |
| 12 | `streamlit_app.py`, `Dockerfile`, `core/auth.py` |
