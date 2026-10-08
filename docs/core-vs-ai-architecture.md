# Core versus AI: how the agent layer builds on the semantic foundation

*A reader should be able to learn ontologies, RDF, SHACL, SPARQL and knowledge graphs from this project without ever installing an LLM library. The AI layer is a later chapter that consumes what the earlier chapters built. It is not a prerequisite for them.*

## 1. The progression

```text
Healthcare domain            what the hospital needs to know               docs/competency-questions.md
   -> Ontology               classes, properties, vocabularies             docs/ontology-engineering.md
   -> RDF / OWL              the authoritative graph                       ontology/healthcare_schema.ttl + data/sample_data.ttl
   -> SHACL                  what valid data looks like                    shapes/
   -> SPARQL                 questions as queries                          sparql/
   -> Knowledge graph        data -> contract -> RDF -> projection         docs/sample-data-and-semantic-mapping.md
   -> APIs                   the same capabilities over HTTP               api.py, routers/
------------------------------------------------------------------------ CORE ends here
   -> Semantic retrieval     embeddings + graph traversal to find concepts enterprise/hybrid_retrieval.py
   -> RAG                    retrieval -> grounded query -> cited answer   agents/nodes/{ontology,query,response}.py
   -> Agentic AI             plan, validate, ask a human, abstain          agents/graph.py
------------------------------------------------------------------------ ADVANCED
```

Everything above the line is understandable, runnable and testable on its own. Everything below it uses what is above the line and adds nothing the layers above depend on.

## 2. Core and advanced components

| | Component | Where | Needs |
|---|---|---|---|
| **CORE** | Ontology schema (TBox) and sample data (ABox) generators | `scripts/generate_hc_ontology.py`, `scripts/generate_sample_data.py`, `services/reference_vocab.py`, `services/sample_data.py` | owlready2, rdflib, pySHACL |
| | RDF/OWL artifacts and their union | `ontology/healthcare_schema.ttl`, `data/sample_data.ttl`, `core/dataset.py` | rdflib |
| | SHACL validation | `core/shacl_*.py`, `shapes/` | rdflib, pySHACL |
| | SPARQL execution and validation | `core/sparql_validator.py`, `routers/sparql.py`, `sparql/*.rq` | rdflib |
| | Graph projection (plan, Cypher script) | `services/graph_projection.py`, `services/neo4j_exporter.py` | rdflib (the driver only to *write*) |
| | HTTP API, auth, authorization, tenancy | `api.py`, `routers/{system,ontology,patients,doctors,clinical,sparql,shacl,neo4j}.py`, `core/security.py`, `core/authz.py` | FastAPI |
| **ADVANCED** | LLM client | `core/llm.py` | openai, langchain-openai |
| | Natural language to SPARQL / Cypher | `services/{sparql,cypher}_generator.py`, `/llm-query`, `/nl-to-cypher` | the LLM stack |
| | Embeddings, document ingestion | `services/embedding_service.py`, `services/document_ingestor.py`, `routers/{embedding,documents}.py` | openai, a running Neo4j |
| | Hybrid retrieval and rerank (GraphRAG) | `enterprise/{hybrid_retrieval,retrieval_pipeline,lexical_memory}.py` | embeddings (the lexical channel needs nothing) |
| | The agent | `agents/graph.py`, `agents/nodes/`, `routers/agent.py` | langgraph, langchain |
| | Memory (working, episodic, procedural, semantic) | `agents/memory/` | Neo4j; embeddings for semantic |
| | Human approval | `agents/nodes/human_gate.py` | langgraph `interrupt` |
| | Abstention, provenance, guardrails, cost | `enterprise/{abstention,provenance,guardrails,cost}.py` | **nothing** (plain Python) |
| | Tracing, evaluation, workflows | `enterprise/{observability,evaluation,workflows}.py` | langsmith / opentelemetry, optional |
| | Demo UI | `streamlit_app.py` | streamlit |

Two facts worth noticing. The governance logic (abstention, provenance, guardrails) is *classified* advanced because it exists to control the agent, but it has no AI dependency, so it can be read, tested and taught without any model. And `neo4j` sits in the core list only as a driver: validating, generating, planning the projection and answering SPARQL do not talk to a server.

## 3. The dependency rules, and the evidence that they hold

1. **Core never imports an AI library at import time.** No `openai`, `langchain*`, `langgraph`, `langsmith`, `opentelemetry` or `streamlit` is reachable from any core module.
2. **Core never imports an advanced module at import time.** The agent consumes the core; the core does not know the agent exists.
3. **The few lazy edges into the advanced layer are listed, and the list is a test.** They are: `api` mounting the AI routers, `core.dependencies` building the LLM and embedding services on first use, `services.load_ontology.generate_sparql` calling the LLM, and two demo-only hooks into agent memory.
4. **Validation and generation do not need the Neo4j driver.**

These are checked three independent ways in `tests/test_architecture_boundaries.py`:

| Evidence | What it shows |
|---|---|
| *Static*: an import-graph analysis of every module, eager and lazy | Rules 1 to 4 for each of the core modules, one parametrized test per module; the allowed lazy edges must match the documented list exactly, so a new edge fails the build until it is justified |
| *Runtime*: a fresh interpreter in which the AI libraries and the `neo4j` package cannot be imported | The real API answers `/health`, `/sparql` (5 patients) and `/neo4j/projection` (124 nodes); `/agent` is 404; a natural-language endpoint returns 503, not a stack trace; SHACL, the data contract and the projection all run; no AI module is loaded |
| *Packaging*: `requirements-core.txt` against `requirements.txt` | The core list is a subset of the full list and names no AI package |

The runtime row was also confirmed in a real core-only virtualenv (section 11). I also checked that the tests can fail: adding `import langgraph` to a core module fails five of them.

## 4. Running without the AI layer

```bash
pip install -r requirements-core.txt -c constraints.txt
uvicorn api:app
```

or, with everything installed, `ENABLE_AI_LAYER=false` mounts the core routers only. If the layer is enabled but its libraries are missing, the API logs one warning and starts with the core routers instead of failing to import. The natural-language endpoints inside core routers (`/llm-query`, `/nl-query`, `/nl-to-cypher`) answer `503` with a message that says the optional layer is not installed.

The RDF and SPARQL chapters never touch the agent: the competency questions are `.rq` files run by `rdflib`, the shapes are Turtle, the ontology is generated by one script.

## 5. How the agent consumes the foundation

The agent is a LangGraph state machine: `memory_load -> planner -> ontology -> query -> validation -> human_gate -> execution -> abstention -> response`. It reaches the semantic layer through a small number of seams. None of them is a copy of core logic.

| The agent needs | It calls | Defined in | Note |
|---|---|---|---|
| The ontology (classes, properties) | `get_ontology()` | `core/dependencies.py` -> `services/load_ontology.py` | Same object the REST ontology endpoints use; builds the schema prompt for the generators |
| A SPARQL/Cypher query from a question | `get_sparql_generator()`, `get_cypher_generator()` | `services/*_generator.py` | The only LLM-producing calls besides the planner and the answer writer |
| **Query safety** | `SparqlQueryValidator`, `CypherQueryValidator` | `core/sparql_validator.py`, `core/cypher_validator.py` | The same validators the public API uses. The agent has no private, weaker path |
| Query execution | `get_sparql_to_cypher()` and `execute_cypher` | `services/sparql_to_cypher.py` | Read-only transaction and structural allow-list from the security work apply here too |
| Graph facts for retrieval | `get_sparql_to_cypher()` for traversal | `enterprise/hybrid_retrieval.py` | Graph channels read the *projection* |
| Embeddings | `get_embedding_service()` | `services/embedding_service.py` | One of three retrieval channels |
| Memory | `get_memory_orchestrator()` | `agents/memory/` | Stored in Neo4j under agent-only labels (`AgentSession`, `AgentTurn`, `AgentProcedure`, ...), disjoint from the projection labels, so rebuilding the projection never touches memory |
| Identity and tenant | `TenantContext`, `Principal` | `enterprise/`, `core/security.py` | Derived from the authenticated credential, not from request headers |

The direction of every arrow is agent -> core. The agent's state (`agents/state.py`) is plain data and does not leak LangGraph types into the services.

## 6. RAG integration

Retrieval-augmented generation here means *grounding a query in the ontology*, not retrieving prose.

1. `hybrid_retrieve` gathers candidate ontology concepts from three channels: a **lexical** match on names and synonyms (no model needed), a **graph** channel (keyword hits and neighbourhood traversal over the projection), and a **vector** channel (embeddings).
2. `retrieve_with_rerank` pools them, reranks, and records an error budget (how much of the answer rests on which channel).
3. The query agent receives the top concepts as context for the generator, so the SPARQL or Cypher it writes uses terms that exist.
4. The validator then checks the generated query against the ontology and the safety policy before anything runs.
5. The response carries **provenance**: the query text, the concepts used, the result rows, and the retrieval trace.

The vector channel is one of three. Without embeddings, the lexical and graph channels still work, and the answer's confidence reflects that.

## 7. Memory integration

Four memories, each separate and each optional:

| Memory | Holds | Stored |
|---|---|---|
| Working | The current turn's compacted context | In the graph state |
| Episodic | Sessions, turns, events, summaries | Neo4j (`AgentSession`, `AgentTurn`, `AgentEvent`, `SessionSummary`) |
| Procedural | Query patterns that worked | Neo4j (`AgentProcedure`) |
| Semantic | Ontology concepts relevant to this question | Derived from the ontology and embeddings |

A meta-memory controller decides what to recall and what to retain. Memory only changes *what context the agent sees*. It never writes to the RDF authority, and its labels cannot collide with the projection's (the ontology has a class `Procedure`, which is why procedural memory is `AgentProcedure`).

## 8. Abstention and human approval are strengths

The agent can decline to answer, and it can ask a person before running a query. Both are implemented and tested.

**Abstention** (`enterprise/abstention.py`) refuses when any of these holds: a human rejected the query; execution failed; mandatory provenance is missing (no query path and no result rows, or no concepts for an ontology-only answer); or the fused confidence (retrieval 0.18, retrieval pool 0.08, memory 0.04, validation 0.25, execution 0.25, provenance 0.20) is below `AGENT_ABSTENTION_THRESHOLD` (default 0.45). The decision and its reason (`missing_provenance`, `low_confidence`, `execution_failed`, `human_rejected`, `no_evidence`) are returned to the caller.

**Human approval** (`agents/nodes/human_gate.py`) pauses the graph with a LangGraph `interrupt` when the planner flags a risky query (broad scans, sensitive patient lists) or `AGENT_FORCE_HITL` is set. The reviewer sees the question, the validated query and the plan, and resumes with `approved` or `rejected`.

**Why a knowledge-grounded system should not fabricate.** A language model optimises for a fluent answer; in healthcare a fluent wrong answer is worse than none. The whole point of putting an ontology, a validator and a graph under the model is that an answer can be *traced* to a query and to rows. If there are no rows, or no valid query, there is nothing for the answer to stand on, and the honest output is "I cannot answer this from the data", with the reason. This is also the open-world point from the competency questions: absence of a record is not evidence of absence, so a system that turns an empty result into a confident "no" is guessing. The abstention rule makes that explicit, and because it is plain Python over evidence it is unit-tested without a model (`tests/test_governance.py`, and again with the AI stack made unimportable in `tests/test_architecture_boundaries.py`).

## 9. What should be optional

| Capability | Optional? | How it is optional today |
|---|---|---|
| Ontology, RDF, SHACL, SPARQL, projection planning, API | **No, this is the product** | - |
| Writing the projection to Neo4j | Yes | needs a server; planning does not |
| Natural language to SPARQL/Cypher | Yes | lazy import; `503` when the stack is missing |
| Embeddings and document ingestion | Yes | routers not mounted when the layer is off |
| Hybrid retrieval / GraphRAG | Yes | lexical channel works alone |
| The agent, memory, human approval | Yes | routers not mounted when the layer is off |
| Abstention, provenance, guardrails | Optional as a feature; free to keep | no dependencies |
| LangSmith / OpenTelemetry | Yes, off by default | lazy; configuration only |
| Streamlit UI | Yes | separate entry point |

## 10. Where this sits in the book

| Part | Chapters | Needs the AI layer? |
|---|---|---|
| I. Foundations | Domain and competency questions; ontology design; RDF/OWL; SHACL; SPARQL | No |
| II. The knowledge graph | Sample data and mapping; reasoning; the Neo4j projection; the HTTP API; security | No |
| III. Retrieval | Embeddings, hybrid retrieval, grounding queries in the ontology | Yes (the embedding channel); the lexical and graph channels do not |
| IV. Agents | Planning, validation, memory, human approval, abstention | Yes |

A reader can stop after Part II with a complete, validated, queryable healthcare knowledge graph. Part III and IV add *natural language access* to it; they do not change what it means.

## 11. Limits

- Install-level separation is `requirements-core.txt` (additive). `scripts/dev.py setup` still installs everything by default; a `--core-only` flag was not added. A clean core-only environment *was* built and used once (a new virtualenv from `requirements-core.txt` with `constraints.txt`: no openai, langchain, langgraph or streamlit installed): `scripts/validate.py` passed, the API started with the AI layer inactive (`/health` 200, `/agent/health` 404), and 489 tests passed across the ontology, sample-data, SPARQL, projection, SHACL, API-boundary and architecture-boundary suites. That run is manual, not part of CI.
- Some natural-language endpoints still live in core routers (`routers/sparql.py`, `routers/neo4j.py`). They fail cleanly when the stack is missing, but a stricter split would move them under an `ai/` router group.
- `enterprise/` mixes true enterprise controls with AI-specific ones; its modules are classified advanced as a group.
- The agent, memory, embedding and retrieval paths **were** exercised live (OpenAI and Neo4j Desktop); the results, the four defects that run found and the remaining limitations are in [AI_LAYER_LIVE_VERIFICATION.md](AI_LAYER_LIVE_VERIFICATION.md). LangSmith tracing was deliberately not exercised.
