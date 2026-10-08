"""Abstention gate — calibrated refusal before natural-language response."""

from __future__ import annotations

import logging
from typing import Any

from agents.state import AgentState
from enterprise.abstention import decide_abstention

logger = logging.getLogger("healthcare_ontology.agent")


def abstention_node(state: AgentState) -> dict[str, Any]:
    trace = list(state.get("trace") or [])
    errors = list(state.get("errors") or [])
    trace.append("abstention:start")

    force_failed = state.get("status") == "failed" or bool(
        state.get("validation_error") and not state.get("validation_ok")
    )
    decision = decide_abstention(state, force_failed=force_failed)

    trace.append(
        f"abstention:{'refused' if decision['refused'] else 'allowed'}:"
        f"{decision.get('refusal_reason') or 'ok'}:"
        f"conf={decision.get('confidence')}"
    )

    return {
        "refused": decision["refused"],
        "refusal_reason": decision.get("refusal_reason"),
        "confidence": decision.get("confidence"),
        "abstention_threshold": decision.get("threshold"),
        "confidence_signals": decision.get("signals"),
        "provenance": decision.get("provenance"),
        "status": "responding",
        "errors": errors,
        "trace": trace,
    }
