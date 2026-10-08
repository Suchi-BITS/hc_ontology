"""Shared lexical helpers for memory retrieval and matching."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable

_TOKEN = re.compile(r"[a-z0-9]+", re.I)
_CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ALIASES_PATH = _PROJECT_ROOT / "data" / "healthcare_term_aliases.json"


@lru_cache
def load_term_aliases() -> dict[str, list[str]]:
    """Load healthcare term synonyms from data file."""
    if not _ALIASES_PATH.is_file():
        return {}
    try:
        raw = json.loads(_ALIASES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, list[str]] = {}
    for key, values in raw.items():
        if not isinstance(values, list):
            continue
        out[str(key).lower()] = [str(v).lower() for v in values if v]
    return out


def split_name_tokens(name: str) -> set[str]:
    """Tokenize ontology entity names including CamelCase splits."""
    tokens = {t.lower() for t in _TOKEN.findall(name or "") if len(t) > 1}
    for part in _CAMEL.findall(name or ""):
        if len(part) > 1:
            tokens.add(part.lower())
    return tokens


def extract_tokens(text: str, *, min_len: int = 3) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text or "") if len(t) >= min_len]


def expand_tokens(tokens: Iterable[str]) -> set[str]:
    """Expand tokens with configured healthcare aliases (bidirectional)."""
    aliases = load_term_aliases()
    expanded: set[str] = set()
    for token in tokens:
        t = token.lower()
        if not t:
            continue
        expanded.add(t)
        for alias in aliases.get(t, []):
            expanded.add(alias.lower())
        for canonical, group in aliases.items():
            if t in group:
                expanded.add(canonical)
                expanded.update(group)
    return expanded


def overlap_score(question_tokens: Iterable[str], haystack: str) -> float:
    """Fraction of question tokens matched in haystack (with alias + name token expansion)."""
    q = expand_tokens(question_tokens)
    if not q:
        return 0.0
    target = expand_tokens(extract_tokens(haystack))
    target |= split_name_tokens(haystack)
    hay_lower = (haystack or "").lower()
    hits = sum(1 for t in q if t in target or t in hay_lower)
    return min(1.0, hits / max(len(q), 1))


def tokens_for_learning(
    question: str,
    *,
    validated_query: str = "",
    concept_names: Iterable[str] | None = None,
    limit: int = 30,
) -> list[str]:
    """Rich keyword set when learning procedures or indexing turns."""
    bag: set[str] = set(expand_tokens(extract_tokens(question)))
    bag |= set(expand_tokens(extract_tokens(validated_query)))
    for name in concept_names or []:
        bag |= split_name_tokens(str(name))
        bag |= set(expand_tokens(extract_tokens(str(name))))
    return sorted(bag)[:limit]
