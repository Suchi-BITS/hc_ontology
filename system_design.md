# system_design_document.md

# Healthcare Ontology Platform – System Design Document

## 1. Overview

The Healthcare Ontology Platform provides ontology-driven healthcare intelligence using semantic technologies, graph databases, and local large language models.

The system supports:

* Ontology exploration
* RDF/SPARQL querying
* Natural language question answering
* Neo4j graph export
* SPARQL-to-Cypher translation
* Semantic vector search using embeddings

---

# 2. High-Level Architecture

```
                        User
                          │
                          ▼
                     FastAPI APIs
                          │
     ┌────────────────────┼─────────────────────┐
     │                    │                     │
     ▼                    ▼                     ▼
HealthcareOntology   SparqlGenerator   EmbeddingService
     │                    │                     │
     ▼                    ▼                     ▼
 Owlready2           Ollama Qwen         Ollama Embeddings
     │                    │                     │
     ▼                    ▼                     ▼
 healthcare.owl       SPARQL Query          Neo4j XC
     │                    │                     │
     ▼                    ▼                     ▼
   RDFLib            RDF Execution        Vector Search
```

---

# 3. Core Components

## 3.1 Ontology Layer

File:

```
load_ontology.py
```

Responsibilities:

* Load OWL ontology
* Extract classes
* Extract object properties
* Extract individuals
* Execute SPARQL
* Perform graph traversal

Technology:

* Owlready2
* RDFLib

---

## 3.2 API Layer

File:

```
api.py
```

Responsibilities:

* Expose REST endpoints
* Swagger documentation
* Integrate ontology services
* Integrate embeddings

Technology:

* FastAPI
* Pydantic

---

## 3.3 Natural Language Layer

File:

```
sparql_generator.py
```

Responsibilities:

* Generate SPARQL from English questions
* Validate generated SPARQL
* Repair invalid queries

Technology:

* LangChain
* Ollama
* Qwen

Pipeline:

```
Question
↓
Prompt Construction
↓
Ollama
↓
SPARQL
↓
Validation
↓
Repair
```

---

## 3.4 Knowledge Graph Layer

File:

```
healthcare_ontology.owl
```

Contains:

Classes:

* Patient
* Doctor
* Diagnosis
* Treatment
* Appointment

Object Properties:

* hasDiagnosis
* diagnosedBy
* requiresTreatment

Data Properties:

* firstName
* lastName
* bloodGroup

---

## 3.5 Neo4j Integration

Files:

```
neo4j_exporter.py
sparql_to_cypher.py
```

Responsibilities:

* RDF → Cypher export
* SPARQL → Cypher translation
* Neo4j connectivity

---

## 3.6 Embedding Layer

File:

```
embedding_service.py
```

Responsibilities:

* Annotation extraction
* Embedding generation
* Vector storage
* Similarity search

Pipeline:

```
OWL
↓
Annotation Extraction
↓
Ollama nomic-embed-text
↓
Neo4j Vector Index
↓
Similarity Search
```

---

# 4. API Categories

System APIs

* /
* /health
* /stats

Ontology APIs

* /classes
* /individuals
* /object-properties
* /data-properties

Domain APIs

* /patients
* /doctors
* /appointments
* /diagnoses
* /treatments

Knowledge Graph APIs

* /rdf/triples
* /graph-summary

SPARQL APIs

* /sparql
* /nl-query
* /llm-query

Neo4j APIs

* /neo4j/export
* /sparql-to-cypher

Embedding APIs

* /embedding/search
* /embedding/similar

---

# 5. Deployment Architecture

```
                Docker Compose
                        │
      ┌─────────────────┼─────────────────┐
      │                 │                 │
      ▼                 ▼                 ▼
 FastAPI           Neo4j             Ollama
   8000             7687              11434
```

---

# 6. Future Improvements

* Split api.py into routers
* Add authentication
* Add caching
* Add CI/CD pipeline
* Add automated testing
* Add ontology versioning

---

# 7. Risks

* Large prompts may slow SPARQL generation.
* Neo4j and RDF models require translation.
* Duplicate FastAPI routes can cause conflicts.
* Embedding synchronization should be incremental.
