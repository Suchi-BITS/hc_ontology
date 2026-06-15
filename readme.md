# README.md

# Healthcare Ontology Platform

Ontology-powered healthcare intelligence using FastAPI, Owlready2, Ollama, Neo4j, and SPARQL.

---

## Features

* Healthcare ontology management
* RDF/SPARQL querying
* Natural language to SPARQL generation
* Neo4j export
* SPARQL-to-Cypher translation
* Semantic vector search
* Local LLM inference using Ollama

---

## Tech Stack

Backend:

* FastAPI

Knowledge Graph:

* Owlready2
* RDFLib

LLMs:

* Ollama
* Qwen2.5
* Llama

Vector Search:

* Ollama nomic-embed-text
* Neo4j Vector Indexes

Graph Database:

* Neo4j

---

## Installation

Clone repository:

```bash
git clone <repo>
cd healthcare_ontology
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Ollama Setup

Install Ollama.

Pull required models:

```bash
ollama pull qwen2.5
ollama pull nomic-embed-text
```

Start Ollama:

```bash
ollama serve
```

---

## Neo4j Setup

Create database:

```
XC
```

Update `.env`:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<password>
NEO4J_DATABASE=XC
```

---

## Running FastAPI

```bash
uvicorn api:app --reload
```

Swagger UI:

```
http://localhost:8000/docs
```

---

## Key Endpoints

Health:

```
GET /health
```

Patients:

```
GET /patients
```

SPARQL:

```
POST /sparql
```

Natural Language:

```
POST /nl-query
```

Neo4j Export:

```
GET /neo4j/export
```

Embeddings:

```
GET /embedding/search
```

---

## Project Structure

```
healthcare_ontology/
├── api.py
├── load_ontology.py
├── sparql_generator.py
├── sparql_to_cypher.py
├── embedding_service.py
├── neo4j_exporter.py
├── generate_hc_ontology.py
├── healthcare_ontology.owl
├── requirements.txt
└── docker_compose.yaml
```

---

## Recommended Improvements

* Remove venv from repository.
* Split FastAPI routers.
* Add unit tests.
* Add Dockerfiles.
* Add GitHub Actions.
* Introduce authentication.

---

## License

Internal project.
SELECT ?patient WHERE { ?patient rdf:type :Patient . ?patient hc:hasDiagnosis ?d }