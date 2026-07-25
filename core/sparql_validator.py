"""SPARQL post-generation / pre-execution validation."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
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
        return QueryValidationResult(valid=True, query=query)

    def check_schema(self, query: str) -> QueryValidationResult:
        if not self.known_terms:
            return QueryValidationResult(valid=True, query=query)

        # Terms after hc: or bare :LocalName in typical course queries
        refs = set(re.findall(r"(?:hc:|:)([A-Za-z_][A-Za-z0-9_]*)", query))
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

    def execute_with_timeout(
        self,
        execute_fn: Callable[[str], list],
        query: str,
    ) -> list:
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(execute_fn, query)
            try:
                return fut.result(timeout=self.timeout_seconds)
            except FuturesTimeout as exc:
                raise TimeoutError(
                    f"SPARQL execution exceeded {self.timeout_seconds}s"
                ) from exc
