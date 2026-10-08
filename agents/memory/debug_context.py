"""Terminal debug output for memory assembly and semantic enrichment."""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

from core.config import get_settings

logger = logging.getLogger("healthcare_ontology.agent.memory")

_REPAIR_SECTION = re.compile(r"### Repair context\s*\n([\s\S]*?)(?=\n### |\Z)")


def memory_debug_enabled() -> bool:
    return bool(get_settings().get("memory_debug_context", False))


def memory_debug_full() -> bool:
    return bool(get_settings().get("memory_debug_context_full", False))


def _emit_terminal(msg: str) -> None:
    """Write memory debug once to stderr (visible in the uvicorn/Cursor terminal)."""
    try:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def _text_limit(default: int) -> int:
    return default * 4 if memory_debug_full() else default


def _truncate(text: str, limit: int = 1200) -> str:
    text = (text or "").strip()
    limit = _text_limit(limit)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _concept_names(concepts: list[Any], limit: int = 12) -> list[str]:
    names: list[str] = []
    for item in concepts[:limit]:
        if isinstance(item, dict):
            name = item.get("name") or item.get("concept")
            if name:
                names.append(str(name))
        elif item:
            names.append(str(item))
    return names


def _similar_episodes_preview(episodes: list[Any], limit: int = 3) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ep in episodes[:limit]:
        if not isinstance(ep, dict):
            continue
        out.append(
            {
                "question": _truncate(ep.get("question") or "", 200),
                "validated_query": _truncate(
                    ep.get("validated_query") or ep.get("draft_query") or "", 300
                ),
                "status": ep.get("status"),
                "score": ep.get("score") or ep.get("similarity"),
            }
        )
    return out


def _procedural_preview(procedures: list[Any], limit: int = 5) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for proc in procedures[:limit]:
        if not isinstance(proc, dict):
            continue
        out.append(
            {
                "name": proc.get("name"),
                "match_score": proc.get("match_score"),
                "query_type": proc.get("query_type"),
                "success_count": proc.get("success_count"),
                "template_query": _truncate(proc.get("template_query") or "", 400),
            }
        )
    return out


def _repair_preview(working_context: str) -> dict[str, Any] | None:
    if not working_context:
        return None
    match = _REPAIR_SECTION.search(working_context)
    if not match:
        return None
    body = (match.group(1) or "").strip()
    if not body:
        return None
    return {"present": True, "body": _truncate(body, 600)}


def snapshot_recall_plan(plan: Any) -> dict[str, Any]:
    """Full meta-memory recall plan for logging."""
    if hasattr(plan, "to_dict"):
        data = dict(plan.to_dict())
    elif isinstance(plan, dict):
        data = dict(plan)
    else:
        return {"raw": str(plan)}
    if data.get("session_summary"):
        data["session_summary"] = _truncate(str(data["session_summary"]), 500)
    signals = data.get("signals") or {}
    if signals.get("scored_turns"):
        signals = dict(signals)
        for row in signals["scored_turns"]:
            if isinstance(row, dict) and row.get("question"):
                row["question"] = _truncate(str(row["question"]), 120)
        data["signals"] = signals
    return data


def snapshot_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """Compact view of agent memory fields for logging."""
    bundle = state.get("memory_bundle") or {}
    episodic = bundle.get("episodic") or {}
    semantic = bundle.get("semantic") or {}
    meta = state.get("meta_memory") or {}
    working = state.get("working_context") or state.get("memory_context") or ""
    procedures = bundle.get("procedural") or state.get("matched_procedures") or []
    similar = episodic.get("similar_episodes") or []

    repair = _repair_preview(working)
    if not repair and state.get("validation_error") and state.get("draft_query"):
        repair = {
            "present": True,
            "body": _truncate(
                f"Previous query failed:\n{state.get('draft_query')}\n"
                f"Error: {state.get('validation_error')}\n"
                "Generate a corrected query.",
                600,
            ),
        }

    return {
        "question": state.get("question") or "",
        "session_id": state.get("session_id") or "",
        "tenant_id": state.get("tenant_id") or "",
        "query_type": state.get("query_type"),
        "query_attempts": state.get("query_attempts"),
        "validation_ok": state.get("validation_ok"),
        "validation_error": state.get("validation_error"),
        "draft_query_preview": _truncate(state.get("draft_query") or "", 400),
        "validated_query_preview": _truncate(state.get("validated_query") or "", 400),
        "meta_memory": snapshot_recall_plan(meta) if meta else {},
        "episodic": {
            "recent_text_len": len(episodic.get("recent_text") or ""),
            "recent_text_preview": _truncate(episodic.get("recent_text") or "", 500),
            "similar_count": len(similar),
            "similar_episodes": _similar_episodes_preview(similar),
            "session_summary_len": len(episodic.get("session_summary") or ""),
            "session_summary_preview": _truncate(episodic.get("session_summary") or "", 300),
        },
        "procedural": _procedural_preview(procedures),
        "semantic": {
            "concept_count": len(semantic.get("concepts") or state.get("retrieved_concepts") or []),
            "concepts": _concept_names(
                semantic.get("concepts") or state.get("retrieved_concepts") or []
            ),
            "document_count": len(semantic.get("document_sections") or semantic.get("sections") or []),
            "hybrid_meta": semantic.get("hybrid_meta") or state.get("hybrid_meta") or {},
            "retrieval_meta": semantic.get("retrieval_meta") or state.get("retrieval_meta") or {},
            "schema_excerpt_len": len(semantic.get("schema_excerpt") or ""),
        },
        "repair_context": repair,
        "working_events": [
            {
                "type": e.get("type"),
                "payload": e.get("payload"),
            }
            for e in (state.get("working_events") or [])[-6:]
            if isinstance(e, dict)
        ],
        "working_context_len": len(working),
        "working_context": _truncate(working, 2000),
        "ontology_context_len": len(state.get("ontology_context") or ""),
        "ontology_context": _truncate(state.get("ontology_context") or "", 1200),
        "trace_tail": list(state.get("trace") or [])[-8:],
    }


def snapshot_from_assembled(assembled: dict[str, Any], *, question: str, session_id: str) -> dict[str, Any]:
    return snapshot_from_state(
        {
            "question": question,
            "session_id": session_id,
            **assembled,
        }
    )


def snapshot_query_grounding(state: dict[str, Any], *, grounded: str, procedure_reused: bool) -> dict[str, Any]:
    snap = snapshot_from_state(state)
    snap["grounded_context_len"] = len(grounded or "")
    snap["grounded_context"] = _truncate(grounded or "", 2500)
    snap["procedure_template_reused"] = procedure_reused
    return snap


def snapshot_commit_result(
    *,
    turn_id: str,
    status: str,
    procedure_id: str | None,
    meta_post: dict[str, Any],
) -> dict[str, Any]:
    return {
        "turn_id": turn_id,
        "status": status,
        "procedure_learned_id": procedure_id,
        "meta_post_turn": meta_post,
    }


def log_memory_phase(
    phase: str,
    *,
    question: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Print a before/after memory snapshot to the API terminal."""
    if not memory_debug_enabled():
        return

    lines = [
        "",
        "=" * 78,
        f"MEMORY DEBUG — {phase}",
        f"question: {question[:300]}",
    ]
    if before is not None:
        lines.append("-" * 78)
        lines.append("BEFORE:")
        lines.append(json.dumps(before, indent=2, default=str))
    if after is not None:
        lines.append("-" * 78)
        lines.append("AFTER:")
        lines.append(json.dumps(after, indent=2, default=str))
    lines.append("=" * 78)

    msg = "\n".join(lines)
    _emit_terminal(msg)
    logger.info("memory debug phase=%s", phase)
