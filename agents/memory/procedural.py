"""Procedural memory — reusable query templates and plan patterns (Neo4j)."""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from neo4j import GraphDatabase

from core.config import get_settings, require_neo4j_password
from enterprise.lexical_memory import expand_tokens, extract_tokens, overlap_score, tokens_for_learning

logger = logging.getLogger("healthcare_ontology.agent")

_TOKEN = re.compile(r"[a-z0-9]+", re.I)


class ProceduralMemoryStore:
    """Store and match learned procedures (query templates)."""

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

    def ensure_schema(self) -> None:
        driver = self._connect()
        with driver.session(database=self._database) as session:
            # The ontology has a class `Procedure`, so domain nodes carry the label :Procedure.
            # Procedural memory therefore uses :AgentProcedure. Migrate nodes written under the
            # old label (identified by procedure_id, which domain nodes never have).
            session.run(
                "MATCH (p:Procedure) WHERE p.procedure_id IS NOT NULL "
                "SET p:AgentProcedure REMOVE p:Procedure"
            )
            session.run(
                "CREATE CONSTRAINT agent_procedure_id IF NOT EXISTS "
                "FOR (p:AgentProcedure) REQUIRE p.procedure_id IS UNIQUE"
            )

    def match_procedures(
        self,
        question: str,
        *,
        tenant_id: str = "default",
        query_type: str | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Lexical match against stored procedure names and intent keywords."""
        tokens = extract_tokens(question)
        expanded = expand_tokens(tokens)
        if not expanded:
            return []
        settings = get_settings()
        threshold = float(settings.get("procedural_match_threshold", 0.35))
        try:
            driver = self._connect()
            with driver.session(database=self._database) as session:
                rows = session.run(
                    """
                    MATCH (p:AgentProcedure)
                    WHERE p.tenant_id = $tenant_id OR p.tenant_id = 'global'
                    RETURN p.procedure_id AS procedure_id,
                           p.name AS name,
                           p.query_type AS query_type,
                           p.intent_keywords AS intent_keywords,
                           p.template_query AS template_query,
                           p.plan_steps_json AS plan_steps_json,
                           p.success_count AS success_count,
                           p.avg_confidence AS avg_confidence
                    ORDER BY p.success_count DESC, p.last_used_at DESC
                    LIMIT 100
                    """,
                    tenant_id=tenant_id,
                )
                candidates = list(rows)
        except Exception as exc:
            logger.warning("Procedure match failed: %s", exc)
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in candidates:
            if row.get("stale"):
                continue
            if query_type and row.get("query_type") and row.get("query_type") != query_type:
                continue
            keywords_raw = row.get("intent_keywords") or ""
            try:
                keywords = json.loads(keywords_raw) if keywords_raw.startswith("[") else []
            except json.JSONDecodeError:
                keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
            haystack = " ".join(
                [
                    str(row.get("name") or ""),
                    " ".join(keywords),
                    str(row.get("template_query") or "")[:500],
                ]
            ).lower()
            score = overlap_score(expanded, haystack)
            if score < threshold:
                continue
            item = dict(row)
            try:
                item["plan_steps"] = json.loads(item.pop("plan_steps_json") or "[]")
            except (json.JSONDecodeError, KeyError):
                item["plan_steps"] = []
            item["match_score"] = round(score, 4)
            scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for score, item in scored[:limit] if score >= threshold]

    def learn_from_turn(
        self,
        *,
        tenant_id: str,
        question: str,
        query_type: str,
        validated_query: str,
        plan: list[str] | None = None,
        turn_id: str = "",
        confidence: float = 0.0,
        concept_names: list[str] | None = None,
    ) -> str | None:
        """Create or reinforce a procedure from a successful turn."""
        settings = get_settings()
        if not settings.get("procedural_auto_learn", True):
            return None
        min_conf = float(settings.get("procedural_min_confidence", 0.7))
        if confidence < min_conf or not validated_query.strip():
            return None

        name = self._derive_name(question)
        keywords = tokens_for_learning(
            question,
            validated_query=validated_query,
            concept_names=concept_names,
        )
        procedure_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        try:
            driver = self._connect()
            with driver.session(database=self._database) as session:
                existing = session.run(
                    """
                    MATCH (p:AgentProcedure {tenant_id: $tenant_id, name: $name})
                    RETURN p.procedure_id AS procedure_id
                    LIMIT 1
                    """,
                    tenant_id=tenant_id,
                    name=name,
                ).single()
                if existing:
                    procedure_id = existing["procedure_id"]
                    session.run(
                        """
                        MATCH (p:AgentProcedure {procedure_id: $procedure_id})
                        SET p.success_count = coalesce(p.success_count, 0) + 1,
                            p.last_used_at = $now,
                            p.avg_confidence = (
                                coalesce(p.avg_confidence, 0) * coalesce(p.success_count, 0)
                                + $confidence
                            ) / (coalesce(p.success_count, 0) + 1),
                            p.template_query = $template_query
                        """,
                        procedure_id=procedure_id,
                        now=now,
                        confidence=confidence,
                        template_query=validated_query[:4000],
                    )
                else:
                    session.run(
                        """
                        CREATE (p:AgentProcedure {
                            procedure_id: $procedure_id,
                            tenant_id: $tenant_id,
                            name: $name,
                            query_type: $query_type,
                            intent_keywords: $intent_keywords,
                            template_query: $template_query,
                            plan_steps_json: $plan_steps_json,
                            success_count: 1,
                            avg_confidence: $confidence,
                            created_at: $now,
                            last_used_at: $now
                        })
                        """,
                        procedure_id=procedure_id,
                        tenant_id=tenant_id,
                        name=name,
                        query_type=query_type,
                        intent_keywords=json.dumps(keywords),
                        template_query=validated_query[:4000],
                        plan_steps_json=json.dumps(plan or []),
                        confidence=confidence,
                        now=now,
                    )
                if turn_id:
                    session.run(
                        """
                        MATCH (p:AgentProcedure {procedure_id: $procedure_id})
                        MATCH (t:AgentTurn {turn_id: $turn_id})
                        MERGE (p)-[:LEARNED_FROM]->(t)
                        """,
                        procedure_id=procedure_id,
                        turn_id=turn_id,
                    )
                for cname in (concept_names or [])[:10]:
                    session.run(
                        """
                        MATCH (p:AgentProcedure {procedure_id: $procedure_id})
                        OPTIONAL MATCH (c:OntologyConcept {name: $name})
                        FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
                            MERGE (p)-[:APPLIES_TO_CONCEPT]->(c)
                        )
                        """,
                        procedure_id=procedure_id,
                        name=cname,
                    )
        except Exception as exc:
            logger.warning("Procedure learn failed: %s", exc)
            return None
        return procedure_id

    @staticmethod
    def _derive_name(question: str) -> str:
        tokens = [t for t in _TOKEN.findall(question.lower()) if len(t) > 2][:6]
        return "_".join(tokens) or "generic_query"

    def record_usage(self, procedure_id: str) -> None:
        try:
            driver = self._connect()
            with driver.session(database=self._database) as session:
                session.run(
                    """
                    MATCH (p:AgentProcedure {procedure_id: $procedure_id})
                    SET p.last_used_at = $now,
                        p.success_count = coalesce(p.success_count, 0) + 1,
                        p.stale = false
                    """,
                    procedure_id=procedure_id,
                    now=datetime.now(timezone.utc).isoformat(),
                )
        except Exception as exc:
            logger.debug("Procedure usage record failed: %s", exc)

    def decay_unused(self, *, tenant_id: str = "default", stale_after_days: int = 30) -> int:
        """Mark procedures unused beyond stale_after_days as stale (not deleted)."""
        cutoff = datetime.now(timezone.utc).timestamp() - stale_after_days * 86400
        cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
        try:
            driver = self._connect()
            with driver.session(database=self._database) as session:
                result = session.run(
                    """
                    MATCH (p:AgentProcedure)
                    WHERE (p.tenant_id = $tenant_id OR p.tenant_id = 'global')
                      AND coalesce(p.stale, false) = false
                      AND coalesce(p.last_used_at, p.created_at, '') < $cutoff
                    SET p.stale = true,
                        p.stale_at = $now
                    RETURN count(p) AS decayed
                    """,
                    tenant_id=tenant_id,
                    cutoff=cutoff_iso,
                    now=datetime.now(timezone.utc).isoformat(),
                ).single()
                return int(result["decayed"]) if result else 0
        except Exception as exc:
            logger.warning("Procedure decay_unused failed: %s", exc)
            return 0


_procedural: ProceduralMemoryStore | None = None


def get_procedural_memory() -> ProceduralMemoryStore:
    global _procedural
    if _procedural is None:
        _procedural = ProceduralMemoryStore()
    return _procedural
