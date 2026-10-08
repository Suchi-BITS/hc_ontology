"""Working memory — compact active context for the current turn."""

from __future__ import annotations

from typing import Any


def _section(title: str, body: str, max_chars: int) -> str:
    body = (body or "").strip()
    if not body:
        return ""
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    return f"### {title}\n{body}"


def compact_working_context(
    *,
    question: str,
    memory_bundle: dict[str, Any] | None = None,
    ontology_context: str = "",
    validation_error: str | None = None,
    draft_query: str = "",
    max_chars: int = 6000,
) -> str:
    """Build a token-bounded working context with fixed priority."""
    bundle = memory_bundle or {}
    parts: list[str] = []

    q_budget = min(800, max_chars // 8)
    parts.append(_section("Question", question, q_budget))

    procedural = bundle.get("procedural") or []
    if procedural:
        lines = []
        for proc in procedural[:3]:
            if not isinstance(proc, dict):
                continue
            name = proc.get("name") or "procedure"
            template = (proc.get("template_query") or "")[:400]
            score = proc.get("match_score")
            lines.append(f"- {name} (score={score}): {template}")
        parts.append(_section("Relevant procedures", "\n".join(lines), max_chars // 5))

    semantic = bundle.get("semantic") or {}
    concepts = semantic.get("concepts") or bundle.get("semantic_concepts") or []
    if concepts:
        lines = []
        for item in concepts[:8]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('name', '')}")
            else:
                lines.append(f"- {item}")
        parts.append(_section("Semantic concepts", "\n".join(lines), max_chars // 4))

    if ontology_context:
        parts.append(_section("Ontology context", ontology_context, max_chars // 3))

    episodic = bundle.get("episodic") or {}
    recent = episodic.get("recent_text") or episodic.get("summary") or ""
    if recent:
        parts.append(_section("Episodic memory", recent, max_chars // 4))

    similar = episodic.get("similar_episodes") or []
    if similar:
        lines = []
        for ep in similar[:3]:
            if isinstance(ep, dict):
                lines.append(
                    f"- Q: {(ep.get('question') or '')[:120]}\n"
                    f"  Query: {(ep.get('validated_query') or ep.get('draft_query') or '')[:120]}"
                )
        parts.append(_section("Similar past episodes", "\n".join(lines), max_chars // 5))

    if validation_error and draft_query:
        repair = (
            f"Previous query failed:\n{draft_query}\nError: {validation_error}\n"
            "Generate a corrected query."
        )
        parts.append(_section("Repair context", repair, max_chars // 8))

    text = "\n\n".join(p for p in parts if p)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


def append_working_event(
    events: list[dict[str, Any]] | None,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Append a working-memory event for this turn."""
    from datetime import datetime, timezone

    out = list(events or [])
    out.append(
        {
            "type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            "payload": payload or {},
        }
    )
    return out
