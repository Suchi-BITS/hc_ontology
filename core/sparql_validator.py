"""SPARQL post-generation / pre-execution validation."""

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

FORBIDDEN_SPARQL = {
    "INSERT",
    "DELETE",
    "DROP",
    "CLEAR",
    "LOAD",
    "CREATE",
    "MODIFY",
    "MOVE",
    "COPY",
    "ADD",
    "WITH",  # WITH DELETE / WITH INSERT update forms — block WITH alone is too broad
}

# WITH is common in SPARQL 1.1 SELECT; remove it from forbidden and use phrase checks
FORBIDDEN_SPARQL.discard("WITH")

FORBIDDEN_SPARQL_PHRASES = {
    "INSERT DATA",
    "DELETE DATA",
    "DELETE WHERE",
    "INSERT{",
    "DELETE{",
}


def parsed_query_problems(query: str) -> list[str]:
    """Problems found by walking the PARSED query: only a SELECT, no dataset clauses, no SERVICE.

    SERVICE would make the server send the query (and its bindings) to a URL chosen by the caller;
    FROM / FROM NAMED would make it fetch a document chosen by the caller. Neither is a read of our graph.
    """
    try:
        from rdflib.plugins.sparql.parser import parseQuery

        parsed = parseQuery(query)
    except Exception:
        return []  # not parseable: reported by the syntax stage
    body = parsed[1]
    problems: list[str] = []
    if getattr(body, "name", None) != "SelectQuery":
        problems.append(f"only SELECT queries are allowed (got {getattr(body, 'name', 'unknown')})")

    def walk(node):
        name = getattr(node, "name", None)
        if name == "ServiceGraphPattern":
            problems.append("SERVICE (federated queries) is not allowed")
        if name == "DatasetClause":
            problems.append("FROM / FROM NAMED dataset clauses are not allowed")
        children = []
        if hasattr(node, "values") and callable(node.values):
            children = list(node.values())
        elif isinstance(node, (list, tuple)):
            children = list(node)
        for child in children:
            if hasattr(child, "values") or isinstance(child, (list, tuple)):
                walk(child)

    walk(body)
    clauses = body.get("datasetClause") if hasattr(body, "get") else None
    if isinstance(clauses, list) and clauses:  # (CompValue.get returns the key itself when absent)
        problems.append("FROM / FROM NAMED dataset clauses are not allowed")
    return sorted(set(problems))


class SparqlQueryValidator(QueryValidator):
    def __init__(
        self,
        *,
        classes: Iterable[str] | None = None,
        object_properties: Iterable[str] | None = None,
        data_properties: Iterable[str] | None = None,
        default_limit: int = 200,
        timeout_seconds: float = 30.0,
        namespace: str = "http://example.org/healthcare-hospital.owl#",
    ):
        self.classes = {c for c in (classes or [])}
        self.object_properties = {p for p in (object_properties or [])}
        self.data_properties = {p for p in (data_properties or [])}
        self.known_terms = self.classes | self.object_properties | self.data_properties
        self.default_limit = default_limit
        self.timeout_seconds = timeout_seconds
        self.namespace = namespace

    def check_syntax(self, query: str) -> QueryValidationResult:
        upper = query.strip().upper()
        if not upper.startswith("PREFIX") and "SELECT" not in upper:
            return QueryValidationResult(
                valid=False,
                query=query,
                stage="syntax",
                error="SPARQL must be a PREFIX/SELECT query",
            )
        if "SELECT" not in upper:
            return QueryValidationResult(
                valid=False,
                query=query,
                stage="syntax",
                error="Only SELECT queries are allowed",
            )
        try:
            from rdflib.plugins.sparql import prepareQuery

            prepareQuery(query)
        except Exception as exc:
            return QueryValidationResult(
                valid=False,
                query=query,
                stage="syntax",
                error=f"SPARQL parse error: {exc}",
            )
        return QueryValidationResult(valid=True, query=query)

    def check_safety(self, query: str) -> QueryValidationResult:
        hits = find_forbidden_keywords(query, FORBIDDEN_SPARQL)
        cleaned = re.sub(r"\s+", " ", query.upper())
        for phrase in FORBIDDEN_SPARQL_PHRASES:
            if phrase in cleaned.replace(" ", "") or phrase in cleaned:
                # normalize phrase check
                compact = cleaned.replace(" ", "")
                if phrase.replace(" ", "") in compact:
                    hits.append(phrase)
        # Deduplicate
        hits = sorted(set(hits))
        if hits:
            return QueryValidationResult(
                valid=False,
                query=query,
                stage="safety",
                error=f"Forbidden SPARQL write/update keywords: {', '.join(hits)}",
                details={"forbidden": hits},
            )
        # Structural check on the PARSED query (not on its text): a query that does not parse is left
        # to the syntax stage; one that parses must be a plain SELECT over the local graph.
        problems = parsed_query_problems(query)
        if problems:
            return QueryValidationResult(
                valid=False,
                query=query,
                stage="safety",
                error=f"SPARQL query refused: {'; '.join(problems)}",
                details={"forbidden": [], "policy_violations": problems},
            )
        return QueryValidationResult(valid=True, query=query)

    def check_schema(self, query: str) -> QueryValidationResult:
        if not self.known_terms:
            return QueryValidationResult(valid=True, query=query)

        # Terms after hc: or bare :LocalName in typical course queries
        # Only the ontology's own prefix (hc:Name) or the empty prefix (:Name). A term such as
        # rdfs:subClassOf has a different prefix and is not an ontology term.
        refs = set(re.findall(r"(?<![A-Za-z0-9_])(?:hc)?:([A-Za-z_][A-Za-z0-9_]*)", query))
        # Filter RDF/OWL builtins and variables already excluded by pattern
        builtins = {
            "type",
            "Property",
            "Class",
            "Ontology",
            "label",
            "comment",
        }
        unknown = sorted(
            t for t in refs if t not in self.known_terms and t not in builtins
        )
        if unknown:
            return QueryValidationResult(
                valid=False,
                query=query,
                stage="schema",
                error=f"Unknown ontology terms in SPARQL: {', '.join(unknown)}",
                details={"unknown_terms": unknown},
            )
        return QueryValidationResult(valid=True, query=query)

    def check_limits(self, query: str) -> QueryValidationResult:
        if re.search(r"\bLIMIT\b", query, flags=re.IGNORECASE):
            return QueryValidationResult(valid=True, query=query)
        rewritten = query.rstrip().rstrip(";") + f"\nLIMIT {self.default_limit}"
        logger.info("Injected LIMIT %s into SPARQL query", self.default_limit)
        return QueryValidationResult(
            valid=True,
            query=rewritten,
            details={"limit_injected": self.default_limit},
        )

    # There is deliberately no execute_with_timeout here. The version that used to live in this class ran
    # the query on a thread inside `with ThreadPoolExecutor(...)`: on timeout the `with` block still waited
    # for the thread to finish, so the "timeout" never bounded anything. Bounded execution is
    # core/sparql_exec.py (a killable worker process); see docs/security-architecture.md.
