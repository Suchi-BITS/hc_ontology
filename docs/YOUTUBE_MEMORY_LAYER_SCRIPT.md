# YouTube Video Scripts: The Memory Layer in Healthcare Knowledge Graph Agents

**Series title:** *Four Memories for Healthcare AI Agents*  
**Project:** `hc_ontology/`  
**Format:** 3 × ~60 minutes (YouTube long-form)  
**Prerequisites:** Modules on OWL, Neo4j export, embeddings sync, and basic `/agent/query` usage  
**Companion docs:** [system_design.md](../system_design.md) §8.4, [graph_schema_design.md](../graph_schema_design.md) §3.4–3.6

---

## Series overview (put in Video 1 description + playlist)

| # | Title | Runtime | Focus |
|---|-------|---------|-------|
| 1 | **Why Your Healthcare Agent Forgets — And How We Fix It** | ~60 min | Cognitive model, architecture, orchestrator, Neo4j layers |
| 2 | **Episodic & Working Memory — Conversation That Persists** | ~60 min | Sessions, turns, events, working context compaction |
| 3 | **Semantic & Procedural Memory — Grounded Facts and Learned Skills** | ~60 min | Ontology + GraphRAG retrieval, auto-learned query templates |

**Playlist hook (30 sec):**  
> Stateless LLMs forget every request. Real healthcare agents need **working**, **episodic**, **procedural**, and **semantic** memory — plus **meta-memory** to decide what to keep, archive, or drop under context limits. This series walks through a production-style implementation in Python, Neo4j, and LangGraph — with code you can run locally.

---

# VIDEO 1 — Why Your Healthcare Agent Forgets — And How We Fix It

**Suggested runtime:** 58–62 minutes  
**Files to have open:** `system_design.md`, `graph_schema_design.md`, `agents/memory/orchestrator.py`, `agents/graph.py`

---

## Hook (4 min)

**[ON SCREEN]** Split screen:

- Left: ChatGPT-style UI — user asks *"What did I ask about hypertension last turn?"* → model has no idea
- Right: Neo4j Browser — `(:AgentSession)-[:HAS_TURN]->(:AgentTurn)` chain + Swagger `POST /agent/query` with same `session_id`

**NARRATION**

> If you've built a healthcare chatbot on top of an LLM, you've hit this wall: the model **doesn't remember** the last question, the Cypher query that worked, or the ontology concepts it already retrieved.
>
> Retrieval-augmented generation (RAG) helps with **documents**. It does **not** give you:
> - Multi-turn conversation continuity
> - Reusable query skills learned from past successes
> - A structured trace of *what happened* in prior agent runs
>
> In this project we implement **four memory types** — the same taxonomy used in cognitive science and modern agent papers — backed by **Neo4j** and **LangGraph**.
>
> By the end of this video you'll know *why* each memory exists, *where* it lives in code, and *how* a single `POST /agent/query` flows through the memory layer.

**[ON SCREEN — TITLE CARD]**  
*Video 1 of 3: Memory Foundations*

---

## Section 1.1 — The four memory types (12 min)

**Learning objective:** Map cognitive memory types to healthcare agent needs.

**[ON SCREEN — TABLE]**

| Memory type | Human analogy | Agent need in this project |
|-------------|---------------|----------------------------|
| **Working** | What you're holding in mind right now | Current question, plan, draft query, validation error, compacted prompt context |
| **Episodic** | Remembering a specific past experience | *Last Tuesday we asked about patients with diabetes and ran this Cypher* |
| **Procedural** | Knowing how to ride a bike / write a query | Reusable Cypher/SPARQL templates learned from successful turns |
| **Semantic** | General world knowledge | OWL classes, `OntologyConcept` embeddings, GraphRAG document chunks |
| **Meta** | Knowing what you know | Score turns for recall, archive long sessions, decay stale procedures, tune context budget |

**NARRATION**

> **Working memory** is ephemeral. It exists for **this thread, this turn**. In our code that's `AgentState` plus LangGraph's checkpointer — fields like `working_context`, `draft_query`, and `working_events`.
>
> **Episodic memory** is the diary. Each agent run appends a turn: question, answer, validated query, confidence, status. We persist it in Neo4j as `AgentSession` → `AgentTurn` → optional `AgentEvent`.
>
> **Procedural memory** is the playbook. When a turn completes with high confidence and a valid query, we can **learn** a `Procedure` node: intent keywords + template query + plan steps. Next time a similar question arrives, we skip full LLM generation.
>
> **Semantic memory** is **not** conversation history. It's stable domain knowledge: ontology terms, vector-indexed concepts, and document sections grounded to those concepts. It was already in the project via embeddings and GraphRAG; we wired it explicitly into the memory orchestrator.
>
> **Meta-memory** is the **control plane** above all four stores. Before each turn it scores past episodes by relevance, utility, salience, and recency — then packs only the highest-value items into the working-context budget. After each turn it can **archive** old turns into a `SessionSummary` node (audit-safe: we mark `archived=true`, we don't delete by default) and **decay** procedural templates that haven't been used in weeks.

**[ON SCREEN — DIAGRAM]** `system_design.md` §8.4 lifecycle:

```
POST /agent/query
  → meta_memory.plan_recall()           # score + limits
  → memory_load: assemble_context()      # episodic + procedural
  → ontology: enrich_semantic()          # semantic bundle
  → planner / query: working_context
  → response: commit_turn()              # episodic write + procedure learn
  → meta_memory.post_turn()              # archive + decay
```

**[PAUSE FOR NOTE]**  
> Semantic memory is **read-mostly during a turn**. Episodic and procedural memories **write** at the end. Working memory **dies** when the turn ends — except what's summarized into episodic storage. Meta-memory runs **before and after** every turn to govern recall and archival.

---

## Section 1.2 — Where memory lives in Neo4j (14 min)

**Learning objective:** Understand the five graph layers; know which layers are memory.

**[ON SCREEN]** `graph_schema_design.md` mermaid diagram (clinical, semantic, document, episodic, procedural)

**NARRATION**

> Neo4j in this project is **not one graph**. It's five layers in one database:
>
> 1. **Clinical** — `:Patient`, `:Doctor` individuals from OWL export  
> 2. **Semantic** — `:OntologyConcept` with vector embeddings  
> 3. **Document** — `:DocumentSection` grounded to concepts (GraphRAG)  
> 4. **Episodic** — `:AgentSession`, `:AgentTurn`, `:AgentEvent`, `:SessionSummary`  
> 5. **Procedural** — `:Procedure` templates  
>
> Layers 2 and 3 feed **semantic memory**. Layers 4 and 5 are **agent memory proper**. Layer 1 is what your Cypher queries **execute against**.

**[DEMO — Neo4j Browser]**

```cypher
MATCH (n)
RETURN labels(n) AS labels, count(*) AS cnt
ORDER BY cnt DESC;
```

Point out: after agent runs you should see `AgentSession`, `AgentTurn`; after several successes, `Procedure`.

**[ON SCREEN — CODE]** Relationships summary:

```cypher
(:AgentSession)-[:HAS_TURN]->(:AgentTurn)
(:AgentSession)-[:HAS_SUMMARY]->(:SessionSummary)
(:AgentTurn)-[:HAS_EVENT]->(:AgentEvent)
(:AgentTurn)-[:USED_CONCEPT]->(:OntologyConcept)
(:Procedure)-[:LEARNED_FROM]->(:AgentTurn)
(:Procedure)-[:APPLIES_TO_CONCEPT]->(:OntologyConcept)
```

**NARRATION**

> The link `USED_CONCEPT` is audit gold: you can answer *which ontology terms informed this answer?*  
> `LEARNED_FROM` ties a procedure back to the turn that taught it — lineage for compliance in healthcare settings.

---

## Section 1.3 — The MemoryOrchestrator (15 min)

**Learning objective:** Read `orchestrator.py`; understand assemble vs enrich vs commit.

**[ON SCREEN — CODE]** `agents/memory/orchestrator.py` — walk three public methods:

1. `assemble_context()` — called conceptually at **memory_load**
2. `enrich_semantic()` — called at **ontology node**
3. `commit_turn()` — called at **response node**

**NARRATION**

> We deliberately **don't** scatter `load_context()` and `save_turn()` across nodes anymore. The **MemoryOrchestrator** is the single API:
>
> - **Plan recall** (meta-memory) scores session turns and sets episodic/similar limits before assembly.
> - **Assemble** loads meta-ranked episodic text + similar episodes + matched procedures, then compacts them into `working_context`.
> - **Enrich semantic** runs hybrid retrieval and optional GraphRAG, updates `memory_bundle.semantic`, refreshes `ontology_context`.
> - **Commit** writes the turn, events, concept links, and optionally learns a procedure.
> - **Post-turn** (meta-memory) archives long sessions and decays stale procedures.

**[ON SCREEN — CODE]** Package layout:

```
agents/memory/
  working.py      # compact_working_context, append_working_event
  episodic.py     # EpisodicMemoryStore (+ archive, SessionSummary)
  procedural.py   # ProceduralMemoryStore (+ stale decay)
  semantic.py     # retrieve_semantic_memory
  meta_memory.py  # MetaMemoryController — plan_recall, post_turn, score_turn
  orchestrator.py # MemoryOrchestrator
```

**[DEMO — Swagger]**

```http
GET /agent/health
```

Show feature flags: `four_memory`, `meta_memory`, `working_memory`, `episodic_memory`, `procedural_memory`, `semantic_memory`.

```http
POST /agent/query
Content-Type: application/json
X-Tenant-ID: default
X-Role: analyst

{
  "question": "List patients with hypertension",
  "session_id": "demo-session-001"
}
```

**NARRATION**

> Save `session_id` from the response. We'll reuse it in Video 2. Point at response fields: `memory_bundle`, `meta_memory` (recall_confidence, context_pressure), `working_context` (inside `state`), `trace` entries like `memory_load:start`.

---

## Section 1.4 — LangGraph integration (12 min)

**Learning objective:** See `memory_load` as first node; understand state flow.

**[ON SCREEN — CODE]** `agents/graph.py`

```
START → memory_load → planner → ontology → query → validation → ...
```

**NARRATION**

> Before our memory work, the graph started at **planner**. The planner only had the raw question. Now **memory_load** runs first and injects `memory_context`, `memory_bundle`, and `matched_procedures`.
>
> The **ontology** node no longer duplicates episodic loading — it calls `enrich_semantic()` only.
>
> **Planner** reads `working_context` (compacted), not a wall of raw JSON.

**[ON SCREEN — CODE]** `agents/state.py` — highlight memory fields:

```python
memory_bundle: dict[str, Any]
memory_context: str
working_context: str
working_events: list[dict[str, Any]]
matched_procedures: list[dict[str, Any]]
meta_memory: dict[str, Any]
```

**[ON SCREEN — CODE]** `agents/nodes/memory_load.py` — 2-minute walkthrough

**Honest limitation (1 min):**

> LangGraph's checkpointer is still `MemorySaver` — in-process. **Working memory** for HITL resume works per server process, not across restarts. Episodic/procedural persistence in Neo4j **does** survive restarts. We'll call out production upgrades (Redis checkpointer) in Video 3.

---

## Section 1.4b — Meta-memory: knowing what you know (10 min)

**Learning objective:** Understand `MetaMemoryController`; read `plan_recall` and `post_turn`.

**[ON SCREEN — CODE]** `agents/memory/meta_memory.py`

**NARRATION**

> The four memory types tell you **what** is stored. **Meta-memory** tells you **what to do with it** — retain, archive, or skip — based on relevance, utility, salience, and context pressure.
>
> Before `assemble_context`, `plan_recall()`:
>
> 1. Counts turns in the session  
> 2. Scores each turn with `score_turn()` — keyword relevance (40%), confidence/utility (30%), salience from validated queries (15%), recency decay (15%)  
> 3. Keeps turns above `META_MEMORY_RETAIN_THRESHOLD` (default 0.35)  
> 4. Detects **context pressure** when turn count exceeds half the archive threshold  
> 5. Under pressure: lowers episodic/similar limits and shrinks `max_chars` by 15%  
>
> The ranked turns become `recent_text` in the episodic bundle — not a blind "last 5 turns" dump.

**[ON SCREEN — CODE]** `score_turn()` and `RecallPlan` dataclass

```python
score(m) = 0.40*relevance + 0.30*utility + 0.15*salience + 0.15*recency
```

**[ON SCREEN — CODE]** `post_turn()` after `commit_turn`:

> When a session exceeds `META_MEMORY_SESSION_ARCHIVE_TURNS` (default 15), we:
>
> - Create a `SessionSummary` node linked via `HAS_SUMMARY`  
> - Set `archived=true` on older turns (audit trail preserved — **not deleted**)  
> - Keep the most recent `META_MEMORY_KEEP_RECENT_TURNS` (default 5) in hot recall  
>
> Procedural templates unused for 30 days get `stale=true` and stop matching until reinforced.

**[DEMO — Neo4j Browser]** After a long session:

```cypher
MATCH (s:AgentSession {session_id: 'demo-session-001'})-[:HAS_SUMMARY]->(sum:SessionSummary)
RETURN sum.summary_text, sum.archived_turn_count;

MATCH (t:AgentTurn) WHERE t.archived = true RETURN count(t);
```

**[ON SCREEN — RESPONSE JSON]** Point at `meta_memory`:

```json
{
  "recall_confidence": 0.72,
  "context_pressure": false,
  "episodic_limit": 5,
  "signals": { "turn_count": 3, "selected_turn_count": 2 }
}
```

> `recall_confidence` feeds into abstention's `memory_coverage` signal — the agent knows when prior context is thin.

---

## Section 1.5 — Configuration & tenancy (8 min)

**Learning objective:** Know the env vars; understand tenant scoping.

**[ON SCREEN — TABLE]** From `core/config.py`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `WORKING_MEMORY_MAX_CHARS` | 6000 | Compacted context budget |
| `EPISODIC_CONTEXT_TURNS` | 5 | Recent turns per session |
| `EPISODIC_SIMILAR_TOP_K` | 3 | Similar episode hints |
| `PROCEDURAL_MATCH_THRESHOLD` | 0.35 | Min score to list procedure |
| `PROCEDURAL_AUTO_LEARN` | true | Learn from successful turns |
| `PROCEDURAL_MIN_CONFIDENCE` | 0.7 | Min confidence to learn |
| `SEMANTIC_ENABLE_GRAPH_RAG` | true | Include document sections |
| `META_MEMORY_ENABLED` | true | Meta-memory recall/archive/decay |
| `META_MEMORY_RETAIN_THRESHOLD` | 0.35 | Min turn score for hot recall |
| `META_MEMORY_SESSION_ARCHIVE_TURNS` | 15 | Archive when session exceeds this |
| `META_MEMORY_KEEP_RECENT_TURNS` | 5 | Hot turns after archival |
| `META_MEMORY_PURGE_FAILED` | false | Delete failed turns (off by default) |
| `META_MEMORY_PROCEDURE_DECAY_DAYS` | 30 | Mark unused procedures stale |

**NARRATION**

> `AgentSession` and `Procedure` carry `tenant_id`. APIs require `X-Tenant-ID`. Episodic search and procedure match **filter by tenant** — important for multi-tenant hospital deployments.

---

## Lab 1 — First memory-aware session (5 min)

**[LAB]**

1. `POST /embedding/sync` and `POST /neo4j/load` if not done  
2. `POST /agent/query` with `session_id: "yt-memory-lab-1"` — question about patients  
3. Second query same session: *"What query type did you use before?"* — observe episodic context in trace  
4. Neo4j: `MATCH (s:AgentSession {session_id: 'yt-memory-lab-1'})-[:HAS_TURN]->(t) RETURN t`

**Terminal inspection (optional):** set `MEMORY_DEBUG_CONTEXT=true` in `.env` and restart the API. Each `/agent/query` prints labeled blocks: `assemble_context`, `enrich_semantic`, `query (grounded_context)`, `commit_turn`. See `readme.md` → *Memory cycle testing* for the full eight-scenario checklist.

---

## Recap & next video teaser (2 min)

**NARRATION**

> Today: **four memory types**, **meta-memory control plane**, **five Neo4j layers**, **MemoryOrchestrator** lifecycle, **memory_load** in LangGraph.
>
> **Video 2** goes deep on **episodic and working memory** — `AgentEvent` traces, context compaction, and the session APIs.
>
> **Video 3** covers **semantic retrieval fusion** and **procedural auto-learning** — how the agent gets faster over time.

**[END SCREEN]** Subscribe + link to repo `docs/YOUTUBE_MEMORY_LAYER_SCRIPT.md`

---

# VIDEO 2 — Episodic & Working Memory — Conversation That Persists

**Suggested runtime:** 58–62 minutes  
**Files:** `agents/memory/episodic.py`, `agents/memory/working.py`, `agents/nodes/memory_load.py`, `agents/nodes/response.py`

---

## Hook (3 min)

**[ON SCREEN]** Two agent runs side by side:

- Run A: new `session_id` every request — planner treats each question cold  
- Run B: same `session_id` — `memory_load` injects *"Prior conversation context…"*

**NARRATION**

> Episodic memory is what makes an agent feel like a **conversation** instead of a stateless API call. Working memory is what keeps the **current** turn coherent when validation fails, HITL pauses, or the prompt budget is tight.
>
> This video is implementation-heavy: Neo4j schema, Python store, compaction algorithm, and the APIs you'll use to debug memory in production.

---

## Section 2.1 — Episodic schema deep dive (14 min)

**Learning objective:** Model sessions, turns, and events; write Cypher fluently.

**[ON SCREEN]** `graph_schema_design.md` §3.4

**NARRATION**

> A **session** is a stable ID the client sends — think browser tab or EHR workflow instance. A **turn** is one `POST /agent/query` (or resume) that completes. An **event** is a fine-grained step inside that turn.

**[ON SCREEN — PROPERTIES TABLE]**

| Node | Key properties |
|------|----------------|
| `AgentSession` | `session_id`, `tenant_id`, `user_id`, `updated_at` |
| `AgentTurn` | `question`, `answer`, `validated_query`, `confidence`, `status`, `refused` |
| `AgentEvent` | `type`, `payload_json`, `created_at` |

**[ON SCREEN — CODE]** `EpisodicMemoryStore.ensure_schema()` — three constraints

**[DEMO — Neo4j Browser]**

```cypher
MATCH (s:AgentSession)-[:HAS_TURN]->(t:AgentTurn)
OPTIONAL MATCH (t)-[:HAS_EVENT]->(e:AgentEvent)
RETURN s.session_id, t.question, t.status, collect(e.type) AS events
ORDER BY t.created_at DESC
LIMIT 10;
```

**NARRATION**

> Event types you'll see: `memory_assembled`, `semantic_enriched`, `trace` (from `working_events` and graph trace). This is your **debug timeline** when an answer is wrong.

---

## Section 2.2 — save_turn and commit_turn (12 min)

**Learning objective:** Trace write path from response node to Neo4j.

**[ON SCREEN — CODE]** `agents/nodes/response.py` → `_persist()` → `get_memory_orchestrator().commit_turn()`

**[ON SCREEN — CODE]** `orchestrator.py` `commit_turn()`:

- Collects `retrieved_concepts` → `USED_CONCEPT` edges  
- Merges `working_events` + last 20 trace steps → `AgentEvent` nodes  
- Calls `episodic.save_turn()` with structured `metadata_json` (not opaque strings)
- Calls `meta.post_turn()` — archive long sessions, decay stale procedures

**NARRATION**

> We upgraded from the original `metadata_json=str(meta)` hack to proper JSON via `json.dumps`. Metadata includes `plan`, `provenance_path_count`, and `matched_procedures` names — enough to reconstruct *why* the agent answered without storing full result rows.

**[ON SCREEN — DESIGN RULE]**

> **Do not** store Cypher result rows in the graph. Episodic memory stores **summaries** and **queries**, not PHI-heavy tabular dumps. Results stay in the API response (truncated at 50 rows in `serialize_state`).

**[DEMO]**

Run agent query → inspect turn:

```cypher
MATCH (t:AgentTurn)-[:USED_CONCEPT]->(c:OntologyConcept)
WHERE t.turn_id = $turn_id
RETURN t.question, c.name;
```

---

## Section 2.3 — Loading episodic context (12 min)

**Learning objective:** `load_context` and `search_similar_episodes`.

**[ON SCREEN — CODE]** `episodic.py`:

- `load_context(session_id, limit=EPISODIC_CONTEXT_TURNS)`  
- `search_similar_episodes(question)` — token overlap over past `status=completed` turns with `validated_query`

**NARRATION**

> Recent context is **recency-biased**: last N turns, formatted as natural language for the planner prompt.
>
> Similar episodes are **keyword-biased** today — we tokenize the question and score overlap against historical questions. It's cheap, explainable, and good for course demos. Video 3 discusses vector indexing on turns as a future upgrade.

**[DEMO — API]**

```http
GET /agent/memory/yt-memory-lab-1?limit=5
X-Tenant-ID: default
X-Role: analyst
```

```http
GET /agent/memory/episodes/search?q=patients%20hypertension&limit=5
X-Tenant-ID: default
X-Role: analyst
```

Show `match_score` on episodes.

**[ON SCREEN — CODE]** `memory_load_node` — how `assemble_context` fills `memory_bundle.episodic`

---

## Section 2.4 — Working memory compaction (16 min)

**Learning objective:** Implement/read `compact_working_context`; understand priority budget and meta-memory ranked episodic text.

**[ON SCREEN — CODE]** `agents/memory/working.py` full walkthrough

**NARRATION**

> LLM context windows are finite. We don't dump the entire `AgentState` into the prompt. `compact_working_context` builds sections with **fixed priority**:
>
> 1. Question (always)  
> 2. Matched procedures  
> 3. Semantic concept list  
> 4. Full ontology context (from ontology node)  
> 5. Episodic recent + similar episodes — **ranked by meta-memory** when enabled  
> 6. Repair block (validation error + failed query) on retry  
>
> Total length capped by `WORKING_MEMORY_MAX_CHARS` (default 6000), or lower when meta-memory detects **context pressure**.

**[ON SCREEN — LIVE EXAMPLE]** Print `working_context` from agent response `state` — annotate each `### Section`

**[ON SCREEN — CODE]** `append_working_event()` — used when memory assembles and semantic enriches

**NARRATION**

> `working_events` are **in-turn only**. They become `AgentEvent` nodes on commit. Think of them as structured flight recorder data for the current request.

**[DEMO — RETRY SCENARIO]**

1. Ask a question that produces invalid Cypher (or temporarily break validator)  
2. Show validation retry — section 6 (*Repair context*) appears in working memory  
3. Trace: `query:attempt=2`, `validation:fail`, then `validation:ok`

---

## Section 2.5 — Planner and query consumption (8 min)

**Learning objective:** See how downstream nodes read working memory.

**[ON SCREEN — CODE]**

- `planner.py`: `working_context or memory_context` in prompt  
- `query.py`: `_grounded_question()` calls `compact_working_context` again with ontology + repair fields

**NARRATION**

> Planner gets **episodic + procedural** hints early (from memory_load). Query gets the **full** compacted context after ontology enrichment — including semantic concepts and document evidence.

---

## Section 2.6 — HITL and working memory (5 min)

**Learning objective:** Relate `thread_id` checkpointer to working state across pause.

**NARRATION**

> Human-in-the-loop uses LangGraph `interrupt()` at `human_gate`. The **thread_id** keys the checkpointer — all working fields (`draft_query`, `validated_query`, `plan`) survive until `POST /agent/resume`.
>
> Episodic write happens **after** response — so a paused thread has **no new turn** in Neo4j yet. That's correct: we only persist completed or rejected outcomes.

**[DEMO]**

```http
POST /agent/query
{ "question": "...", "require_human_approval": true }

POST /agent/resume
{ "thread_id": "...", "decision": "approved" }
```

---

## Lab 2 — Build a three-turn clinical session (5 min)

**[LAB]**

Use one `session_id`. Turn 1: *"What is the Patient concept?"* (ontology_only). Turn 2: *"List all patients"* (cypher, may need HITL). Turn 3: *"Repeat the last query"* — observe episodic + similar episode behavior.

Verify in Neo4j: 3 turns, monotonically increasing `created_at`, events on latest turn.

---

## Recap (2 min)

> Episodic = **Neo4j diary** (sessions, turns, events, concepts). Working = **compacted prompt state** (priority sections, per-turn events). Next: semantic fusion and procedural learning.

---

# VIDEO 3 — Semantic & Procedural Memory — Grounded Facts and Learned Skills

**Suggested runtime:** 58–62 minutes  
**Files:** `agents/memory/semantic.py`, `agents/memory/procedural.py`, `enterprise/hybrid_retrieval.py`, `enterprise/retrieval_pipeline.py`, `enterprise/abstention.py`

---

## Hook (4 min)

**[ON SCREEN]**

- Left: Agent run 1 — full LLM Cypher generation (~90 sec)  
- Right: Agent run 5 — same intent — `query:procedure_template` in trace (~5 sec)

**NARRATION**

> **Semantic memory** grounds answers in ontology truth — not hallucinated table names. **Procedural memory** lets the agent **reuse** what worked — like a clinician remembering a order set.
>
> Together they turn a generic LLM into a **healthcare graph specialist** that gets faster and more grounded over time.

---

## Section 3.1 — Semantic memory architecture (12 min)

**Learning objective:** Separate semantic from episodic; list all sources.

**[ON SCREEN — TABLE]**

| Source | Neo4j / runtime | Access path |
|--------|-----------------|-------------|
| OWL schema | Owlready2 in memory | `get_ontology().get_classes()` |
| Concept embeddings | `:OntologyConcept` | `EmbeddingService` vector index |
| Hybrid retrieval | Concepts + OWL keyword + neighborhood | `enterprise/hybrid_retrieval.py` |
| GraphRAG chunks | `:DocumentSection -[:GROUNDS_IN]-> OntologyConcept` | `document_ingestor.retrieve_grounded_document_sections` |

**[ON SCREEN — CODE]** `semantic.py` → `retrieve_semantic_memory()` returns:

```python
{
  "concepts": [...],
  "document_sections": [...],
  "schema_excerpt": "...",
  "hybrid_meta": {...},
  "retrieval_meta": {...}  # includes error_budget
}
```

**NARRATION**

> Semantic memory is **read-only during a turn**. You materialize it elsewhere: `POST /embedding/sync`, `POST /documents/upload`, OWL load at startup. The ontology node **reads** it via `orchestrator.enrich_semantic()`.

**[DEMO]**

```http
POST /documents/upload
# upload a short .txt clinical guideline

POST /agent/query
{ "question": "...", "session_id": "semantic-demo" }
```

In response `state.ontology_context`, point out *Grounded document evidence* section from `format_semantic_context()`.

---

## Section 3.2 — Hybrid retrieval pipeline (14 min)

**Learning objective:** Explain pool → rerank → error budget; connect to agent confidence.

**[ON SCREEN — CODE]** `enterprise/hybrid_retrieval.py`:

1. Vector hits (`EmbeddingService.search_api`)  
2. Graph keyword hits (OWL class/individual names)  
3. Neighborhood expansion (Neo4j optional match)  
4. **RRF merge**

**[ON SCREEN — CODE]** `enterprise/retrieval_pipeline.py`:

- `rerank_candidates()` — 65% RRF + 35% lexical overlap  
- `compute_error_budget()` — `concept_pool_hit_rate`, `residual_retrieval_risk`

**NARRATION**

> This pipeline predates the memory package — we **wrapped** it as semantic memory rather than duplicating logic in the ontology node. The **error budget** feeds abstention and appears in `retrieval_meta` on the API response.

**[DEMO]**

```http
POST /enterprise/hybrid-search
{ "query": "diabetes medication interaction", "top_k": 8 }
```

Compare channels in response to agent `retrieval_meta.channels`.

**[ON SCREEN — CODE]** `ontology_node` — thin wrapper calling `enrich_semantic()`

---

## Section 3.3 — Procedural memory schema and matching (12 min)

**Learning objective:** Model procedures; understand match vs template-fill thresholds.

**[ON SCREEN]** `graph_schema_design.md` §3.5

**[ON SCREEN — CODE]** `procedural.py`:

- `match_procedures(question, tenant_id)` — lexical score vs `PROCEDURAL_MATCH_THRESHOLD` (0.35)  
- `learn_from_turn(...)` — requires `PROCEDURAL_AUTO_LEARN`, `confidence >= PROCEDURAL_MIN_CONFIDENCE` (0.7), non-empty `validated_query`

**NARRATION**

> Two thresholds matter:
> - **0.35** — show procedure in working context (hint)  
> - **0.85** — query node uses `template_query` **directly** without LLM generation (`query:procedure_template` in trace)  
>
> Procedures merge by `tenant_id` + derived `name` (question tokens). `success_count` and `avg_confidence` increase on repeat successes.
>
> **Meta-memory decay:** procedures with `last_used_at` older than `META_MEMORY_PROCEDURE_DECAY_DAYS` get `stale=true` and are excluded from `match_procedures`. A new success via `learn_from_turn` clears `stale`.

**[DEMO — API]**

```http
GET /agent/memory/procedures?q=list%20patients%20diagnosis
X-Tenant-ID: default
```

**[DEMO — Neo4j]**

```cypher
MATCH (p:Procedure)-[:LEARNED_FROM]->(t:AgentTurn)
RETURN p.name, p.template_query, p.success_count, t.question
ORDER BY p.success_count DESC;
```

---

## Section 3.4 — Auto-learn lifecycle (10 min)

**Learning objective:** Trace procedure creation end-to-end.

**[ON SCREEN — FLOW]**

```
validation_ok + status=completed + confidence>=0.7
  → commit_turn()
  → procedural.learn_from_turn()
  → MERGE Procedure, link LEARNED_FROM, APPLIES_TO_CONCEPT
```

**[ON SCREEN — CODE]** `orchestrator.commit_turn()` — conditional learn block

**NARRATION**

> We **never** learn from refused, failed, or low-confidence turns. That's intentional — you don't want a bad Cypher query fossilized into procedural memory.

**[LAB — LIVE]**

1. Run 3 similar successful queries: *"List patients with hypertension"* variants  
2. Watch `Procedure` node appear / `success_count` increment  
3. Fourth run — confirm `query:procedure_template` in trace

---

## Section 3.5 — Query node: procedure vs LLM (8 min)

**Learning objective:** Read `_procedure_template()` and fallback behavior.

**[ON SCREEN — CODE]** `agents/nodes/query.py`

**NARRATION**

> If `match_score >= 0.85` and query types align, `draft_query` = `template_query` immediately. Validation still runs — procedures are **candidates**, not bypasses for safety checks.
>
> On validation failure, repair path uses LLM `gen.repair()` — procedural template is not retried blindly.

---

## Section 3.6 — Memory in governance: abstention (6 min)

**Learning objective:** See `memory_coverage` confidence signal.

**[ON SCREEN — CODE]** `enterprise/abstention.py` — `memory_coverage` from episodic + procedural presence in `memory_bundle`, blended with `meta_memory.recall_confidence` when meta-memory is enabled

**NARRATION**

> Abstention fuses retrieval, validation, execution, provenance, and now **memory coverage** (4% weight). If the agent has no episodic hints and no procedures for a ambiguous clinical question, confidence drops — safer to refuse than invent.

**[DEMO]** Compare confidence `signals` in response with and without `session_id` + prior turns.

---

## Section 3.7 — Production considerations (8 min)

**Learning objective:** Leave students with a realistic roadmap.

**[ON SCREEN — BULLETS]**

| Topic | Current state | Production upgrade |
|-------|---------------|-------------------|
| Working memory durability | `MemorySaver` in-process | Redis / Postgres checkpointer |
| Episodic similarity | Keyword overlap | Vector index on `AgentTurn.question` |
| PHI in episodic nodes | Question/answer text stored | Redaction at write; retention TTL |
| Procedure governance | Auto-learn on | Admin review queue; promote to `global` |
| Semantic tenancy | `OntologyConcept` global | Per-tenant concept namespaces |
| Memory observability | `trace`, `AgentEvent` | LangSmith spans on `memory.assemble` |

**NARRATION**

> The architecture separates **concerns** so you can upgrade each memory type independently. Semantic layer was already production-shaped (vector index). Episodic and procedural are the new graph surfaces — monitor `Procedure.success_count` and episodic `refused` rates as KPIs.

---

## Capstone lab — Full memory stack (6 min)

**[LAB — 15 min student time; narrate checklist]**

1. Materialize: `/neo4j/load`, `/embedding/sync`, upload one document  
2. Session `capstone-memory`: 4-turn conversation (define concept → list patients → filter diagnosis → reuse query)  
3. Verify Neo4j: sessions, turns, events, concepts, at least one procedure  
4. Call episode search + procedure APIs  
5. Read `working_context` + `meta_memory` + `provenance` + `confidence.signals.memory_coverage` on final response

---

## Series finale (2 min)

**NARRATION**

> You now have the full **four-memory stack** plus **meta-memory** for healthcare graph agents:
>
> - **Working** — compact, prioritized context per turn  
> - **Episodic** — persistent conversation and audit trail in Neo4j  
> - **Semantic** — ontology + vectors + GraphRAG grounding  
> - **Procedural** — learned query skills that compound over time  
> - **Meta** — score, archive, and decay — knowing what you know  
>
> Code: `agents/memory/` (including `meta_memory.py`). Docs: `system_design.md` and `graph_schema_design.md`.  
> Link the playlist. Ask viewers to post their Neo4j `Procedure` success_count screenshots.

**[END SCREEN]**

---

## Production notes for the instructor

### Suggested chapter timestamps (YouTube)

**Video 1:** 0:00 Hook · 4:00 Four types · 16:00 Neo4j layers · 30:00 Orchestrator · 45:00 LangGraph · 53:00 Config · 55:00 Lab · 58:00 Recap  

**Video 2:** 0:00 Hook · 3:00 Episodic schema · 17:00 commit_turn · 29:00 load/search · 41:00 Working compaction · 57:00 HITL · 58:00 Lab  

**Video 3:** 0:00 Hook · 4:00 Semantic arch · 16:00 Hybrid pipeline · 30:00 Procedural schema · 42:00 Auto-learn · 52:00 Query node · 58:00 Governance · 66:00 Production · 72:00 Capstone  

*(Adjust demos ±5 min based on Ollama speed.)*

### B-roll / screen recording checklist

- [ ] Neo4j Browser: layer count query  
- [ ] Swagger: `/agent/health` features list  
- [ ] Side-by-side: cold vs warm `session_id`  
- [ ] Trace highlighting: `memory_load`, `query:procedure_template`  
- [ ] `working_context` markdown sections scrolled slowly  
- [ ] Procedure node before/after `success_count`  

### Common student pitfalls (call out on camera)

1. Forgetting `POST /embedding/sync` before semantic memory works  
2. Using Neo4j **instance name** instead of `NEO4J_DATABASE`  
3. Expecting memory across different `session_id` values  
4. Confusing `:Patient` (clinical individual) with `:OntologyConcept {name:'Patient'}`  
5. Learning procedures from failed/refused turns (won't happen by design)  
6. Expecting archived turns in hot recall — check `t.archived` and `SessionSummary` nodes  

### Link in video description

```
Repo: hc_ontology/
Memory docs: system_design.md §8.4, graph_schema_design.md §3.4–3.6
Script: docs/YOUTUBE_MEMORY_LAYER_SCRIPT.md
```
