"""Read-only Cypher policy: a structural ALLOWLIST, not a blocklist.

This is the second line of defense. The first is that queries from users and from the LLM are executed
in a read-only transaction (`execute_read` with READ access mode, see services/sparql_to_cypher.py):
the database itself refuses to write, whatever the text says. This module exists so that bad queries
are refused early, with a reason, and so that nothing exotic (procedures, subqueries that call out,
admin commands, unbounded traversals) is ever sent to the database at all.

How it works. The query is first checked for anything this tokenizer might read differently from the
database's lexer: comments, non-ASCII outside string literals, control characters, multiple statements,
unterminated strings. Those are refused outright (a disagreement between a checker and the real lexer is
the classic way past a filter). Then the query is tokenized and:

  * every Cypher RESERVED WORD must be on the allowed list (read-only clause words and operators);
    CREATE, MERGE, SET, DELETE, REMOVE, CALL, LOAD, FOREACH, USE, SHOW, ... are not on it;
  * every FUNCTION CALL must be on the function allowlist (so no `apoc.*`, no `db.*`, no `dbms.*`);
  * relationship traversals must have a bounded length;
  * parameters (`$x`) are refused because we send none.

Anything not recognised as allowed is refused: unknown words fail closed only if they are reserved
words; ordinary names (labels, variables, properties) are free, as they cannot execute anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_QUERY_LENGTH = 5000
MAX_PATH_LENGTH = 6

ALLOWED_KEYWORDS = frozenset(
    {
        "MATCH", "OPTIONAL", "WHERE", "RETURN", "WITH", "ORDER", "BY", "SKIP", "LIMIT", "UNWIND", "UNION",
        "ALL", "AS", "DISTINCT", "AND", "OR", "NOT", "XOR", "IN", "IS", "NULL", "TRUE", "FALSE", "CONTAINS",
        "STARTS", "ENDS", "CASE", "WHEN", "THEN", "ELSE", "END", "ASC", "ASCENDING", "DESC", "DESCENDING",
        "EXISTS", "EXPLAIN",
    }
)

# The openCypher / Neo4j reserved and administrative words. A bare word from this set that is not in
# ALLOWED_KEYWORDS is refused. (Names such as Patient or p are not in it and are always fine.)
RESERVED_KEYWORDS = ALLOWED_KEYWORDS | frozenset(
    {
        "CALL", "YIELD", "CREATE", "MERGE", "DELETE", "DETACH", "SET", "REMOVE", "DROP", "LOAD", "CSV",
        "FOREACH", "USE", "SHOW", "TERMINATE", "START", "GRANT", "REVOKE", "DENY", "PROFILE", "USING",
        "PERIODIC", "COMMIT", "CONSTRAINT", "INDEX", "INDEXES", "CONSTRAINTS", "ASSERT", "REQUIRE",
        "UNIQUE", "FOR", "ON", "OF", "FROM", "HEADERS", "FIELDTERMINATOR", "NODE", "RELATIONSHIP",
        "DATABASE", "DATABASES", "USER", "USERS", "ROLE", "ROLES", "PRIVILEGE", "PRIVILEGES",
        "TRANSACTION", "TRANSACTIONS", "ALTER", "RENAME", "STOP", "WAIT", "NOWAIT", "IF", "SCALAR",
        "SHORTESTPATH", "ALLSHORTESTPATHS", "REDUCE", "ADD", "SERVER", "COMPOSITE", "ALIAS", "ALIASES",
        "TEXT", "RANGE", "POINT", "VECTOR", "LOOKUP", "FULLTEXT", "EACH", "TO", "WITHOUT", "REPLACE",
    }
)

ALLOWED_FUNCTIONS = frozenset(
    {
        "count", "collect", "sum", "avg", "min", "max", "size", "tolower", "toupper", "tostring", "tointeger",
        "tofloat", "toboolean", "coalesce", "keys", "labels", "type", "id", "elementid", "head", "last", "tail",
        "range", "abs", "ceil", "floor", "round", "sqrt", "date", "datetime", "localdatetime", "duration",
        "substring", "trim", "ltrim", "rtrim", "split", "left", "right", "reverse", "length", "nodes",
        "relationships", "exists", "isempty", "any", "all", "none", "single", "properties", "startnode",
        "endnode", "toupper", "tolower", "stdev", "percentilecont", "percentiledisc",
    }
)

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class PolicyResult:
    allowed: bool
    violations: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        return "; ".join(self.violations)


def _scan(query: str) -> tuple[str, list[str]]:
    """Return the query with string literals and backtick-quoted names blanked, plus any lexical problems."""
    problems: list[str] = []
    out: list[str] = []
    i, n = 0, len(query)
    while i < n:
        ch = query[i]
        if ch in "'\"":
            quote, j = ch, i + 1
            while j < n:
                if query[j] == "\\":
                    j += 2
                    continue
                if query[j] == quote:
                    if j + 1 < n and query[j + 1] == quote:  # doubled quote escapes itself
                        j += 2
                        continue
                    break
                j += 1
            else:
                problems.append("unterminated string literal")
                return "".join(out), problems
            out.append(" ")
            i = j + 1
            continue
        if ch == "`":
            j = i + 1
            while j < n:
                if query[j] == "`":
                    if j + 1 < n and query[j + 1] == "`":
                        j += 2
                        continue
                    break
                j += 1
            else:
                problems.append("unterminated quoted name")
                return "".join(out), problems
            out.append(" quotedname ")
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), problems


def check_read_only(query: str) -> PolicyResult:
    """Decide whether a Cypher query is within the read-only policy."""
    violations: list[str] = []
    text = query or ""
    if not text.strip():
        return PolicyResult(False, ["empty query"])
    if len(text) > MAX_QUERY_LENGTH:
        violations.append(f"query is longer than {MAX_QUERY_LENGTH} characters")
    if "//" in text or "/*" in text or "*/" in text:
        violations.append("comments are not allowed")
    if ";" in text:
        violations.append("only a single statement is allowed")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
        violations.append("control characters are not allowed")

    blanked, problems = _scan(text)
    violations.extend(problems)
    if any(ord(c) > 126 for c in blanked):
        violations.append("non-ASCII characters are only allowed inside string literals")
    if violations:
        return PolicyResult(False, sorted(set(violations)))

    if "$" in blanked:
        violations.append("query parameters are not allowed")

    # every word, with what precedes and follows it
    for match in _WORD.finditer(blanked):
        word = match.group(0)
        before = blanked[: match.start()].rstrip()
        after = blanked[match.end():].lstrip()
        if before.endswith(".") or before.endswith(":"):  # property name or label/relationship type
            continue
        upper = word.upper()
        if after.startswith("("):
            if upper in ALLOWED_KEYWORDS and upper not in ("EXISTS", "ALL"):
                continue  # MATCH (n), WHERE (a OR b), IN (...)
            if word.lower() in ALLOWED_FUNCTIONS:
                continue
            if upper in RESERVED_KEYWORDS:
                violations.append(f"keyword {upper} is not allowed in read-only queries")
            else:
                violations.append(f"function {word}() is not on the allowlist")
        elif upper in RESERVED_KEYWORDS and upper not in ALLOWED_KEYWORDS:
            violations.append(f"keyword {upper} is not allowed in read-only queries")

    # namespaced calls such as apoc.cypher.doIt(...) or db.labels(...)
    for match in re.finditer(r"[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)+\s*\(", blanked):
        violations.append(f"namespaced call {re.sub(chr(92) + 's+', '', match.group(0))[:-1]}() is not allowed")

    # traversals must be bounded
    for rel in re.finditer(r"\[([^\]]*)\]", blanked):
        body = rel.group(1)
        star = body.find("*")
        if star == -1:
            continue
        head = body[:star]
        if re.fullmatch(r"\s*[A-Za-z_0-9]*\s*(:\s*[A-Za-z_0-9|\s:]+)?\s*", head) is None:
            continue  # arithmetic inside a list, not a relationship pattern
        spec = body[star + 1:].strip()
        bounded = re.fullmatch(r"(\d+)?\s*(\.\.\s*(\d+))?", spec)
        upper_bound = None
        if bounded:
            if bounded.group(3):
                upper_bound = int(bounded.group(3))
            elif bounded.group(1) and not bounded.group(2):
                upper_bound = int(bounded.group(1))
        if upper_bound is None or upper_bound > MAX_PATH_LENGTH:
            violations.append(f"variable-length traversals must have an upper bound of at most {MAX_PATH_LENGTH}")

    return PolicyResult(not violations, sorted(set(violations)))


class CypherPolicyViolation(ValueError):
    def __init__(self, result: PolicyResult):
        self.result = result
        super().__init__(f"Cypher query refused by the read-only policy: {result.reason}")


def require_read_only(query: str) -> None:
    result = check_read_only(query)
    if not result.allowed:
        raise CypherPolicyViolation(result)
