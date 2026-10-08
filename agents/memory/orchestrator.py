"""Memory orchestrator — assemble and commit all four memory types."""

from __future__ import annotations

import logging
from typing import Any

from agents.memory.debug_context import (
    log_memory_phase,
    snapshot_commit_result,
    snapshot_from_assembled,
    snapshot_from_state,
    snapshot_recall_plan,
)
from agents.memory.episodic import get_episodic_memory
from agents.memory.meta_memory import get_meta_memory_controller
from agents.memory.procedural import get_procedural_memory
from agents.memory.semantic import format_semantic_context, retrieve_semantic_memory
from agents.memory.working import append_working_event, compact_working_context
from core.config import get_settings

logger = logging.getLogger("healthcare_ontology.agent")


class MemoryOrchestrator:
    """Coordinate working, episodic, procedural, and semantic memory."""

    def __init__(self) -> None:
        self.episodic = get_episodic_memory()
        self.procedural = get_procedural_memory()
        self.meta = get_meta_memory_controller()

    def ensure_schema(self) -> None:
        self.episodic.ensure_schema()
        self.procedural.ensure_schema()
        # SessionSummary nodes use MERGE on write; no extra constraint required

    def assemble_context(
        self,
        *,
        question: str,
        session_id: str = "",
        tenant_id: str = "default",
        user_id: str = "",
        query_type: str | None = None,
        include_semantic: bool = False,
    ) -> dict[str, Any]:
        """Load episodic + procedural memory; optionally semantic."""
        settings = get_settings()
        recall_plan = self.meta.plan_recall(
            question=question,
            session_id=session_id,
            tenant_id=tenant_id,
            query_type=query_type,
        )
        log_memory_phase(
            "assemble_context (before)",
            question=question,
            before={
                "session_id": session_id,
                "tenant_id": tenant_id,
                "query_type": query_type,
                "include_semantic": include_semantic,
                "meta_recall_plan": snapshot_recall_plan(recall_plan),
            },
        )
        episodic_limit = recall_plan.episodic_limit
        similar_limit = recall_plan.similar_limit

        recent_text = ""
        similar_episodes: list[dict[str, Any]] = []
        if session_id:
            recent_text = self.meta.build_episodic_context(
                recall_plan,
                session_id=session_id,
                tenant_id=tenant_id,
            )
            similar_episodes = self.episodic.search_similar_episodes(
                question, tenant_id=tenant_id, limit=similar_limit
            )

        procedures = self.procedural.match_procedures(
            question, tenant_id=tenant_id, query_type=query_type
        )

        semantic: dict[str, Any] = {}
        if include_semantic:
            semantic = retrieve_semantic_memory(
                question, tenant_id=tenant_id, include_documents=True
            )

        memory_bundle: dict[str, Any] = {
            "episodic": {
                "recent_text": recent_text,
                "similar_episodes": similar_episodes,
                "session_summary": recall_plan.session_summary,
            },
            "procedural": procedures,
            "semantic": semantic,
        }

        max_chars = recall_plan.max_chars
        working_context = compact_working_context(
            question=question,
            memory_bundle=memory_bundle,
            max_chars=max_chars,
        )

        memory_context = working_context
        working_events = append_working_event([], "memory_assembled", {
            "episodic_turns": bool(recent_text),
            "similar_count": len(similar_episodes),
            "procedure_count": len(procedures),
            "semantic_loaded": bool(semantic),
            "meta_recall_confidence": recall_plan.recall_confidence,
            "meta_context_pressure": recall_plan.context_pressure,
        })

        meta_memory = recall_plan.to_dict()

        assembled = {
            "memory_bundle": memory_bundle,
            "memory_context": memory_context,
            "working_context": working_context,
            "working_events": working_events,
            "matched_procedures": procedures,
            "meta_memory": meta_memory,
        }
        log_memory_phase(
            "assemble_context (after)",
            question=question,
            after=snapshot_from_assembled(assembled, question=question, session_id=session_id),
        )
        return assembled

    def enrich_semantic(
        self,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Run semantic retrieval and refresh working context."""
        settings = get_settings()
        question = state.get("question") or ""
        tenant_id = state.get("tenant_id") or "default"
        log_memory_phase(
            "enrich_semantic (before)",
            question=question,
            before=snapshot_from_state(state),
        )
        bundle = dict(state.get("memory_bundle") or {})

        semantic = retrieve_semantic_memory(
            question, tenant_id=tenant_id, include_documents=True
        )
        bundle["semantic"] = semantic

        ontology_id = state.get("ontology_id") or "hc-core"
        ontology_context = format_semantic_context(semantic, ontology_id=ontology_id)

        max_chars = int(settings.get("working_memory_max_chars", 6000))
        meta = state.get("meta_memory") or {}
        if meta.get("max_chars"):
            max_chars = int(meta["max_chars"])
        working_context = compact_working_context(
            question=question,
            memory_bundle=bundle,
            ontology_context=ontology_context,
            validation_error=state.get("validation_error"),
            draft_query=state.get("draft_query") or "",
            max_chars=max_chars,
        )

        working_events = append_working_event(
            state.get("working_events"),
            "semantic_enriched",
            {"concept_count": len(semantic.get("concepts") or [])},
        )

        enriched = {
            "memory_bundle": bundle,
            "ontology_context": ontology_context,
            "retrieved_concepts": semantic.get("concepts") or [],
            "hybrid_meta": semantic.get("hybrid_meta") or {},
            "retrieval_meta": semantic.get("retrieval_meta") or {},
            "working_context": working_context,
            "memory_context": working_context,
            "working_events": working_events,
            "meta_memory": state.get("meta_memory") or {},
        }
        log_memory_phase(
            "enrich_semantic (after)",
            question=question,
            after=snapshot_from_state({**state, **enriched}),
        )
        return enriched

    def commit_turn(self, state: dict[str, Any], *, answer: str, status: str) -> str:
        """Persist episodic turn, events, and learn procedures."""
        session_id = state.get("session_id")
        if not session_id:
            return ""

        log_memory_phase(
            "commit_turn (before)",
            question=state.get("question") or "",
            before=snapshot_from_state(state),
        )

        concepts = []
        for item in state.get("retrieved_concepts") or []:
            if isinstance(item, dict):
                name = item.get("name") or item.get("concept")
                if name:
                    concepts.append(str(name))

        trace = state.get("trace") or []
        working_events = state.get("working_events") or []
        events = list(working_events)
        for step in trace[-20:]:
            events.append({"type": "trace", "payload": {"step": step}})

        turn_id = self.episodic.save_turn(
            session_id=session_id,
            thread_id=state.get("thread_id") or "",
            question=state.get("question") or "",
            answer=answer,
            query_type=state.get("query_type") or "",
            draft_query=state.get("draft_query") or "",
            validated_query=state.get("validated_query") or "",
            status=status,
            tenant_id=state.get("tenant_id") or "default",
            user_id=state.get("user_id") or "",
            confidence=state.get("confidence"),
            refused=bool(state.get("refused")),
            refusal_reason=state.get("refusal_reason"),
            concept_names=concepts,
            events=events,
            metadata={
                "plan": state.get("plan"),
                "provenance_path_count": (state.get("provenance") or {}).get("path_count"),
                "memory_bundle_keys": list((state.get("memory_bundle") or {}).keys()),
                "matched_procedures": [
                    p.get("name") for p in (state.get("matched_procedures") or [])
                ],
            },
        )

        procedure_id: str | None = None
        if status == "completed" and state.get("validation_ok"):
            procedure_id = self.procedural.learn_from_turn(
                tenant_id=state.get("tenant_id") or "default",
                question=state.get("question") or "",
                query_type=state.get("query_type") or "cypher",
                validated_query=state.get("validated_query") or "",
                plan=state.get("plan"),
                turn_id=turn_id,
                confidence=float(state.get("confidence") or 0.0),
                concept_names=concepts,
            )

        meta_post = self.meta.post_turn(
            session_id=session_id,
            tenant_id=state.get("tenant_id") or "default",
            turn_id=turn_id,
            status=status,
        )

        log_memory_phase(
            "commit_turn (after)",
            question=state.get("question") or "",
            after=snapshot_commit_result(
                turn_id=turn_id,
                status=status,
                procedure_id=procedure_id,
                meta_post=meta_post,
            ),
        )

        return turn_id


_orchestrator: MemoryOrchestrator | None = None


def get_memory_orchestrator() -> MemoryOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MemoryOrchestrator()
    return _orchestrator


# Backward-compatible alias
def get_agent_memory():
    return get_episodic_memory()
