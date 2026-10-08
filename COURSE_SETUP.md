# Course setup guide (students)

> **Fastest path:** `python scripts/dev.py quickstart` does the project setup below for you (virtualenv, dependencies, `.env`) and then validates, tests and runs the demo, with no Neo4j or API key. The Neo4j and OpenAI steps are optional additions (`python scripts/dev.py up`, then `load`) and OpenAI. See [docs/reproducibility.md](docs/reproducibility.md).

Follow these steps in order before starting the Udemy labs.

---

## Prerequisites

- Python 3.11+
- [Neo4j Desktop](https://neo4j.com/download/)
- An [OpenAI API key](https://platform.openai.com/api-keys) (kept in `.env`, never committed)
- Git

---

## Step 1 — Project setup (manual route)

```powershell
cd hc_ontology
.\scripts\setup.ps1
```

Or on macOS/Linux:

```bash
bash scripts/setup.sh
```

Copy and edit environment (the setup scripts do this for you if `.env` is missing):

```bash
cp .env.example .env
```

Set at least `OPENAI_API_KEY` and `NEO4J_PASSWORD`. Never commit `.env`; see [docs/security-and-configuration.md](docs/security-and-configuration.md).

---

## Step 2 — Neo4j

1. Open **Neo4j Desktop** → create/start an instance (name can be `hc`)
2. Open **Databases** tab → note the database name. Neo4j Community Edition has exactly one user database, named `neo4j`; use that name (or run Neo4j with `python scripts/dev.py up` instead of Desktop)
3. Set password on first login
4. Update `.env`:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<your-neo4j-password>
NEO4J_DATABASE=neo4j
```

> **Important:** `NEO4J_DATABASE` is the **database name inside Neo4j**, not the Desktop instance name.

Verify in Browser or:

```http
GET http://127.0.0.1:8000/neo4j/health
```

---

## Step 3 — OpenAI

Ensure `OPENAI_API_KEY` is set in `.env` (Ollama is not used). Verify:

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

Normal — an LLM call can take 1–3 minutes. Wait or use smaller questions for demos.

---

## Capstone exercise

**Question:** *Which patients have hypertension and what treatments do they receive?*

1. `POST /nl-to-cypher` with the question
2. Review generated Cypher
3. `POST /execute-cypher`
4. Compare with `POST /llm-query` (SPARQL path) and `GET /embedding/search?q=hypertension treatment`
