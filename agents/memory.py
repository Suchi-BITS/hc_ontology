"""Knowledge-graph based memory for multi-agent runs (Neo4j)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from neo4j import GraphDatabase

from core.config import get_settings

logger = logging.getLogger("healthcare_ontology.agent")


class AgentMemoryStore:
    """Persist agent sessions/turns and retrieve prior context from Neo4j.

    Graph model
    -----------
    (:AgentSession {session_id})-[:HAS_TURN]->(:AgentTurn {turn_id, question, ...})
    (:AgentTurn)-[:USED_CONCEPT]->(:OntologyConcept {name})  # when present
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
                auth=(self._user, self._password),
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

    def load_context(self, session_id: str, limit: int = 5) -> str:
        """Return a short natural-language summary of recent turns."""
        if not session_id:
            return ""
        try:
            driver = self._connect()
            with driver.session(database=self._database) as session:
                rows = session.run(
                    """
                    MATCH (s:AgentSession {session_id: $sid})-[:HAS_TURN]->(t:AgentTurn)
                    RETURN t.question AS question,
                           t.answer AS answer,
                           t.query_type AS query_type,
                           t.created_at AS created_at
                    ORDER BY t.created_at DESC
                    LIMIT $limit
                    """,
                    sid=session_id,
                    limit=limit,
                )
                turns = list(rows)
        except Exception as exc:
            logger.warning("Agent memory load failed: %s", exc)
            return ""

        if not turns:
            return ""

        lines = ["Prior conversation context (most recent first):"]
        for row in turns:
            q = (row.get("question") or "")[:200]
            a = (row.get("answer") or "")[:300]
            lines.append(f"- Q: {q}")
            if a:
                lines.append(f"  A: {a}")
        return "\n".join(lines)

    def save_turn(
        self,
        *,
        session_id: str,
        thread_id: str,
        question: str,
        answer: str,
        query_type: str,
        draft_query: str = "",
        status: str = "completed",
        concept_names: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Persist a completed (or failed) agent turn. Returns turn_id."""
        turn_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        concept_names = concept_names or []
        meta = metadata or {}

        try:
            driver = self._connect()
            with driver.session(database=self._database) as session:
                session.run(
                    """
                    MERGE (s:AgentSession {session_id: $session_id})
                    ON CREATE SET s.created_at = $created_at
                    SET s.updated_at = $created_at,
                        s.last_thread_id = $thread_id
                    CREATE (t:AgentTurn {
                        turn_id: $turn_id,
                        thread_id: $thread_id,
                        question: $question,
                        answer: $answer,
                        query_type: $query_type,
                        draft_query: $draft_query,
                        status: $status,
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
                    status=status,
                    created_at=created_at,
                    metadata_json=str(meta)[:2000],
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
        except Exception as exc:
            logger.warning("Agent memory save failed: %s", exc)
        return turn_id


_memory: AgentMemoryStore | None = None


def get_agent_memory() -> AgentMemoryStore:
    global _memory
    if _memory is None:
        _memory = AgentMemoryStore()
    return _memory
