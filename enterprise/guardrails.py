"""Guardrails — input/output safety checks before agent execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


FORBIDDEN_PATTERNS = [
    re.compile(r"\b(ignore|bypass)\s+(previous|all)\s+instructions\b", re.I),
    re.compile(r"\b(system\s*prompt|jailbreak)\b", re.I),
    re.compile(r"\b(drop\s+database|truncate\s+table)\b", re.I),
    re.compile(r"\bDETACH\s+DELETE\b", re.I),
    re.compile(r"\bCREATE\s+CONSTRAINT\b", re.I),
]

PII_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN-like
    re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
]

PHI_HINTS = re.compile(
    r"\b(ssn|social security|medical record number|mrn)\b",
    re.I,
)


@dataclass
class GuardrailResult:
    allowed: bool
    reason: Optional[str] = None
    redacted_text: Optional[str] = None
    flags: list[str] | None = None


def check_input(text: str) -> GuardrailResult:
    flags: list[str] = []
    if not text or not text.strip():
        return GuardrailResult(allowed=False, reason="Empty input", flags=["empty"])

    for pat in FORBIDDEN_PATTERNS:
        if pat.search(text):
            flags.append("forbidden_pattern")
            return GuardrailResult(
                allowed=False,
                reason=f"Blocked by guardrail pattern: {pat.pattern}",
                flags=flags,
            )

    if PHI_HINTS.search(text):
        flags.append("phi_hint")

    redacted = text
    for pat in PII_PATTERNS:
        if pat.search(redacted):
            flags.append("pii")
            redacted = pat.sub("[REDACTED]", redacted)

    return GuardrailResult(allowed=True, redacted_text=redacted, flags=flags or None)


def check_output(text: str) -> GuardrailResult:
    flags: list[str] = []
    redacted = text or ""
    for pat in PII_PATTERNS:
        if pat.search(redacted):
            flags.append("pii_output")
            redacted = pat.sub("[REDACTED]", redacted)
    # Block accidental write/delete instructions in answers
    if re.search(r"\b(DETACH\s+DELETE|DROP\s+CONSTRAINT)\b", redacted, re.I):
        flags.append("dangerous_output")
        return GuardrailResult(
            allowed=False,
            reason="Output contains dangerous graph mutation language",
            flags=flags,
        )
    return GuardrailResult(allowed=True, redacted_text=redacted, flags=flags or None)
