"""Cypher post-generation / pre-execution validation."""

from __future__ import annotations

import logging
import re
from typing import Callable, Iterable

from core.query_validator import (
    QueryValidationResult,
    QueryValidator,
    find_forbidden_keywords,
)

logger = logging.getLogger("healthcare_ontology.query")

FORBIDDEN_CYPHER = {
    "CREATE",
    "MERGE",
    "DELETE",
    "DETACH",
    "SET",
    "REMOVE",
    "DROP",
    "LOAD",
    "FOREACH",
}

FORBIDDEN_CYPHER_PHRASES = {
    "CALL DBMS",
    "CALL DB.",
    "DETACH DELETE",
}


class CypherQueryValidator(QueryValidator):
    def __init__(
        self,
        *,
        classes: Iterable[str] | None = None,
        object_properties: Iterable[str] | None = None,
        data_properties: Iterable[str] | None = None,
        default_limit: int = 200,
        timeout_seconds: float = 30.0,
        explain_fn: Callable[[str], None] | None = None,
    ):
        # Labels as used in graph (class names); relationships UPPERCASE
        self.classes = {c for c in (classes or [])}
        self.relationship_types = {
            (p.upper() if not p.isupper() else p) for p in (object_properties or [])
        }
        # Also accept original casing for properties list that may already be upper
        self.relationship_types |= {p for p in (object_properties or [])}
        self.data_properties = {p for p in (data_properties or [])}
        self.default_limit = default_limit
        self.timeout_seconds = timeout_seconds
        self.explain_fn = explain_fn

    def check_syntax(self, query: str) -> QueryValidationResult:
        upper = query.upper()
        if "MATCH" not in upper or "RETURN" not in upper:
            return QueryValidationResult(
                valid=False,
                query=query,
                stage="syntax",
                error="Cypher read queries must include MATCH and RETURN",
            )
        return_body = re.split(r"\bRETURN\b", query, maxsplit=1, flags=re.IGNORECASE)
        if len(return_body) > 1:
            tail = re.split(r"\bLIMIT\b", return_body[1], maxsplit=1, flags=re.IGNORECASE)[0]
            if not tail.strip() or not re.search(r"[A-Za-z_]", tail):
                return QueryValidationResult(
                    valid=False,
                    query=query,
                    stage="syntax",
                    error="RETURN clause must include at least one expression",
                )
        if self.explain_fn is not None:
            try:
                self.explain_fn(f"EXPLAIN {query}")
            except Exception as exc:
                msg = str(exc).lower()
                # If Neo4j is unreachable, still allow structural stages to run;
                # genuine parse errors from Neo4j usually mention SyntaxError.
                if "syntax" in msg or "invalid" in msg:
                    return QueryValidationResult(
                        valid=False,
                        query=query,
                        stage="syntax",
                        error=f"Cypher EXPLAIN/parse failed: {exc}",
                    )
                logger.warning(
                    "Skipping Cypher EXPLAIN (Neo4j unavailable): %s", exc
                )
        return QueryValidationResult(valid=True, query=query)

    def check_safety(self, query: str) -> QueryValidationResult:
        hits = find_forbidden_keywords(query, FORBIDDEN_CYPHER)
        cleaned = re.sub(r"\s+", " ", query.upper())
        for phrase in FORBIDDEN_CYPHER_PHRASES:
            if phrase in cleaned:
                hits.append(phrase)
        hits = sorted(set(hits))
        if hits:
            return QueryValidationResult(
                valid=False,
                query=query,
                stage="safety",
                error=f"Forbidden Cypher write/admin keywords: {', '.join(hits)}",
                details={"forbidden": hits},
            )
        # The allowlist policy is the structural check (procedures, subqueries that call out, comments,
        # unbounded traversals ...). The keyword list above only gives a friendlier message for the
        # common cases; the real write barrier is the read-only transaction at execution time.
        from core.cypher_policy import check_read_only

        policy = check_read_only(query)
        if not policy.allowed:
            return QueryValidationResult(
                valid=False,
                query=query,
                stage="safety",
                error=f"Query refused by the read-only policy: {policy.reason}",
                details={"policy_violations": policy.violations, "forbidden": []},
            )
        return QueryValidationResult(valid=True, query=query)

    def check_schema(self, query: str) -> QueryValidationResult:
        if not self.classes and not self.relationship_types:
            return QueryValidationResult(valid=True, query=query)

        labels = set(
            re.findall(r"\([^\[\]]*?:\s*`?([A-Za-z_][A-Za-z0-9_]*)`?", query)
        )
        rels = set(
            re.findall(
                r"\[\s*(?:[A-Za-z_][A-Za-z0-9_]*)?\s*:\s*`?([A-Za-z_][A-Za-z0-9_]*)`?",
                query,
            )
        )

        unknown_labels = sorted(
            t for t in labels if self.classes and t not in self.classes
        )
        # Rel types compared case-insensitively to UPPER map
        known_rels_upper = {r.upper() for r in self.relationship_types}
        unknown_rels = sorted(
            t
            for t in rels
            if known_rels_upper and t.upper() not in known_rels_upper
        )

        # Property keys after `.` — only flag if clearly not `name` and not in schema
        props = set(re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)", query))
        allow_props = self.data_properties | {"name", "iri", "id", "elementId", "rdfTypes"}
        unknown_props = sorted(
            p
            for p in props
            if self.data_properties and p not in allow_props
        )

        problems = []
        if unknown_labels:
            problems.append(f"unknown labels: {', '.join(unknown_labels)}")
        if unknown_rels:
            problems.append(f"unknown relationships: {', '.join(unknown_rels)}")
        if unknown_props:
            problems.append(f"unknown properties: {', '.join(unknown_props)}")

        if problems:
            return QueryValidationResult(
                valid=False,
                query=query,
                stage="schema",
                error="Schema whitelist failed — " + "; ".join(problems),
                details={
                    "unknown_labels": unknown_labels,
                    "unknown_relationships": unknown_rels,
                    "unknown_properties": unknown_props,
                },
            )
        return QueryValidationResult(valid=True, query=query)

    def check_limits(self, query: str) -> QueryValidationResult:
        if re.search(r"\bLIMIT\b", query, flags=re.IGNORECASE):
            return QueryValidationResult(valid=True, query=query)
        rewritten = query.rstrip().rstrip(";") + f"\nLIMIT {self.default_limit}"
        logger.info("Injected LIMIT %s into Cypher query", self.default_limit)
        return QueryValidationResult(
            valid=True,
            query=rewritten,
            details={"limit_injected": self.default_limit},
        )

    def run_all_checks(self, query: str) -> QueryValidationResult:
        from core.cypher_repair import repair_cypher

        return super().run_all_checks(repair_cypher(query))
