"""Human-in-the-loop gate — interrupt before execution when required."""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from agents.state import AgentState


def human_gate_node(state: AgentState) -> dict[str, Any]:
    """Pause for approval when Planner flagged HITL; otherwise auto-approve."""
    trace = list(state.get("trace") or [])
    query_type = state.get("query_type") or "cypher"

    if query_type == "ontology_only" or not state.get("require_human_approval"):
        trace.append("human_gate:auto_approved")
        return {
            "human_decision": "approved",
            "status": "awaiting_approval",
            "trace": trace,
        }

    payload = {
        "message": "Human approval required before query execution.",
        "question": state.get("question"),
        "query_type": query_type,
        "validated_query": state.get("validated_query") or state.get("draft_query"),
        "plan": state.get("plan"),
        "reasoning": state.get("reasoning"),
        "instructions": "Resume with decision 'approved' or 'rejected' (optional feedback).",
    }
    decision = interrupt(payload)

    # Resume value may be str or dict
    human_decision = "approved"
    human_feedback = None
    if isinstance(decision, dict):
        human_decision = str(decision.get("decision", "approved")).lower()
        human_feedback = decision.get("feedback")
    elif isinstance(decision, str):
        human_decision = decision.lower()

    if human_decision not in ("approved", "rejected"):
        human_decision = "approved"

    trace.append(f"human_gate:{human_decision}")
    return {
        "human_decision": human_decision,
        "human_feedback": human_feedback,
        "status": "awaiting_approval",
        "trace": trace,
    }


def route_after_human(state: AgentState) -> str:
    if state.get("human_decision") == "rejected":
        return "rejected"
    return "execution"
