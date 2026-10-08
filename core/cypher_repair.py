"""Shared Cypher syntax repairs for LLM-generated queries."""

from __future__ import annotations

import re


def repair_cypher(query: str) -> str:
    """Fix common LLM mistakes without changing valid queries."""
    cypher = (query or "").strip()
    if not cypher:
        return cypher

    # Graph export uses patient -> diagnosis via HASDIAGNOSIS.
    cypher = re.sub(
        r"\(\s*p\s*:\s*Patient\s*\)\s*<-\s*\[\s*:\s*DIAGNOSISFORPATIENT\s*\]\s*-\s*\(\s*d\s*:\s*Diagnosis\s*\)",
        "(p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis)",
        cypher,
        flags=re.IGNORECASE,
    )
    cypher = re.sub(
        r"\(\s*d\s*:\s*Diagnosis\s*\)\s*-\s*\[\s*:\s*DIAGNOSISFORPATIENT\s*\]\s*->\s*\(\s*p\s*:\s*Patient\s*\)",
        "(p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis)",
        cypher,
        flags=re.IGNORECASE,
    )

    if re.search(r"\bRETURN\s*(?:\n\s*LIMIT\b|\s+LIMIT\b|\s*;?\s*$)", cypher, re.I):
        aliases = re.findall(r"\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", cypher)
        if not aliases:
            aliases = ["n"]
        items: list[str] = []
        for alias in aliases[:6]:
            low = alias.lower()
            if low.startswith("d") and "diagnosisname" in cypher.lower():
                items.append(f"{alias}.diagnosisName")
            else:
                items.append(f"{alias}.name")
        return_expr = ", ".join(dict.fromkeys(items))
        cypher = re.sub(
            r"\bRETURN\s*(?=\n\s*LIMIT\b|\s+LIMIT\b|\s*;?\s*$)",
            f"RETURN {return_expr} ",
            cypher,
            count=1,
            flags=re.IGNORECASE | re.MULTILINE,
        )

    return cypher.strip()
