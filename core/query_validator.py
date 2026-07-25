"""Shared query validation types and keyword tokenization helpers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class QueryValidationResult:
    valid: bool
    query: str = ""
    stage: str | None = None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QueryValidationError(Exception):
    """Raised when a query fails a validation stage."""

    def __init__(self, result: QueryValidationResult):
        self.result = result
        super().__init__(result.error or "Query validation failed")


# Tokenize on word boundaries; ignore content inside string literals (rough).
_STRING_LIT = re.compile(
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`'
)
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def strip_string_literals(text: str) -> str:
    return _STRING_LIT.sub(" ", text)


def tokenize_keywords(text: str) -> set[str]:
    """Uppercase identifier tokens outside string literals."""
    cleaned = strip_string_literals(text)
    return {m.group(0).upper() for m in _WORD.finditer(cleaned)}


def find_forbidden_keywords(text: str, forbidden: set[str]) -> list[str]:
    tokens = tokenize_keywords(text)
    # Also catch multi-word phrases like CALL DBMS after stripping strings
    cleaned_upper = strip_string_literals(text).upper()
    hits: list[str] = []
    for item in sorted(forbidden):
        if " " in item:
            if item in cleaned_upper:
                hits.append(item)
        elif item in tokens:
            hits.append(item)
    return hits


class QueryValidator(ABC):
    """Strategy interface: run ordered validation stages."""

    @abstractmethod
    def check_syntax(self, query: str) -> QueryValidationResult:
        ...

    @abstractmethod
    def check_safety(self, query: str) -> QueryValidationResult:
        ...

    @abstractmethod
    def check_schema(self, query: str) -> QueryValidationResult:
        ...

    @abstractmethod
    def check_limits(self, query: str) -> QueryValidationResult:
        """May rewrite query (e.g. inject LIMIT)."""

    def run_all_checks(self, query: str) -> QueryValidationResult:
        current = query.strip()
        if not current:
            return QueryValidationResult(
                valid=False,
                query=current,
                stage="syntax",
                error="Empty query",
            )

        # Safety first so write/injection attempts get a clear stage label
        # even when the payload is also syntactically invalid.
        for stage_name, fn in (
            ("safety", self.check_safety),
            ("syntax", self.check_syntax),
            ("schema", self.check_schema),
            ("limits", self.check_limits),
        ):
            result = fn(current)
            if not result.valid:
                result.stage = result.stage or stage_name
                result.query = result.query or current
                return result
            if result.query:
                current = result.query

        return QueryValidationResult(valid=True, query=current, stage=None)
