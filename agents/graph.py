"""LangGraph assembly: shared state, conditional routing, retry, HITL."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agents.nodes.execution import execution_node
from agents.nodes.human_gate import human_gate_node, route_after_human
from agents.nodes.ontology import ontology_node
from agents.nodes.planner import planner_node
from agents.nodes.query import query_node
from agents.nodes.response import rejected_node, respond_failed_node, response_node
from agents.nodes.validation import route_after_validation, validation_node
from agents.state import AgentState

logger = logging.getLogger("healthcare_ontology.agent")


def build_agent_graph(*, checkpointer: Any | None = None):
    """Compile the enterprise multi-agent healthcare graph.

    Flow
    ----
    START → planner → ontology → query → validation
         ↳ (retry) ──────────────┘
         ↳ human_gate → execution → response → END
         ↳ respond_failed → END
         ↳ rejected → END
    """
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("ontology", ontology_node)
    graph.add_node("query", query_node)
    graph.add_node("validation", validation_node)
    graph.add_node("human_gate", human_gate_node)
    graph.add_node("execution", execution_node)
    graph.add_node("response", response_node)
    graph.add_node("respond_failed", respond_failed_node)
    graph.add_node("rejected", rejected_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "ontology")
    graph.add_edge("ontology", "query")
    graph.add_edge("query", "validation")

    graph.add_conditional_edges(
        "validation",
        route_after_validation,
        {
            "human_gate": "human_gate",
            "retry_query": "query",
            "respond_failed": "respond_failed",
        },
    )

    graph.add_conditional_edges(
        "human_gate",
        route_after_human,
        {
            "execution": "execution",
            "rejected": "rejected",
        },
    )

    graph.add_edge("execution", "response")
    graph.add_edge("response", END)
    graph.add_edge("respond_failed", END)
    graph.add_edge("rejected", END)

    saver = checkpointer if checkpointer is not None else MemorySaver()
    compiled = graph.compile(checkpointer=saver)
    logger.info("Healthcare multi-agent LangGraph compiled")
    return compiled


@lru_cache
def get_agent_graph():
    return build_agent_graph()


def serialize_state(values: dict[str, Any]) -> dict[str, Any]:
    """Pick API-safe fields from graph state values."""
    keys = [
        "thread_id",
        "session_id",
        "tenant_id",
        "ontology_id",
        "ontology_version",
        "user_id",
        "question",
        "plan",
        "query_type",
        "reasoning",
        "require_human_approval",
        "ontology_context",
        "retrieved_concepts",
        "hybrid_meta",
        "memory_context",
        "draft_query",
        "validated_query",
        "query_attempts",
        "validation_ok",
        "validation_error",
        "validation_stage",
        "human_decision",
        "human_feedback",
        "results",
        "execution_error",
        "answer",
        "citations",
        "status",
        "errors",
        "trace",
        "cost_usd",
        "blocked",
        "guardrail_flags",
    ]
    out = {k: values.get(k) for k in keys if k in values}
    # Truncate bulky fields for HTTP responses
    if isinstance(out.get("results"), list) and len(out["results"]) > 50:
        out["results"] = out["results"][:50]
        out["results_truncated"] = True
    if isinstance(out.get("ontology_context"), str) and len(out["ontology_context"]) > 4000:
        out["ontology_context"] = out["ontology_context"][:4000] + "…"
    return out
