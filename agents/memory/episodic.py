"""Episodic memory — session turns and past interaction events (Neo4j)."""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from neo4j import GraphDatabase

from core.config import get_settings, require_neo4j_password
from enterprise.lexical_memory import expand_tokens, extract_tokens, overlap_score

logger = logging.getLogger("healthcare_ontology.agent")

_TOKEN = re.compile(r"[a-z0-9]+", re.I)


class EpisodicMemoryStore:
    """Persist and retrieve agent sessions, turns, and events.

    Graph model
    -----------
    (:AgentSession)-[:HAS_TURN]->(:AgentTurn)
    (:AgentTurn)-[:HAS_EVENT]->(:AgentEvent)
    (:AgentTurn)-[:USED_CONCEPT]->(:OntologyConcept)
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._uri = settings["neo4j_uri"]
        self._user = settings["neo4j_username"]
        self._password = settings["neo4j_password"]
        self._database = settings["neo4j_database"]
        self._driver = None

    def _connect(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self._uri,
                auth=(self._user, require_neo4j_password()),
            )
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def ensure_schema(self) -> None:
        driver = self._connect()
        with driver.session(database=self._database) as session:
            session.run(
                "CREATE CONSTRAINT agent_session_id IF NOT EXISTS "
                "FOR (s:AgentSession) REQUIRE s.session_id IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT agent_turn_id IF NOT EXISTS "
                "FOR (t:AgentTurn) REQUIRE t.turn_id IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT agent_event_id IF NOT EXISTS "
                "FOR (e:AgentEvent) REQUIRE e.event_id IS UNIQUE"
            )

    def load_context(
        self,
        session_id: str,
        *,
        limit: int = 5,
        tenant_id: str = "default",
        exclude_archived: bool = True,
    ) -> str:
        """Return a short natural-language summary of recent turns."""
        turns = self.fetch_turns(
            session_id,
            limit=limit,
            tenant_id=tenant_id,
            exclude_archived=exclude_archived,
        )
        if not turns:
            return ""

        lines = ["Prior conversation context (most recent first):"]
        for row in turns:
            q = (row.get("question") or "")[:200]
            a = (row.get("answer") or "")[:300]
            status = row.get("status") or ""
            lines.append(f"- Q: {q}")
            if a:
                lines.append(f"  A: {a}")
            if status:
                lines.append(f"  (status={status})")
        return "\n".join(lines)

    def count_turns(self, session_id: str, *, tenant_id: str = "default") -> int:
        if not session_id:
            return 0
        try:
            driver = self._connect()
            with driver.session(database=self._database) as session:
                row = session.run(
                    """
                    MATCH (s:AgentSession {session_id: $sid})-[:HAS_TURN]->(t:AgentTurn)
                    WHERE coalesce(s.tenant_id, $tenant_id) = $tenant_id
                    RETURN count(t) AS cnt
                    """,
                    sid=session_id,
                    tenant_id=tenant_id,
                ).single()
                return int(row["cnt"]) if row else 0
        except Exception as exc:
            logger.warning("Episodic count_turns failed: %s", exc)
            return 0

    def fetch_turns(
        self,
        session_id: str,
        *,
        limit: int = 20,
        tenant_id: str = "default",
        exclude_archived: bool = True,
    ) -> list[dict[str, Any]]:
        """Return raw turn dicts for meta-memory scoring."""
        if not session_id:
            return []
        try:
            driver = self._connect()
            with driver.session(database=self._database) as session:
                rows = session.run(
                    """
                    MATCH (s:AgentSession {session_id: $sid})-[:HAS_TURN]->(t:AgentTurn)
                    WHERE coalesce(s.tenant_id, $tenant_id) = $tenant_id
                      AND ($exclude_archived = false OR coalesce(t.archived, false) = false)
                    RETURN t.turn_id AS turn_id,
                           t.question AS question,
                           t.answer AS answer,
                           t.query_type AS query_type,
                           t.status AS status,
                           t.confidence AS confidence,
                           t.refused AS refused,
                           t.validated_query AS validated_query,
                           t.draft_query AS draft_query,
                           t.created_at AS created_at
                    ORDER BY t.created_at DESC
                    LIMIT $limit
                    """,
                    sid=session_id,
                    tenant_id=tenant_id,
                    limit=limit,
                    exclude_archived=exclude_archived,
                )
                return [dict(row) for row in rows]
        except Exception as exc:
            logger.warning("Episodic fetch_turns failed: %s", exc)
            return []

    def get_session_summary(self, session_id: str, *, tenant_id: str = "default") -> str:
        if not session_id:
            return ""
        try:
            driver = self._connect()
            with driver.session(database=self._database) as session:
                row = session.run(
                    """
                    MATCH (s:AgentSession {session_id: $sid})-[:HAS_SUMMARY]->(sum:SessionSummary)
                    WHERE coalesce(s.tenant_id, $tenant_id) = $tenant_id
                    RETURN sum.summary_text AS summary_text
                    ORDER BY sum.created_at DESC
                    LIMIT 1
                    """,
                    sid=session_id,
                    tenant_id=tenant_id,
                ).single()
                return (row.get("summary_text") or "") if row else ""
        except Exception as exc:
            logger.warning("Episodic get_session_summary failed: %s", exc)
            return ""

    def archive_old_turns(
        self,
        session_id: str,
        *,
        keep_recent: int = 5,
        tenant_id: str = "default",
    ) -> dict[str, Any]:
        """Summarize and archive turns beyond the hot-recall window."""
        if not session_id:
            return {"archived_count": 0}
        try:
            driver = self._connect()
            with driver.session(database=self._database) as session:
                rows = session.run(
                    """
                    MATCH (s:AgentSession {session_id: $sid})-[:HAS_TURN]->(t:AgentTurn)
                    WHERE coalesce(s.tenant_id, $tenant_id) = $tenant_id
                      AND coalesce(t.archived, false) = false
                    RETURN t.turn_id AS turn_id,
                           t.question AS question,
                           t.answer AS answer,
                           t.status AS status,
                           t.created_at AS created_at
                    ORDER BY t.created_at ASC
                    """,
                    sid=session_id,
                    tenant_id=tenant_id,
                )
                turns = list(rows)
        except Exception as exc:
            logger.warning("Episodic archive_old_turns fetch failed: %s", exc)
            return {"archived_count": 0, "error": str(exc)}

        if len(turns) <= keep_recent:
            return {"archived_count": 0, "skipped": "below_threshold"}

        to_archive = turns[: len(turns) - keep_recent]
        summary_lines = [
            f"Archived {len(to_archive)} prior turn(s) from this session.",
        ]
        for row in to_archive[-8:]:
            q = (row.get("question") or "")[:120]
            a = (row.get("answer") or "")[:160]
            summary_lines.append(f"- Q: {q}")
            if a:
                summary_lines.append(f"  A: {a}")
        summary_text = "\n".join(summary_lines)[:4000]
        summary_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        turn_ids = [row["turn_id"] for row in to_archive if row.get("turn_id")]

        try:
            driver = self._connect()
            with driver.session(database=self._database) as session:
                session.run(
                    """
                    MATCH (s:AgentSession {session_id: $sid})
                    WHERE coalesce(s.tenant_id, $tenant_id) = $tenant_id
                    CREATE (sum:SessionSummary {
                        summary_id: $summary_id,
                        summary_text: $summary_text,
                        archived_turn_count: $archived_count,
                        created_at: $created_at
                    })
                    CREATE (s)-[:HAS_SUMMARY]->(sum)
                    """,
                    sid=session_id,
                    tenant_id=tenant_id,
                    summary_id=summary_id,
                    summary_text=summary_text,
                    archived_count=len(to_archive),
                    created_at=created_at,
                )
                session.run(
                    """
                    MATCH (t:AgentTurn)
                    WHERE t.turn_id IN $turn_ids
                    SET t.archived = true,
                        t.archived_at = $created_at
                    """,
                    turn_ids=turn_ids,
                    created_at=created_at,
                )
        except Exception as exc:
            logger.warning("Episodic archive_old_turns write failed: %s", exc)
            return {"archived_count": 0, "error": str(exc)}

        return {
            "archived_count": len(to_archive),
            "summary_id": summary_id,
            "keep_recent": keep_recent,
        }

    def purge_failed_turns(
        self,
        session_id: str,
        *,
        tenant_id: str = "default",
        older_than_hours: int = 24,
    ) -> int:
        """Delete failed turns older than TTL (opt-in; off by default)."""
        if not session_id:
            return 0
        cutoff = datetime.now(timezone.utc).timestamp() - older_than_hours * 3600
        cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
        try:
            driver = self._connect()
            with driver.session(database=self._database) as session:
                result = session.run(
                    """
                    MATCH (s:AgentSession {session_id: $sid})-[:HAS_TURN]->(t:AgentTurn)
                    WHERE coalesce(s.tenant_id, $tenant_id) = $tenant_id
                      AND t.status = 'failed'
                      AND t.created_at < $cutoff
                    DETACH DELETE t
                    RETURN count(*) AS deleted
                    """,
                    sid=session_id,
                    tenant_id=tenant_id,
                    cutoff=cutoff_iso,
                ).single()
                return int(result["deleted"]) if result else 0
        except Exception as exc:
            logger.warning("Episodic purge_failed_turns failed: %s", exc)
            return 0

    def search_similar_episodes(
        self,
        question: str,
        *,
        tenant_id: str = "default",
        limit: int = 3,
        min_status: str = "completed",
    ) -> list[dict[str, Any]]:
        """Keyword overlap search over past successful turns."""
        tokens = extract_tokens(question)
        expanded = expand_tokens(tokens)
        if not expanded:
            return []
        try:
            driver = self._connect()
            with driver.session(database=self._database) as session:
                rows = session.run(
                    """
                    MATCH (s:AgentSession)-[:HAS_TURN]->(t:AgentTurn)
                    WHERE coalesce(s.tenant_id, $tenant_id) = $tenant_id
                      AND t.status = $min_status
                      AND t.validated_query IS NOT NULL
                    RETURN t.turn_id AS turn_id,
                           t.question AS question,
                           t.validated_query AS validated_query,
                           t.draft_query AS draft_query,
                           t.query_type AS query_type,
                           t.confidence AS confidence,
                           t.created_at AS created_at
                    ORDER BY t.created_at DESC
                    LIMIT 50
                    """,
                    tenant_id=tenant_id,
                    min_status=min_status,
                )
                candidates = list(rows)
        except Exception as exc:
            logger.warning("Episodic similarity search failed: %s", exc)
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in candidates:
            haystack = " ".join(
                [
                    row.get("question") or "",
                    row.get("validated_query") or "",
                    row.get("draft_query") or "",
                ]
            )
            score = overlap_score(expanded, haystack)
            if score <= 0:
                continue
            scored.append((score, dict(row)))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, row in scored[:limit]:
            row["match_score"] = round(score, 4)
            out.append(row)
        return out

    def save_turn(
        self,
        *,
        session_id: str,
        thread_id: str,
        question: str,
        answer: str,
        query_type: str,
        draft_query: str = "",
        validated_query: str = "",
        status: str = "completed",
        tenant_id: str = "default",
        user_id: str = "",
        confidence: float | None = None,
        refused: bool = False,
        refusal_reason: str | None = None,
        concept_names: Optional[list[str]] = None,
        events: Optional[list[dict[str, Any]]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Persist a completed (or failed) agent turn. Returns turn_id."""
        turn_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        concept_names = concept_names or []
        events = events or []
        meta = metadata or {}

        try:
            driver = self._connect()
            with driver.session(database=self._database) as session:
                session.run(
                    """
                    MERGE (s:AgentSession {session_id: $session_id})
                    ON CREATE SET s.created_at = $created_at,
                                  s.tenant_id = $tenant_id,
                                  s.user_id = $user_id
                    SET s.updated_at = $created_at,
                        s.last_thread_id = $thread_id,
                        s.tenant_id = $tenant_id,
                        s.user_id = coalesce(s.user_id, $user_id)
                    CREATE (t:AgentTurn {
                        turn_id: $turn_id,
                        thread_id: $thread_id,
                        question: $question,
                        answer: $answer,
                        query_type: $query_type,
                        draft_query: $draft_query,
                        validated_query: $validated_query,
                        status: $status,
                        confidence: $confidence,
                        refused: $refused,
                        refusal_reason: $refusal_reason,
                        created_at: $created_at,
                        metadata_json: $metadata_json
                    })
                    CREATE (s)-[:HAS_TURN]->(t)
                    """,
                    session_id=session_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    question=question,
                    answer=(answer or "")[:4000],
                    query_type=query_type or "",
                    draft_query=(draft_query or "")[:4000],
                    validated_query=(validated_query or "")[:4000],
                    status=status,
                    confidence=confidence,
                    refused=refused,
                    refusal_reason=refusal_reason or "",
                    created_at=created_at,
                    tenant_id=tenant_id,
                    user_id=user_id or "",
                    metadata_json=json.dumps(meta)[:8000],
                )
                for name in concept_names[:20]:
                    if not name:
                        continue
                    session.run(
                        """
                        MATCH (t:AgentTurn {turn_id: $turn_id})
                        OPTIONAL MATCH (c:OntologyConcept {name: $name})
                        FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
                            MERGE (t)-[:USED_CONCEPT]->(c)
                        )
                        """,
                        turn_id=turn_id,
                        name=name,
                    )
                for ev in events[:30]:
                    event_id = str(uuid.uuid4())
                    session.run(
                        """
                        MATCH (t:AgentTurn {turn_id: $turn_id})
                        CREATE (e:AgentEvent {
                            event_id: $event_id,
                            type: $type,
                            payload_json: $payload_json,
                            created_at: $created_at
                        })
                        CREATE (t)-[:HAS_EVENT]->(e)
                        """,
                        turn_id=turn_id,
                        event_id=event_id,
                        type=str(ev.get("type") or "event")[:64],
                        payload_json=json.dumps(ev.get("payload") or {})[:4000],
                        created_at=ev.get("ts") or created_at,
                    )
        except Exception as exc:
            logger.warning("Episodic memory save failed: %s", exc)
        return turn_id


_episodic: EpisodicMemoryStore | None = None


def get_episodic_memory() -> EpisodicMemoryStore:
    global _episodic
    if _episodic is None:
        _episodic = EpisodicMemoryStore()
    return _episodic
