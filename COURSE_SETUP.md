# Course setup guide (students)

Follow these steps in order before starting the Udemy labs.

---

## Prerequisites

- Python 3.11+
- [Neo4j Desktop](https://neo4j.com/download/)
- [Ollama](https://ollama.com/)
- Git

---

## Step 1 — Project setup

```powershell
cd healthcare_ontology
.\scripts\setup.ps1
```

Or on macOS/Linux:

```bash
bash scripts/setup.sh
```

Copy and edit environment:

```bash
cp .env.example .env
```

---

## Step 2 — Neo4j

1. Open **Neo4j Desktop** → create/start an instance (name can be `hc`)
2. Open **Databases** tab → note the database name (e.g. `hcontology` or `neo4j`)
3. Set password on first login
4. Update `.env`:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=hcontology
```

> **Important:** `NEO4J_DATABASE` is the **database name inside Neo4j**, not the Desktop instance name.

Verify in Browser or:

```http
GET http://127.0.0.1:8000/neo4j/health
```

---

## Step 3 — Ollama

```bash
ollama pull qwen2.5:latest
ollama pull nomic-embed-text:latest
ollama serve
```

Verify:

```http
GET http://127.0.0.1:8000/embedding/health
```

---

## Step 4 — Start API

```bash
uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/docs

Optional UI:

```bash
streamlit run streamlit_app.py
```

---

## Step 5 — Sync embeddings (once per fresh Neo4j DB)

```http
POST http://127.0.0.1:8000/embedding/sync
```

Expected:

```json
{ "status": "success", "processed": 42, "failed": 0 }
```

---

## Step 6 — Happy-path smoke test

Run these in Swagger or `examples/requests.http`:

1. `GET /patients` → list of patients
2. `POST /sparql` with a SELECT query → results
3. `POST /nl-to-cypher` with `"List all patients"` → Cypher string
4. `POST /execute-cypher` with generated Cypher → Neo4j rows
5. `GET /embedding/search?query=diabetes&top_k=5` → scored concepts

---

## Common errors

### `Database does not exist`

Wrong `NEO4J_DATABASE`. List databases in Neo4j Browser:

```cypher
SHOW DATABASES;
```

### `Variable patient not defined` (Cypher)

Malformed SPARQL was translated. Use `.` between triples:

```sparql
SELECT ?patient WHERE { ?patient rdf:type :Patient . }
```

### `No vector schema index: ontology_embeddings`

Run `POST /embedding/sync` or retry search (index is auto-created).

### Port 8000 still returns old errors after restart

Kill leftover Python processes on port 8000, then start uvicorn again.

### LLM endpoints hang

Normal — first Ollama call can take 1–3 minutes. Wait or use smaller questions for demos.

---

## Capstone exercise

**Question:** *Which patients have hypertension and what treatments do they receive?*

1. `POST /nl-to-cypher` with the question
2. Review generated Cypher
3. `POST /execute-cypher`
4. Compare with `POST /llm-query` (SPARQL path) and `GET /embedding/search?q=hypertension treatment`
