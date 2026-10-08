"""Meta-memory — monitor, score, and govern the four memory stores.

Meta-memory is the control plane above working, episodic, procedural, and semantic
memory. It decides what to recall into the prompt budget, what to archive after a
session grows, and when procedural templates have gone stale.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.config import get_settings
from enterprise.lexical_memory import overlap_score, extract_tokens, expand_tokens

logger = logging.getLogger("healthcare_ontology.agent")

_TOKEN = re.compile(r"[a-z0-9]+", re.I)


@dataclass
class RecallPlan:
    """Recall policy for a single agent turn."""

    episodic_limit: int = 5
    similar_limit: int = 3
    max_chars: int = 6000
    session_summary: str = ""
    selected_turn_ids: list[str] = field(default_factory=list)
    recall_confidence: float = 0.0
    context_pressure: bool = False
    signals: dict[str, Any] = field(default_factory=dict)
    scored_turns: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("scored_turns", None)
        return data


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if len(t) > 2]


def _keyword_overlap(a_tokens: list[str], b_text: str) -> float:
    if not a_tokens:
        return 0.0
    haystack = (b_text or "").lower()
    overlap = sum(1 for t in a_tokens if t in haystack)
    return overlap / max(len(a_tokens), 1)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _recency_score(created_at: str | None, *, half_life_hours: float = 48.0) -> float:
    dt = _parse_iso(created_at)
    if dt is None:
        return 0.5
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_hours = max(
        0.0,
        (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600.0,
    )
    return math.exp(-age_hours / max(half_life_hours, 1.0))


def score_turn(
    turn: dict[str, Any],
    question: str,
    *,
    weights: dict[str, float] | None = None,
) -> float:
    """Score an episodic turn for retention in working context."""
    w = weights or {
        "relevance": 0.40,
        "utility": 0.30,
        "salience": 0.15,
        "recency": 0.15,
    }
    q_tokens = _tokenize(question)
    turn_text = " ".join(
        [
            turn.get("question") or "",
            turn.get("validated_query") or "",
            turn.get("answer") or "",
        ]
    )
    relevance = max(
        _keyword_overlap(q_tokens, turn.get("question") or ""),
        overlap_score(q_tokens, turn_text) * 0.95,
    )
    status = (turn.get("status") or "").lower()
    conf = float(turn.get("confidence") or 0.0)
    utility = conf if status == "completed" else 0.0
    if turn.get("refused"):
        utility *= 0.25
    salience = 0.0
    if turn.get("validated_query"):
        salience += 0.6
    if turn.get("answer"):
        salience += 0.2
    if status == "failed":
        salience = 0.0
        utility = 0.0
    recency = _recency_score(turn.get("created_at"))
    return (
        w["relevance"] * relevance
        + w["utility"] * utility
        + w["salience"] * salience
        + w["recency"] * recency
    )


def format_scored_turns(turns: list[dict[str, Any]], *, header: str | None = None) -> str:
    """Render scored episodic turns for working-context injection."""
    if not turns:
        return ""
    lines = [header or "Prior conversation context (ranked by relevance):"]
    for row in turns:
        q = (row.get("question") or "")[:200]
        a = (row.get("answer") or "")[:300]
        status = row.get("status") or ""
        score = row.get("_meta_score")
        suffix = f" (score={score:.2f})" if isinstance(score, (int, float)) else ""
        lines.append(f"- Q: {q}{suffix}")
        if a:
            lines.append(f"  A: {a}")
        if status:
            lines.append(f"  (status={status})")
    return "\n".join(lines)


class MetaMemoryController:
    """Govern recall limits, scoring, archival, and procedural decay."""

    def __init__(self) -> None:
        from agents.memory.episodic import get_episodic_memory
        from agents.memory.procedural import get_procedural_memory

        self.episodic = get_episodic_memory()
        self.procedural = get_procedural_memory()

    def plan_recall(
        self,
        *,
        question: str,
        session_id: str = "",
        tenant_id: str = "default",
        query_type: str | None = None,
    ) -> RecallPlan:
        """Decide episodic/procedural recall limits and score session turns."""
        settings = get_settings()
        if not settings.get("meta_memory_enabled", True):
            return RecallPlan(
                episodic_limit=int(settings.get("episodic_context_turns", 5)),
                similar_limit=int(settings.get("episodic_similar_top_k", 3)),
                max_chars=int(settings.get("working_memory_max_chars", 6000)),
                recall_confidence=0.5,
                signals={"enabled": False},
            )

        base_episodic = int(settings.get("episodic_context_turns", 5))
        base_similar = int(settings.get("episodic_similar_top_k", 3))
        max_chars = int(settings.get("working_memory_max_chars", 6000))
        retain_threshold = float(settings.get("meta_memory_retain_threshold", 0.35))
        archive_turns_at = int(settings.get("meta_memory_session_archive_turns", 15))

        turn_count = 0
        session_summary = ""
        selected_turn_ids: list[str] = []
        recall_confidence = 0.0
        context_pressure = False
        scored_turns: list[dict[str, Any]] = []

        if session_id:
            turn_count = self.episodic.count_turns(session_id, tenant_id=tenant_id)
            session_summary = self.episodic.get_session_summary(session_id, tenant_id=tenant_id)
            context_pressure = turn_count > archive_turns_at // 2

            fetch_limit = max(base_episodic * 3, 15)
            raw_turns = self.episodic.fetch_turns(
                session_id, limit=fetch_limit, tenant_id=tenant_id
            )
            for turn in raw_turns:
                turn["_meta_score"] = round(score_turn(turn, question), 4)
            raw_turns.sort(key=lambda t: t.get("_meta_score", 0.0), reverse=True)
            scored_turns = [
                t for t in raw_turns if float(t.get("_meta_score") or 0.0) >= retain_threshold
            ]
            if not scored_turns and raw_turns:
                scored_turns = raw_turns[:base_episodic]
            selected_turn_ids = [str(t.get("turn_id") or "") for t in scored_turns[:base_episodic]]
            if scored_turns:
                top = float(scored_turns[0].get("_meta_score") or 0.0)
                recall_confidence = min(1.0, top + 0.15 * min(len(scored_turns), 3))

        episodic_limit = base_episodic
        similar_limit = base_similar
        if context_pressure:
            episodic_limit = max(2, base_episodic - 2)
            similar_limit = max(1, base_similar - 1)
            max_chars = max(3000, int(max_chars * 0.85))

        signals = {
            "enabled": True,
            "turn_count": turn_count,
            "context_pressure": context_pressure,
            "retain_threshold": retain_threshold,
            "selected_turn_count": len(selected_turn_ids),
            "session_summary_present": bool(session_summary),
            "scored_turns": [
                {
                    "turn_id": t.get("turn_id"),
                    "score": t.get("_meta_score"),
                    "status": t.get("status"),
                }
                for t in scored_turns[:5]
            ],
        }

        plan = RecallPlan(
            episodic_limit=episodic_limit,
            similar_limit=similar_limit,
            max_chars=max_chars,
            session_summary=session_summary,
            selected_turn_ids=selected_turn_ids,
            recall_confidence=round(recall_confidence, 4),
            context_pressure=context_pressure,
            signals=signals,
            scored_turns=scored_turns[: episodic_limit],
        )
        return plan

    def build_episodic_context(
        self,
        plan: RecallPlan,
        *,
        session_id: str,
        tenant_id: str = "default",
    ) -> str:
        """Build episodic recent_text using meta-memory scoring."""
        parts: list[str] = []
        if plan.session_summary:
            parts.append(f"Session summary (archived context):\n{plan.session_summary}")
        if plan.scored_turns:
            parts.append(
                format_scored_turns(
                    plan.scored_turns,
                    header="Prior conversation context (meta-memory ranked):",
                )
            )
        elif session_id:
            parts.append(
                self.episodic.load_context(
                    session_id,
                    limit=plan.episodic_limit,
                    tenant_id=tenant_id,
                )
            )
        return "\n\n".join(p for p in parts if p.strip())

    def post_turn(
        self,
        *,
        session_id: str,
        tenant_id: str = "default",
        turn_id: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        """Archive old turns, optionally purge failures, decay stale procedures."""
        settings = get_settings()
        if not settings.get("meta_memory_enabled", True) or not session_id:
            return {"enabled": False}

        archive_at = int(settings.get("meta_memory_session_archive_turns", 15))
        keep_recent = int(settings.get("meta_memory_keep_recent_turns", 5))
        purge_failed = settings.get("meta_memory_purge_failed", False)
        failed_ttl = int(settings.get("meta_memory_failed_ttl_hours", 24))
        decay_days = int(settings.get("meta_memory_procedure_decay_days", 30))

        result: dict[str, Any] = {
            "enabled": True,
            "turn_id": turn_id,
            "archived": {},
            "purged_failed": 0,
            "procedures_decayed": 0,
        }

        turn_count = self.episodic.count_turns(session_id, tenant_id=tenant_id)
        if turn_count >= archive_at:
            result["archived"] = self.episodic.archive_old_turns(
                session_id,
                keep_recent=keep_recent,
                tenant_id=tenant_id,
            )

        if purge_failed and status == "failed":
            result["purged_failed"] = self.episodic.purge_failed_turns(
                session_id,
                tenant_id=tenant_id,
                older_than_hours=failed_ttl,
            )

        result["procedures_decayed"] = self.procedural.decay_unused(
            tenant_id=tenant_id,
            stale_after_days=decay_days,
        )
        return result


_controller: MetaMemoryController | None = None


def get_meta_memory_controller() -> MetaMemoryController:
    global _controller
    if _controller is None:
        _controller = MetaMemoryController()
    return _controller
