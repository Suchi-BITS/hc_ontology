# Udemy Video Script: Graph Algorithms in the Healthcare Ontology Platform

**Duration:** ~30 minutes (single session or 2 × 15 min)  
**Project:** `hc_ontology/`  
**Prerequisite:** Neo4j export + embedding sync modules

**Related:** [UDEMY_REASONING_SCRIPT.md](UDEMY_REASONING_SCRIPT.md), [graph_schema_design.md](../graph_schema_design.md)

---

## What this app uses (and what it does not)

This platform is a **healthcare knowledge graph + GraphRAG + agent** stack. It uses **practical retrieval and traversal algorithms**, not the full Neo4j Graph Data Science (GDS) catalog.

| Algorithm family | Used here? | Where |
|------------------|------------|-------|
| k-NN / vector similarity (cosine) | ✅ | Neo4j vector index, `embedding_service.py` |
| Reciprocal Rank Fusion (RRF) | ✅ | `enterprise/hybrid_retrieval.py` |
| Keyword overlap scoring | ✅ | `_graph_keyword_hits()` |
| 1-hop neighborhood expansion | ✅ | `_graph_neighborhood()` |
| Multi-hop pattern matching | ✅ | Cypher, SPARQL→Cypher, SHACL SPARQL |
| Backward graph join (GraphRAG) | ✅ | `document_ingestor.py` |
| In-memory property-graph traversal | ✅ | `load_ontology.py` |
| Top-K / rank & sort | ✅ | Every search endpoint |
| Sliding-window text chunking | ✅ | `document_ingestor.chunk_text()` |
| PageRank, shortest path, community detection | ❌ | Not in repo |
| Explicit BFS/DFS library | ❌ | Only implicit loops / Cypher |

---

## MINUTE 0–3 — Hook & algorithm map

**[ON SCREEN]** Architecture diagram from `graph_schema_design.md` — four Neo4j layers.

**NARRATION**

> Students often ask: “Does this course use PageRank or community detection?”  
> **No.** We use algorithms that power **semantic search, hybrid retrieval, clinical path queries, and GraphRAG**—the patterns you’ll ship in ontology-backed products first.
>
> Today’s map:
> 1. **Vector k-NN** — find similar ontology concepts  
> 2. **RRF** — fuse vector + graph signals  
> 3. **Neighborhood expansion** — one hop in Neo4j  
> 4. **Multi-hop MATCH** — clinical questions over paths  
> 5. **Backward GraphRAG join** — concepts → document chunks  
> 6. **Python traversals** — walk OWL object properties in memory  

**[DEMO]** Open Swagger → `/embedding/search`, `/enterprise/hybrid-search`, `/documents/graphrag/retrieve`.

---

## MINUTE 3–10 — Algorithm 1: k-NN vector search (cosine similarity)

**Learning objective:** Explain approximate nearest-neighbor search over `OntologyConcept` embeddings.

**NARRATION**

> Given a query string, we embed it with Ollama `nomic-embed-text` (768 dimensions), then find the **top-k nearest** ontology concept nodes in Neo4j.
>
> Neo4j’s vector index uses an **HNSW** (Hierarchical Navigable Small World) structure internally—an approximate k-NN algorithm optimized for speed at scale. We call it via Cypher, not by implementing HNSW ourselves.

**[ON SCREEN — CODE]** `services/embedding_service.py`

```python
VECTOR_INDEX_NAME = "ontology_embeddings"
VECTOR_DIMENSIONS = 768
VECTOR_SIMILARITY = "cosine"
```

```cypher
CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
YIELD node, score
RETURN node.name AS name, score
ORDER BY score DESC
```

**Pipeline:**

```
Query text → Ollama embed → db.index.vector.queryNodes → top-k concepts
```

**[ON SCREEN — CODE]** `generate_embedding()` → `similarity_search()` → `search_api()`

**[DEMO]**

```http
POST /embedding/sync
GET  /embedding/search?query=diabetes&top_k=5
GET  /embedding/similar/Diagnosis?top_k=5
```

**Teaching points**

- **Cosine similarity** measures angle between vectors (good for text embeddings).  
- Score is **similarity**, not distance—higher = closer.  
- Same algorithm grounds uploaded documents: each chunk embedded, top-k concepts linked via `GROUNDS_IN`.

**[ON SCREEN — CODE]** Document grounding loop in `services/document_ingestor.py`:

```python
groundings = embedding_service.similarity_search_detailed(chunk_text_value, top_k=...)
# MERGE (s)-[:GROUNDS_IN {confidence_score: score}]->(c:OntologyConcept)
```

---

## MINUTE 10–17 — Algorithms 2–4: Hybrid retrieval (RRF + keyword + neighborhood)

**Learning objective:** Understand how the agent fuses multiple retrieval channels.

**NARRATION**

> One signal is rarely enough. The **enterprise hybrid retriever** runs three channels, then **fuses rankings** with Reciprocal Rank Fusion (RRF).

### Channel A — Vector k-NN (again)

From `hybrid_retrieve()` → `embedding_service.search_api()`.

### Channel B — Keyword overlap scoring

**[ON SCREEN — CODE]** `enterprise/hybrid_retrieval.py` → `_graph_keyword_hits()`

```python
tokens = [t for t in q.split() if len(t) > 2]
for name in classes + individuals:
    score = sum(1.0 for t in tokens if t in name.lower())
    score = score / max(len(tokens), 1)
```

> Not a classic graph algorithm—it’s **schema-aware lexical matching** over ontology entity names. Cheap, interpretable, complements vectors when the user types exact terms like “Prescription” or “Diabetes”.

### Channel C — 1-hop neighborhood expansion

**[ON SCREEN — CODE]** `_graph_neighborhood()`

```cypher
MATCH (n) WHERE n.name = 'Diagnosis'
OPTIONAL MATCH (n)-[r]-(m)
RETURN n.name AS source, type(r) AS rel, m.name AS neighbor
LIMIT 10
```

> **Algorithm:** fixed-depth **1-hop expansion** from seed nodes (vector + keyword hits). Explores adjacent clinical entities to enrich agent context—lightweight graph exploration, not full BFS to arbitrary depth.

### Fusion — Reciprocal Rank Fusion (RRF)

**[ON SCREEN — CODE]**

```python
# Reciprocal rank fusion
for rank, hit in enumerate(vector_hits):
    scores[name] = scores.get(name, 0.0) + 1.0 / (60 + rank)
for rank, hit in enumerate(graph_hits + neighborhood):
    scores[name] = scores.get(name, 0.0) + 1.0 / (60 + rank)
ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
```

**NARRATION**

> **RRF** combines ranked lists without normalizing incompatible scores (vector cosine vs keyword counts). Formula: score += `1 / (k + rank)` with **k = 60** (common default from fusion literature).
>
> Concepts appearing in **multiple channels** get boosted—exactly what you want for agent grounding.

**[DEMO]**

```http
POST /enterprise/hybrid-search
Content-Type: application/json

{"query": "patients with diabetes medications", "top_k": 8}
```

**[ON SCREEN]** Show response `channels.vector`, `channels.graph`, `channels.neighborhood`, fused `results` with `rrf_score`.

**[ON SCREEN — CODE]** Consumer: `agents/nodes/ontology.py` → `hybrid_retrieve(question, top_k=8)` builds `ontology_context` for the query agent.

---

## MINUTE 17–23 — Algorithms 5–6: Multi-hop patterns & GraphRAG backward join

### Multi-hop fixed-path matching (Cypher)

**Learning objective:** Recognize subgraph matching as the workhorse “graph algorithm” for clinical queries.

**NARRATION**

> Neo4j doesn’t run Dijkstra here—we declare a **path pattern** and the engine finds bindings. That’s **subgraph pattern matching** ( homomorphism search on labeled property graphs).

**Canonical 3-hop path** (diabetes + medications):

```cypher
MATCH (p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis {diagnosisName: 'Diabetes'}),
      (rx:Prescription)-[:PRESCRIBEDFOR]->(p),
      (rx)-[:CONTAINSMEDICATION]->(m:Medication)
RETURN p.name, d.diagnosisName, m.medicationName
LIMIT 50
```

**2-hop Python traversal** (patient → diagnosis → treatment):

**[ON SCREEN — CODE]** `services/load_ontology.py` → `get_patient_treatments()`

```python
for diagnosis in patient.hasDiagnosis:
    for treatment in diagnosis.requiresTreatment:
        treatments.append({"diagnosis": diagnosis.name, "treatment": treatment.name})
```

**[DEMO]**

```http
GET /patients/PatientJohn/treatments
POST /nl-to-cypher  →  POST /execute-cypher
```

**SPARQL side:** `services/sparql_to_cypher.py` parses triple patterns and emits chained `MATCH` clauses—same underlying **pattern matching** idea over RDF-shaped queries.

### GraphRAG: backward join (vector → graph filter → top-K sort)

**Learning objective:** Two-stage retrieval over the document layer.

**NARRATION**

> GraphRAG here is **not** a random walk algorithm. It’s a **pipeline**:

```
1. k-NN on query        → top ontology concepts
2. Graph join backward  → DocumentSections linked via GROUNDS_IN
3. Sort by score        → top-k sections
```

**[ON SCREEN — CODE]** `retrieve_grounded_document_sections()` in `document_ingestor.py`

```cypher
MATCH (ds:DocumentSection {tenant_id: $tenant_id})-[r:GROUNDS_IN]->(c:OntologyConcept)
WHERE c.name IN $concept_names
RETURN ds.content, c.name, r.confidence_score AS grounding_score
ORDER BY grounding_score DESC
LIMIT $limit
```

**[DEMO]** Upload a `.txt` clinical note → `POST /documents/graphrag/retrieve`.

**Chunking prerequisite** (feeds the graph): sliding-window algorithm in `chunk_text()`—window size 1500, overlap 200, step = `chunk_size - overlap`.

---

## MINUTE 23–27 — Algorithms 7–8: In-memory traversal & materialization order

### In-memory adjacency traversal (Owlready2)

**[ON SCREEN — CODE]** `get_doctor_patients()` — nested loops over all `Diagnosis` instances:

```python
for diagnosis in Diagnosis.instances():
    if doctor in diagnosis.diagnosedBy:
        for patient in diagnosis.diagnosisForPatient:
            patients.append(...)
```

> **Algorithm character:** brute-force scan + **local edge traversal** over object properties. Complexity ~O(individuals × degree)—fine for course-scale ontologies.

Also: `get_rdf_triples()` iterates every individual × every property—full **edge listing** for `/rdf/triples`.

### Three-pass graph materialization (ETL ordering)

**[ON SCREEN — CODE]** `services/neo4j_exporter.py`

```
Pass 1: MERGE nodes (by label + name)
Pass 2: SET data properties
Pass 3: MERGE relationships
```

> Ordering ensures relationship endpoints exist before edges are created—a **topological dependency order** for loading, not graph analytics.

**MERGE** gives **idempotent deduplication** by merge key (`name`)—re-export doesn’t duplicate nodes.

---

## MINUTE 27–30 — Recap, quiz & extension lab

### Summary slide

| # | Algorithm | Purpose | File / API |
|---|-----------|---------|------------|
| 1 | k-NN (HNSW + cosine) | Semantic concept search | `embedding_service.py`, `/embedding/search` |
| 2 | RRF (k=60) | Fuse vector + graph rankings | `hybrid_retrieval.py`, `/enterprise/hybrid-search` |
| 3 | Token overlap score | Lexical schema match | `_graph_keyword_hits()` |
| 4 | 1-hop expansion | Neighbor context | `_graph_neighborhood()` |
| 5 | Multi-hop pattern match | Clinical path queries | Cypher, `load_ontology.py` |
| 6 | Backward join + top-K sort | GraphRAG document retrieval | `document_ingestor.py` |
| 7 | Sliding-window chunking | Build document sections | `chunk_text()` |
| 8 | Adjacency traversal | REST API graph walks | `load_ontology.py` |
| 9 | Three-pass MERGE load | OWL → Neo4j export | `neo4j_exporter.py` |

### What we deliberately omit (extension ideas)

- **PageRank** — rank influential concepts or doctors  
- **Shortest path** — care pathway length between diagnosis and treatment  
- **Community detection** — cluster patients by comorbidity subgraph  
- **Betweenness** — find bridge departments in hospital structure (`add_data.py` hospital tree)

Suggest **Neo4j GDS** plugin for a bonus module.

### Quick quiz

1. What similarity metric does our vector index use?  
2. Why RRF instead of averaging vector and keyword scores?  
3. How many hops in the diabetes→medication Cypher example?  
4. Name the three hybrid retrieval channels.  
5. Is GraphRAG backward join the same as PageRank? (No—explain.)

### 5-minute hands-on

```http
POST /embedding/sync
GET  /embedding/search?query=hypertension&top_k=5
POST /enterprise/hybrid-search     {"query":"hypertension treatment"}
POST /neo4j/seed-demo
POST /execute-cypher               (diabetes 3-hop query)
POST /documents/upload             (short clinical txt)
POST /documents/graphrag/retrieve  {"query":"diabetes medication"}
POST /agent/query                  {"question":"List patients with diabetes","session_id":"algo-demo-1"}
```

Inspect agent trace: `ontology:hybrid=N` in response / `/agent/state/{thread_id}`.

---

## Recording notes

- Split screen: **Neo4j Browser** (path visual) + **VS Code** (algorithm source).  
- When showing vector search, mention index must exist (`POST /embedding/sync` first).  
- Contrast **approximate k-NN** (fast, semantic) vs **exact multi-hop MATCH** (structured, precise).  
- Avoid overclaiming: RRF comment in code says `RRF-ish`—scores are simplified fusion, good for teaching.  
- Link forward to reasoning module: multi-hop Cypher = graph **reasoning**; k-NN = **retrieval**.

### Repository map

| Algorithm | Primary files |
|-----------|---------------|
| Vector k-NN | `services/embedding_service.py`, `routers/embedding.py` |
| Hybrid RRF | `enterprise/hybrid_retrieval.py`, `routers/enterprise.py` |
| GraphRAG | `services/document_ingestor.py`, `routers/documents.py` |
| Multi-hop Cypher | `services/cypher_generator.py`, `services/seed_demo_data.py` |
| OWL traversals | `services/load_ontology.py`, `routers/patients.py`, `routers/doctors.py` |
| Pattern translation | `services/sparql_to_cypher.py` |
| Agent orchestration | `agents/nodes/ontology.py`, `agents/graph.py` |
