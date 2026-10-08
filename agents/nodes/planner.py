"""Planner Agent — multi-step plan, query path, HITL flag."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.prompts import PromptTemplate
from core.llm import get_chat_llm
from core.config import get_settings

logger = logging.getLogger("healthcare_ontology.agent")

_PLANNER_PROMPT = PromptTemplate(
    input_variables=["question", "memory_context"],
    template="""You are the Planner Agent for a healthcare ontology multi-agent system.

Decide how to answer the user question using ONLY these query paths:
- cypher: Neo4j graph query over individuals/relationships (default for clinical data)
- sparql: RDF/OWL SPARQL over the ontology file
- ontology_only: concept lookup / definitions via semantic search (no graph query execution)

Also decide if a human should approve before executing a database query
(require_human_approval=true for broad scans, sensitive patient lists, or high-cost queries).

Prior memory (may be empty):
{memory_context}

Question:
{question}

Return ONLY valid JSON (no markdown):
{{
  "query_type": "cypher" | "sparql" | "ontology_only",
  "require_human_approval": true | false,
  "reasoning": "one short sentence",
  "plan": ["step1", "step2", "step3"]
}}
""",
)


def _heuristic_plan(question: str) -> dict[str, Any]:
    q = question.lower()
    if any(k in q for k in ("sparql", "rdf", "owl class", "triple")):
        query_type = "sparql"
    elif any(
        k in q
        for k in (
            "what is",
            "define",
            "meaning of",
            "explain concept",
            "related concepts",
            "ontology concept",
        )
    ) and not any(k in q for k in ("patient", "doctor", "diagnosis", "list", "how many")):
        query_type = "ontology_only"
    else:
        query_type = "cypher"

    risky = any(
        k in q
        for k in ("all patients", "every patient", "delete", "update", "export all")
    )
    plan = [
        "Retrieve ontology context and prior memory",
        f"Generate a {query_type} query grounded in ontology",
        "Validate query safety and schema",
        "Execute if approved",
        "Compose grounded response",
    ]
    return {
        "query_type": query_type,
        "require_human_approval": risky,
        "reasoning": "Heuristic planner (LLM unavailable or invalid JSON).",
        "plan": plan,
    }


def _parse_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def planner_node(state: AgentState) -> dict[str, Any]:
    question = (state.get("question") or "").strip()
    memory_context = (
        state.get("working_context")
        or state.get("memory_context")
        or ""
    )
    settings = get_settings()
    max_retries = int(state.get("max_retries") or settings.get("agent_max_retries", 3))
    override_type = state.get("query_type")
    override_hitl = state.get("require_human_approval")

    trace = list(state.get("trace") or [])
    trace.append("planner:start")

    planned = None
    try:
        llm = get_chat_llm(model=settings["llm_model"], temperature=0)
        raw = llm.invoke(
            _PLANNER_PROMPT.format(question=question, memory_context=memory_context or "(none)")
        )
        content = getattr(raw, "content", str(raw))
        planned = _parse_json(content)
    except Exception as exc:
        logger.warning("Planner LLM failed, using heuristics: %s", exc)

    if not planned or planned.get("query_type") not in ("cypher", "sparql", "ontology_only"):
        planned = _heuristic_plan(question)

    query_type = planned["query_type"]
    if override_type in ("cypher", "sparql", "ontology_only"):
        query_type = override_type
        trace.append("planner:query_type_override")

    require_hitl = bool(planned.get("require_human_approval", False))
    if override_hitl is not None:
        require_hitl = bool(override_hitl)
        trace.append("planner:hitl_override")
    # Config override: force HITL for all executable queries when enabled
    if settings.get("agent_force_hitl") and query_type != "ontology_only":
        require_hitl = True

    plan = planned.get("plan") or _heuristic_plan(question)["plan"]
    reasoning = planned.get("reasoning") or ""

    # Procedure hint from memory_load
    procedures = state.get("matched_procedures") or []
    if procedures and not planned.get("reasoning"):
        top = procedures[0]
        reasoning = f"Matched procedure '{top.get('name')}' (score={top.get('match_score')})."

    trace.append(f"planner:query_type={query_type}")
    if require_hitl:
        trace.append("planner:hitl_required")

    return {
        "plan": plan,
        "query_type": query_type,
        "reasoning": reasoning,
        "require_human_approval": require_hitl,
        "max_retries": max_retries,
        "query_attempts": 0,
        "status": "planning",
        "errors": list(state.get("errors") or []),
        "trace": trace,
    }
