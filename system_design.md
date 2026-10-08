# Healthcare Ontology Platform — System Design & Implementation

This document is the authoritative reference for platform architecture, component design, API surface, data flows, and implementation details. For Neo4j graph schema specifics, see [graph_schema_design.md](graph_schema_design.md).

---

## 1. Overview

The Healthcare Ontology Platform delivers ontology-driven healthcare intelligence using semantic web technologies, graph databases, hosted LLMs (OpenAI), and a LangGraph multi-agent orchestration layer.

### Capabilities

| Layer | Capability |
|-------|------------|
| Ontology | OWL class/individual exploration, RDF triples, graph traversal (Owlready2) |
| SPARQL | Direct RDF/OWL querying (RDFLib) |
| LLM | Natural language → SPARQL / Cypher (OpenAI + LangChain) |
| Neo4j | OWL export, SPARQL→Cypher, NL→Cypher, Cypher execution |
| Embeddings | OpenAI embeddings (`text-embedding-3-small`, 1536-dim) + Neo4j vector index on `OntologyConcept` |
| SHACL | Instance validation with pySHACL (warn/strict modes) |
| Query safety | SPARQL/Cypher validators (safety → syntax → schema → LIMIT) |
| Multi-agent | LangGraph: Memory Load → Planner → Ontology → Query → Validation → HITL → Execution → Abstention → Response |
| Enterprise | Multi-tenancy, RBAC, guardrails, hybrid retrieval, provenance, abstention, LangSmith/OTEL, eval, workflows |
| Documents | GraphRAG: upload → chunk → ground to ontology concepts → retrieve |
| Memory | Four-memory subsystem: **working** (state), **episodic** (turns/events), **procedural** (query templates), **semantic** (concepts + GraphRAG) |

### Technology stack

| Component | Technology |
|-----------|------------|
| API | FastAPI 0.136, Uvicorn |
| Ontology | Owlready2, RDFLib |
| LLM / embeddings | OpenAI (`gpt-4.1-mini`, `text-embedding-3-small`) via LangChain, LangGraph |
| Graph DB | Neo4j 5.x (Bolt, vector index) |
| Validation | pySHACL |
| UI | Streamlit |
| Observability | LangSmith, OpenTelemetry, Prometheus (`/enterprise/metrics`) |
| Tests | pytest |

---

## 2. Architecture

```
                         User / Streamlit UI
                                 │
                                 ▼
                           FastAPI (api.py)
                                 │
     ┌───────────────────────────┼───────────────────────────┐
     │                           │                           │
     ▼                           ▼                           ▼
 HealthcareOntology      SparqlGenerator /           EmbeddingService
 (load_ontology.py)      CypherGenerator                    │
     │                           │                           ▼
     ▼                           ▼                    Neo4j Vector Index
 Owlready2 + RDFLib         OpenAI LLM              (:OntologyConcept)
     │                           │
     ▼                           ▼
 schema + sample data (.ttl)   SPARQL / Cypher
     │                           │
     ▼                           ▼
  SHACL (pySHACL)          Query Validators ──► Neo4j (clinical layer)

  SparqlToCypher ──► Neo4j (Cypher execution)

  /agent/query ──► LangGraph multi-agent (shared AgentState)
       MemoryOrchestrator (working / episodic / procedural / semantic)
       memory_load → Planner → Ontology → Query → Validation ⇄ retry
                → Human Gate (HITL) → Execution → Abstention → Response
                → Neo4j AgentSession / AgentTurn / AgentEvent / Procedure

  /enterprise/* ──► Tenancy, RBAC, guardrails, hybrid retrieval, monitoring
  /documents/*  ──► GraphRAG ingest + grounded retrieval
```

### Request path summary

1. **Direct query** — `POST /sparql` or `POST /execute-cypher` → validator → executor.
2. **LLM query** — NL → generator → validator → executor (sync or async job).
3. **Agent query** — full LangGraph pipeline with retrieval, governance, HITL, memory.
4. **Semantic search** — embed query → Neo4j vector index → ranked concepts.
5. **GraphRAG** — embed query → concepts → traverse `DocumentSection -[:GROUNDS_IN]-> OntologyConcept`.

---

## 3. Project layout

| Path | Role |
|------|------|
| `api.py` | Application factory, router registration, startup hooks |
| `streamlit_app.py` | Course demo UI |
| `ontology/healthcare_schema.ttl` | Domain schema (TBox): the source of truth for the model |
| `data/sample_data.ttl` | Synthetic instances (ABox); merged with the schema at runtime (`core/dataset.py`) |
| `core/` | Config, auth, schemas, SHACL engine, query validators, job store, metrics, rate limiting |
| `services/` | Ontology loading, SPARQL/Cypher generation, Neo4j export, embeddings, document ingest |
| `agents/` | LangGraph state, graph assembly, nodes |
| `agents/memory/` | Four-memory package: working, episodic, procedural, semantic, orchestrator |
| `enterprise/` | Tenancy, RBAC, guardrails, hybrid retrieval, provenance, abstention, observability, workflows |
| `routers/` | HTTP route modules (system, ontology, sparql, neo4j, embedding, shacl, agent, enterprise, documents) |
| `scripts/` | Ontology generation, data seeding, environment setup |
| `shapes/` | SHACL constraint shapes + manifest |
| `data/sample_instances/` | RDF fixtures for SHACL tests |
| `tests/` | pytest suite |
| `k8s/` | Kubernetes deployment manifests |
| `docker_compose.yaml` | Local Docker stack (API + Streamlit; optional Neo4j profile) |
| `graph_schema_design.md` | Neo4j five-layer graph schema reference |

---

## 4. Core services

### 4.1 HealthcareOntology (`services/load_ontology.py`)

- Loads the merged schema + sample data via Owlready2 at startup (`Dataset.load_owlready()`; singleton via `get_ontology()`).
- Exposes classes, individuals, object/data properties, RDF triples.
- `execute_sparql(query)` — RDFLib-backed SPARQL execution.
- (Removed) `export_neo4j_cypher()`: the lossy second exporter. The Neo4j load now comes only from `services/graph_projection.py`.

### 4.2 SparqlGenerator (`services/sparql_generator.py`)

- NL → SPARQL using OpenAI + LangChain prompt with ontology schema context.
- `repair(question, failed_query, error)` — regeneration after validation failure.
- `get_schema()` — classes/properties for validator whitelist.

### 4.3 CypherGenerator (`services/cypher_generator.py`)

- NL → Cypher grounded in OWL class names and relationship patterns.
- `repair()` — same retry contract as SPARQL generator.

### 4.4 SparqlToCypher (`services/sparql_to_cypher.py`)

- Translates a **subset** of SPARQL 1.1 to Cypher (SELECT, basic patterns, filters).
- `execute_cypher(query)` — runs validated Cypher against Neo4j.

### 4.5 Neo4jExporter (`services/neo4j_exporter.py`)

- Synchronizes the **derived** Neo4j projection from the **authoritative** RDF file (`services/graph_projection.py` builds a deterministic `Projection`; the exporter writes it in one scoped transaction after a SHACL gate).
- Identity = IRI (`iri`, unique); `name` is display only. All asserted types and superclasses become labels; multi-valued properties stay lists; class hierarchy is `(:OntologyClass)-[:SUBCLASS_OF]->(:OntologyClass)`.
- Never clears the database; scoped to `Resource`, `OntologyClass`, `ProjectionMeta`. See [docs/semantic-authority-and-graph-projection.md](docs/semantic-authority-and-graph-projection.md).

### 4.6 EmbeddingService (`services/embedding_service.py`)

- Embeds OWL class annotations via OpenAI embeddings (1536-dim by default).
- `sync()` — upserts `:OntologyConcept` nodes + creates vector index `ontology_embeddings`.
- `search_api(query, top_k)` — cosine similarity search.

### 4.7 DocumentIngestor (`services/document_ingestor.py`)

- Parses txt/md/docx/best-effort pdf; chunks with overlap.
- Grounds each chunk to top-k `OntologyConcept` via vector search (`GROUNDS_IN` edges).
- Creates `:Document` / `:DocumentSection` nodes (tenant-scoped).

### 4.8 Dependency injection (`core/dependencies.py`)

All services are `@lru_cache` singletons: `get_ontology()`, `get_sparql_generator()`, `get_cypher_generator()`, `get_sparql_to_cypher()`, `get_neo4j_exporter()`, `get_embedding_service()`, `get_shacl_validator()`.

---

## 5. Neo4j graph model (summary)

Neo4j holds five complementary layers in one database (`NEO4J_DATABASE`). Full schema: [graph_schema_design.md](graph_schema_design.md).

| Layer | Nodes | Created by |
|-------|-------|------------|
| Clinical | `:Patient`, `:Doctor`, `:Diagnosis`, … | `POST /neo4j/load` |
| Semantic | `:OntologyConcept` + vector index | `POST /embedding/sync` |
| Document | `:Document`, `:DocumentSection` | `POST /documents/upload` |
| Episodic | `:AgentSession`, `:AgentTurn`, `:AgentEvent` | Agent `commit_turn()` |
| Procedural | `:AgentProcedure` | Auto-learn from successful agent turns |

**Recommended materialization order:** export → embedding sync → document upload → agent/GraphRAG queries.

---

## 6. Query validation pipeline

Both SPARQL and Cypher pass through staged validators before execution (`core/sparql_validator.py`, `core/cypher_validator.py`).

| Stage | Purpose |
|-------|------|
| Safety | Block `DELETE`, `DETACH DELETE`, `DROP`, `CREATE CONSTRAINT`, `CALL DBMS`, etc. |
| Syntax | Basic structural checks |
| Schema | Whitelist node labels, relationship types, and property names from OWL |
| Limits | Inject/enforce `LIMIT` (default 200), timeout (default 30s) |

Used by: `POST /sparql`, `POST /execute-cypher`, agent validation node, and LLM endpoints after generation.

Metrics counters exposed at `GET /metrics` (`core/metrics.py`).

---

## 7. SHACL validation

### Design split: OWL vs SHACL

| Concern | Layer |
|---------|-------|
| Class hierarchy, reasoning, inferred facts | OWL + reasoner |
| Instance well-formedness (required fields, patterns) | SHACL |
| Business rules (e.g. allergy vs prescription) | SHACL SPARQL constraints |

### Implementation

- Shapes loaded from `shapes/` via `core/shacl_loader.py` (manifest: `shapes/shapes_manifest.ttl`).
- Shared `Person` constraints in `shapes/common/person_shapes.ttl`.
- `ShaclValidator` (`core/shacl_validator.py`) wraps pySHACL.
- Mode: `SHACL_VALIDATION_MODE=warn` (default) or `strict` (warnings fail conformance).
- Reports formatted via `core/shacl_report.py`; last report at `GET /validation/report`.

---

## 8. Multi-agent system (LangGraph)

### 8.1 Graph topology (`agents/graph.py`)

```
START → memory_load → planner → ontology → query → validation
         ↳ (retry) ──────────────┘
         ↳ human_gate → execution → abstention → response → END
         ↳ respond_failed → abstention → END
         ↳ rejected → END
```

- Checkpointer: `MemorySaver` (in-process; keyed by `thread_id`).
- Conditional routing: `route_after_validation`, `route_after_human`.

### 8.2 Shared state (`agents/state.py`)

`AgentState` (TypedDict) fields include:

| Group | Fields |
|-------|--------|
| Identity | `thread_id`, `session_id`, `question`, `tenant_id`, `ontology_id`, `ontology_version`, `user_id` |
| Planner | `plan`, `query_type`, `reasoning`, `require_human_approval`, `max_retries` |
| Memory | `memory_bundle`, `memory_context`, `working_context`, `working_events`, `matched_procedures` |
| Semantic retrieval | `ontology_context`, `retrieved_concepts`, `hybrid_meta`, `retrieval_meta` |
| Governance | `provenance`, `refused`, `refusal_reason`, `confidence`, `abstention_threshold`, `confidence_signals`, `structured_answer` |
| Query | `draft_query`, `query_attempts`, `validated_query` |
| Validation | `validation_ok`, `validation_error`, `validation_stage` |
| HITL | `human_decision`, `human_feedback` |
| Execution | `results`, `execution_error` |
| Response | `answer`, `citations`, `status`, `errors`, `trace`, `cost_usd`, `blocked`, `guardrail_flags` |

`query_type`: `cypher` | `sparql` | `ontology_only`  
`status`: `pending` → `planning` → `retrieving` → `generating` → `validating` → `awaiting_approval` → `executing` → `responding` → `completed` | `failed` | `rejected`

### 8.3 Agent nodes

| Node | File | Responsibility |
|------|------|----------------|
| **Memory load** | `agents/nodes/memory_load.py` | Assemble episodic + procedural context via `MemoryOrchestrator`; seed `working_context` |
| **Planner** | `agents/nodes/planner.py` | LLM JSON plan + query path selection; uses `working_context`; heuristic fallback; HITL flag |
| **Ontology** | `agents/nodes/ontology.py` | Semantic memory enrichment (hybrid retrieve + GraphRAG + schema excerpt) |
| **Query** | `agents/nodes/query.py` | NL → Cypher/SPARQL; procedure template reuse when `match_score >= 0.85`; `repair()` on retry |
| **Validation** | `agents/nodes/validation.py` | Run `SparqlQueryValidator` or `CypherQueryValidator`; route retry/HITL/fail |
| **Human gate** | `agents/nodes/human_gate.py` | LangGraph `interrupt()` when `require_human_approval`; auto-approve otherwise |
| **Execution** | `agents/nodes/execution.py` | Run SPARQL (RDFLib) or Cypher (Neo4j); ontology_only returns retrieved concepts |
| **Abstention** | `agents/nodes/abstention.py` | Calibrated confidence + mandatory provenance check before answering |
| **Response** | `agents/nodes/response.py` | Structured LLM summary, citations, provenance envelope, `commit_turn()` to Neo4j |

### 8.4 Four-memory subsystem (`agents/memory/`)

Coordinated by `MemoryOrchestrator` (`agents/memory/orchestrator.py`).

| Type | Module | Storage | Read | Write |
|------|--------|---------|------|-------|
| **Working** | `working.py` | `AgentState` + LangGraph checkpointer | Compacted `working_context` per turn | `working_events` append-only during turn |
| **Episodic** | `episodic.py` | Neo4j `AgentSession` / `AgentTurn` / `AgentEvent` | Recent session Q/A + keyword similar-episode search | `commit_turn()` after response |
| **Procedural** | `procedural.py` | Neo4j `Procedure` | `match_procedures()` by intent keywords | Auto-learn from successful turns (`confidence >= PROCEDURAL_MIN_CONFIDENCE`) |
| **Semantic** | `semantic.py` | `OntologyConcept` + OWL + `DocumentSection` | `retrieve_semantic_memory()` (hybrid + GraphRAG) | Read-only during turn (materialized elsewhere) |
| **Meta** | `meta_memory.py` | In-process `RecallPlan` + Neo4j `SessionSummary` | `plan_recall()` before assemble; `post_turn()` after commit | Archive old turns; decay stale procedures |

**Lifecycle per agent turn:**

```
POST /agent/query
  → meta_memory.plan_recall()           # score turns, set limits, detect pressure
  → memory_load: assemble_context()     # episodic + procedural (meta-guided)
  → ontology: enrich_semantic()           # semantic bundle
  → planner / query: working_context      # compacted prompt context
  → response: commit_turn()               # episodic persist + procedure learn
  → meta_memory.post_turn()               # archive, optional purge, procedure decay
```

**Working context priority** (`compact_working_context`):

1. Current question  
2. Matched procedures (top 3)  
3. Semantic concepts  
4. Ontology context  
5. Episodic recent + similar episodes  
6. Validation repair context (on retry)

### 8.5 Hybrid retrieval (`enterprise/hybrid_retrieval.py`, `enterprise/retrieval_pipeline.py`)

Used by semantic memory (`agents/memory/semantic.py`).

**Stage 1 — pool (hybrid_retrieve):**
1. Vector search via `EmbeddingService.search_api`.
2. Graph keyword match against OWL class/individual names.
3. Neo4j neighborhood expansion from seed concepts.
4. Reciprocal Rank Fusion (RRF) merge.

**Stage 2 — rerank (`rerank_candidates`):**
- Fuse RRF score (65%) + lexical overlap (35%).

**Stage 3 — error budget (`compute_error_budget`):**
- Pool hit rate, channel counts, top rerank score, residual retrieval risk.

### 8.6 Governance

**Provenance** (`enterprise/provenance.py`): builds evidence paths — query, ontology concepts, result rows, retrieval trace. `mandatory_satisfied` requires query path + ≥1 concept path.

**Abstention** (`enterprise/abstention.py`): weighted confidence from retrieval (18%), retrieval pool (8%), memory coverage (4%), validation (25%), execution (25%), provenance (20%). Refuse if below `AGENT_ABSTENTION_THRESHOLD` (default 0.45) or provenance unsatisfied.

**Guardrails** (`enterprise/guardrails.py`): block prompt injection / dangerous SQL patterns; redact PII (SSN, phone); PHI hints flagged.

**Structured response** (`enterprise/structured_response.py`): JSON schema for `summary`, `facts`, `limitations`, `confidence`.

### 8.7 Episodic & procedural graph model (summary)

```
(:AgentSession {session_id, tenant_id, user_id})
  -[:HAS_TURN]->(:AgentTurn {turn_id, question, answer, validated_query, confidence, ...})
  -[:HAS_EVENT]->(:AgentEvent {event_id, type, payload_json})   // via turn

(:AgentTurn)-[:USED_CONCEPT]->(:OntologyConcept)
(:AgentProcedure)-[:LEARNED_FROM]->(:AgentTurn)
(:AgentProcedure)-[:APPLIES_TO_CONCEPT]->(:OntologyConcept)
```

- `load_context(session_id)` — recent Q/A for planner grounding.
- `search_similar_episodes(question)` — keyword overlap over past successful turns.
- `match_procedures(question)` — lexical match against stored query templates.
- `learn_from_turn(...)` — reinforce or create `Procedure` after high-confidence success.

---

## 9. Enterprise layer

| Module | Purpose |
|--------|---------|
| `tenancy.py` | `TenantContext`; the tenant is the authenticated identity's (a request naming another tenant is refused); in-memory tenant registry |
| `ontology_registry.py` | Multi-ontology versioning (`hc-core` default), publish/activate versions |
| `rbac.py` | Roles: `viewer`, `analyst`, `approver`, `admin`; permission enforcement |
| `guardrails.py` | Input/output safety |
| `hybrid_retrieval.py` | Vector + graph RRF retrieval |
| `retrieval_pipeline.py` | Pool → rerank → error budget |
| `provenance.py` | Mandatory evidence paths |
| `abstention.py` | Calibrated refusal |
| `structured_response.py` | Response schema + LLM prompt |
| `cost.py` | Per-tenant daily cost tracking vs budget |
| `monitoring.py` | Latency, errors, Prometheus text export |
| `observability.py` | LangSmith tracing + OTEL configuration |
| `evaluation.py` | Offline eval cases, governance eval, LangSmith dataset push |
| `workflows.py` | Background jobs: `embedding_refresh`, `hybrid_warmup`, `ontology_health` |

### RBAC roles

| Role | Permissions |
|------|-------------|
| `viewer` | `ontology:read`, `metrics:read` |
| `analyst` | + `agent:run`, `agent:eval` |
| `approver` | + `agent:approve` |
| `admin` | + `ontology:write`, `admin:*`, `workflow:run` |

Identity, role and tenant come from a server-side credential (`X-API-Key` / `Authorization: Bearer`); `X-Role` and `X-Tenant-ID` are never trusted. See [docs/security-architecture.md](docs/security-architecture.md).  
Disable RBAC: `RBAC_ENABLED=false`.

---

## 10. API reference

### 10.1 System — `routers/system.py`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service info |
| GET | `/health` | Health check |
| GET | `/stats` | Ontology counts (classes, individuals, properties) |
| GET | `/metrics` | Validation/LLM counters |
| GET | `/jobs/{id}` | Async job status (LLM, agent, workflow) |

### 10.2 Ontology & domain

| Method | Path | Description |
|--------|------|-------------|
| GET | `/classes`, `/individuals`, … | Ontology metadata (`routers/ontology.py`) |
| GET | `/patients`, `/doctors`, … | Domain resources (`routers/patients.py`, `doctors.py`, `clinical.py`) |
| GET | `/search?q=` | Text search on individual names |

### 10.3 SPARQL — `routers/sparql.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/sparql` | Execute SPARQL (validated) |
| POST | `/llm-query` | NL → SPARQL (recommended) |
| POST | `/nl-query` | Alias (deprecated) |
| POST | `/llm-query/async` | Enqueue NL→SPARQL job |

### 10.4 Neo4j — `routers/neo4j.py`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/neo4j/health` | Neo4j connectivity |
| GET | `/neo4j/export` | The projection rendered as idempotent Cypher MERGE statements (inspection) |
| GET | `/neo4j/projection` | Preview the projection (counts, fingerprint, not-projected notes); no database access |
| POST | `/neo4j/load` | Synchronize the Neo4j projection from the RDF (SHACL-gated, idempotent, scoped; 422 on invalid RDF) |

`POST /neo4j/seed-demo` was removed: it ran a whole-database `DETACH DELETE`. Development seeding is `scripts/seed_neo4j_demo.py --yes`.
| POST | `/sparql-to-cypher` | SPARQL → Cypher → execute |
| POST | `/nl-to-cypher` | NL → Cypher → execute |
| POST | `/nl-to-cypher/async` | Enqueue NL→Cypher job |
| POST | `/execute-cypher` | Run Cypher (validated) |

### 10.5 Embeddings — `routers/embedding.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/embedding/sync` | Sync OWL classes → Neo4j vectors |
| GET | `/embedding/health` | Embedding model health |
| GET | `/embedding/search?query=&top_k=` | Semantic concept search |
| GET | `/embedding/similar/{concept}?top_k=` | Similar concepts |

### 10.6 SHACL — `routers/shacl.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/validate` | Validate inline RDF |
| POST | `/validate/file` | Validate uploaded OWL/RDF file |
| POST | `/validate/ontology` | Validate project OWL file |
| GET | `/validation/report` | Last report (`?format=html`) |
| GET | `/validation/health` | SHACL engine health |

### 10.7 Multi-agent — `routers/agent.py`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/agent/health` | Graph + feature flags |
| POST | `/agent/query` | Full pipeline (may pause for HITL) |
| POST | `/agent/query/async` | Background run → poll `/agent/jobs/{id}` |
| POST | `/agent/resume` | Approve/reject paused execution (`decision`, `feedback`) |
| GET | `/agent/state/{thread_id}` | Inspect checkpointed state |
| GET | `/agent/memory/episodes/search?q=` | Similar past turns (tenant-scoped) |
| GET | `/agent/memory/procedures?q=` | Matched procedural templates |
| GET | `/agent/memory/{session_id}` | Session conversation context |
| GET | `/agent/jobs/{id}` | Async agent job status |

**Agent request body (`AgentQueryRequest`):**

```json
{
  "question": "List patients with hypertension",
  "session_id": "optional-uuid",
  "thread_id": "optional-uuid",
  "require_human_approval": null,
  "max_retries": 3,
  "query_type": "cypher",
  "ontology_id": "hc-core",
  "ontology_version": null
}
```

**HITL resume (`AgentResumeRequest`):**

```json
{
  "thread_id": "uuid-from-query-response",
  "decision": "approved",
  "feedback": "optional reviewer note"
}
```

### 10.8 Documents (GraphRAG) — `routers/documents.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/documents/upload` | Upload txt/md/docx/pdf; chunk + ground to concepts |
| POST | `/documents/graphrag/retrieve` | Query → concepts → grounded document sections |

### 10.9 Enterprise — `routers/enterprise.py`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/enterprise/health` | Capabilities + observability status |
| GET | `/enterprise/tenants` | Tenant catalog |
| POST | `/enterprise/tenants` | Create tenant |
| GET | `/enterprise/ontologies` | Tenant-scoped ontology list |
| GET | `/enterprise/ontologies/{id}` | Ontology detail |
| POST | `/enterprise/ontologies/{id}/versions` | Publish version |
| POST | `/enterprise/ontologies/{id}/activate/{version}` | Activate version |
| POST | `/enterprise/hybrid-search` | Hybrid retrieval API |
| POST | `/enterprise/guardrails/check` | Test input guardrails |
| GET | `/enterprise/cost` | Per-tenant cost vs budget |
| GET | `/enterprise/monitoring` | Alerts + latency snapshot |
| GET | `/enterprise/metrics` | Prometheus scrape endpoint |
| GET | `/enterprise/workflows` | List workflow names |
| POST | `/enterprise/workflows/run` | Enqueue background workflow |
| POST | `/enterprise/eval/run` | Offline planner + guardrail eval |
| POST | `/enterprise/eval/governance` | Retrieval + provenance + abstention eval |
| POST | `/enterprise/eval/langsmith-dataset` | Push eval cases to LangSmith |
| GET | `/enterprise/jobs/{id}` | Workflow job status |

---

## 11. Data flows

### NL → Answer (Cypher path)

```
Question → CypherGenerator → CypherValidator → Neo4j → JSON results
```

### NL → Answer (SPARQL path)

```
Question → SparqlGenerator → SparqlValidator → RDFLib → JSON results
```

### NL → Answer (Agent path)

```
Question
  → Guardrails + cost budget check
  → memory_load (episodic + procedural assemble)
  → Planner (query_type, HITL flag; uses working_context)
  → Ontology (semantic memory: hybrid retrieve + GraphRAG + schema)
  → Query (grounded NL → Cypher/SPARQL; procedure template if high match)
  → Validation (retry loop up to max_retries)
  → Human gate (interrupt if required)
  → Execution
  → Abstention (confidence + provenance + memory_coverage)
  → Response (structured answer + commit_turn: episodic + procedural learn)
```

### Semantic search

```
OWL class annotations → OpenAI embed → Neo4j OntologyConcept nodes
Query text → embed → vector index → ranked concepts
```

### GraphRAG

```
Upload → chunk → embed chunk → vector match OntologyConcept → GROUNDS_IN edges
Query → embed → top concepts → traverse to DocumentSection → ranked evidence
```

### Async jobs (`core/job_store.py`)

Thread-pool executor (2 workers). Job states: `queued` → `running` → `completed` | `failed`.  
Used by: `/llm-query/async`, `/nl-to-cypher/async`, `/agent/query/async`, `/enterprise/workflows/run`.

---

## 12. Security & authentication

| Mechanism | Config | Behavior |
|-----------|--------|----------|
| API key | `API_KEY` env | `X-API-Key` header; empty = auth disabled (local dev) |
| RBAC | `RBAC_ENABLED` | Role-based permissions on agent/enterprise routes |
| Guardrails | `GUARDRAILS_ENABLED` | Input/output filtering on agent routes |
| Rate limiting | `LLM_RATE_LIMIT_PER_MINUTE` | Sliding window per client/tenant on LLM and agent endpoints |
| Query safety | Validators | Read-only Cypher/SPARQL; schema whitelist |
| Cost budget | `COST_BUDGET_USD_PER_DAY` | Per-tenant daily spend cap on agent runs |

---

## 13. Configuration

All settings loaded from `.env` via `core/config.py`.

### Application

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_NAME` | Healthcare Ontology API | Service title |
| `APP_VERSION` | 1.0.0 | Version string |
| `ENVIRONMENT` | development | Environment label |
| `DEBUG` | false | Uvicorn reload |
| `LOG_LEVEL` | INFO | Logging level |
| `API_BASE_URL` | http://127.0.0.1:8000 | Streamlit → API URL |
| `API_KEY` | (empty) | Optional request authentication |

### Ontology & SHACL

| Variable | Default | Purpose |
|----------|---------|---------|
| `ONTOLOGY_SCHEMA_FILE` | ontology/healthcare_schema.ttl | Schema file |
| `SAMPLE_DATA_FILE` | data/sample_data.ttl | Sample data file (empty = schema only) |
| `SHAPES_DIR` | shapes/ | SHACL shapes directory |
| `DATA_DIR` | data/ | Data directory |
| `VALIDATION_REPORTS_DIR` | validation_reports/ | Report output |
| `SHACL_VALIDATION_MODE` | warn | `warn` or `strict` |

### OpenAI / LLM (see docs/security-and-configuration.md)

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENAI_MODEL` | gpt-4.1-mini | LLM for generation |
| `OPENAI_EMBEDDING_MODEL` | text-embedding-3-small | Embedding model |
| `OPENAI_API_KEY` | (none - required) | OpenAI credential; never commit |

### Neo4j

| Variable | Default | Purpose |
|----------|---------|---------|
| `NEO4J_URI` | bolt://localhost:7687 | Bolt URI |
| `NEO4J_USERNAME` | neo4j | Username |
| `NEO4J_PASSWORD` | (empty) | Password |
| `NEO4J_DATABASE` | neo4j | **Database name** (not instance name) |

### Query execution

| Variable | Default | Purpose |
|----------|---------|---------|
| `QUERY_DEFAULT_LIMIT` | 200 | Max rows per query |
| `QUERY_TIMEOUT_SECONDS` | 30 | Query timeout |
| `QUERY_CACHE_TTL_SECONDS` | 300 | In-memory query cache TTL |
| `LLM_RATE_LIMIT_PER_MINUTE` | 10 | LLM/agent rate limit |

### Agent

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT_MAX_RETRIES` | 3 | Validation retry limit |
| `AGENT_FORCE_HITL` | false | Force human approval for all executable queries |
| `AGENT_ABSTENTION_THRESHOLD` | 0.45 | Minimum confidence to answer |
| `AGENT_RETRIEVAL_POOL_SIZE` | 16 | Hybrid retrieval pool size |
| `AGENT_RETRIEVAL_TOP_K` | 8 | Post-rerank concept count |
| `AGENT_STRUCTURED_LLM` | true | Use LLM for structured response |

### Memory subsystem

| Variable | Default | Purpose |
|----------|---------|---------|
| `WORKING_MEMORY_MAX_CHARS` | 6000 | Max compacted working context size |
| `EPISODIC_CONTEXT_TURNS` | 5 | Recent turns loaded per session |
| `EPISODIC_SIMILAR_TOP_K` | 3 | Similar past episodes to include |
| `PROCEDURAL_MATCH_THRESHOLD` | 0.35 | Minimum lexical score to list a procedure |
| `PROCEDURAL_AUTO_LEARN` | true | Auto-create/reinforce procedures on success |
| `PROCEDURAL_MIN_CONFIDENCE` | 0.7 | Min confidence to learn a procedure |
| `SEMANTIC_ENABLE_GRAPH_RAG` | true | Include document sections in semantic memory |
| `META_MEMORY_ENABLED` | true | Enable meta-memory recall/archive/decay |
| `META_MEMORY_RETAIN_THRESHOLD` | 0.35 | Min turn score to include in hot recall |
| `META_MEMORY_SESSION_ARCHIVE_TURNS` | 15 | Archive when session exceeds this turn count |
| `META_MEMORY_KEEP_RECENT_TURNS` | 5 | Hot turns kept after archival |
| `META_MEMORY_PURGE_FAILED` | false | Delete failed turns after TTL (off by default) |
| `META_MEMORY_FAILED_TTL_HOURS` | 24 | TTL for failed-turn purge |
| `META_MEMORY_PROCEDURE_DECAY_DAYS` | 30 | Mark unused procedures stale |
| `MEMORY_DEBUG_CONTEXT` | false | Print before/after memory snapshots to API terminal |
| `MEMORY_DEBUG_CONTEXT_FULL` | false | With debug on, use longer context previews (4× truncate limits) |

### Enterprise

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEFAULT_TENANT_ID` | default | Default tenant |
| `RBAC_ENABLED` | true | Role enforcement |
| `GUARDRAILS_ENABLED` | true | Input/output guardrails |
| `COST_BUDGET_USD_PER_DAY` | 25 | Per-tenant daily budget |
| `LANGCHAIN_TRACING_V2` | false | LangSmith tracing |
| `LANGCHAIN_API_KEY` | (empty) | LangSmith API key |
| `LANGCHAIN_PROJECT` | healthcare-ontology-agents | LangSmith project |
| `LANGSMITH_ENDPOINT` | https://api.smith.langchain.com | LangSmith endpoint |
| `OTEL_ENABLED` | false | OpenTelemetry export |
| `OTEL_SERVICE_NAME` | healthcare-ontology-api | OTEL service name |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | (empty) | OTLP collector URL |

---

## 14. Deployment

### Local development

```bash
uvicorn api:app --reload --host 127.0.0.1 --port 8000
streamlit run streamlit_app.py
```

### Docker Compose

```bash
docker compose -f docker_compose.yaml up --build
```

```
Docker Compose
├── api:8000
└── streamlit:8501

Neo4j Desktop (host) :7687  ← bolt://host.docker.internal
```

Optional Neo4j container: `docker compose --profile neo4j up`

### Kubernetes (`k8s/deployment.yaml`)

- Namespace: `healthcare-ontology`
- Deployment: 2 replicas, HPA 2–8 pods (CPU 70%)
- ConfigMap + Secret for env vars
- Readiness: `/health`; Liveness: `/enterprise/health`
- Prometheus scrape: `/enterprise/metrics`
- Ingress: `healthcare-ontology.local` (300s proxy timeout for LLM)

### CI/CD

- **CI** (`.github/workflows/ci.yml`): pytest, enterprise smoke import, optional mypy, Docker build
- **CD** (`.github/workflows/cd.yml`): deployment pipeline

---

## 15. Testing

```bash
pytest tests/ -v
```

| Test module | Coverage |
|-------------|----------|
| `test_api.py` | Core API endpoints |
| `test_api_validation.py` | Request validation |
| `test_query_validation.py` | SPARQL/Cypher validators |
| `test_cypher_generation.py` | Cypher generator |
| `test_shacl_validation.py` | SHACL engine |
| `test_patient_shapes.py`, `test_doctor_shapes.py` | Shape-specific fixtures |
| `test_agent_graph.py` | LangGraph assembly + routing |
| `test_memory.py` | Four-memory compaction and memory_load node |
| `test_enterprise.py` | Enterprise modules |
| `test_governance.py` | Provenance, abstention, guardrails |

Fixtures: `data/sample_instances/` (valid/invalid TTL graphs).  
CI disables RBAC/OTEL; enables guardrails.

---

## 16. Known limitations

| Area | Limitation |
|------|------------|
| SPARQL→Cypher | Subset of SPARQL 1.1 only (no full compliance) |
| LLM endpoints | Synchronous paths slow (1–3 min); use async jobs for production |
| Embedding sync | Full-batch, not incremental |
| `nl-query` | Deprecated in favor of `llm-query` |
| Agent checkpointer | In-memory `MemorySaver` — not durable across restarts (working memory) |
| Episodic similarity | Keyword overlap only — no turn embedding index yet |
| Procedure learning | Auto-learns from successful turns only; no manual curation UI |
| OntologyConcept vs clinical | `:OntologyConcept` (class embeddings) not linked to `:Patient` individuals |
| Document PDF | Best-effort extraction; scanned PDFs may yield empty chunks |
| Multi-tenancy | OntologyConcept and clinical layers are global per Neo4j database |
| Job store | In-process thread pool — not distributed |

---

## 17. Related documentation

| Document | Content |
|----------|---------|
| [graph_schema_design.md](graph_schema_design.md) | Neo4j five-layer schema (clinical, semantic, document, episodic, procedural) |
| [docs/YOUTUBE_MEMORY_LAYER_SCRIPT.md](docs/YOUTUBE_MEMORY_LAYER_SCRIPT.md) | YouTube scripts: 3 × 60 min on four-memory layer |
| [readme.md](readme.md) | Quick start, troubleshooting |
| [COURSE_SETUP.md](COURSE_SETUP.md) | Student environment setup |
| [COURSE_STRUCTURE.md](COURSE_STRUCTURE.md) | Udemy module outline |
| [examples/requests.http](examples/requests.http) | Sample HTTP requests |
