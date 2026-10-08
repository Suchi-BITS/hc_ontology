"""HTTP error helpers — consistent status semantics."""

from __future__ import annotations

import re

from fastapi import HTTPException

from core.query_validator import QueryValidationError, QueryValidationResult


def client_error(detail: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail)


def service_unavailable(detail: str) -> HTTPException:
    return HTTPException(status_code=503, detail=detail)


def from_validation_result(result: QueryValidationResult) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "message": result.error or "Query validation failed",
            "stage": result.stage,
            "details": result.details,
        },
    )


_SECRET_SHAPES = re.compile(r"(?<![A-Za-z0-9])(sk|lsv2|hck)[-_][A-Za-z0-9_*.\-]{4,}")


def scrub_secrets(text: str) -> str:
    """Remove anything key-shaped from an error before it reaches a client. Found by the live AI verification:
    OpenAI's own message for a bad key echoes a masked copy of it ('Incorrect API key provided: sk-abc****...1234')."""
    return _SECRET_SHAPES.sub("[redacted-key]", text)


def map_query_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, QueryValidationError):
        return from_validation_result(exc.result)
    if isinstance(exc, ImportError):
        return service_unavailable(
            "This endpoint belongs to the optional AI layer (openai / langchain / langgraph), which is not installed. "
            "The core API (SPARQL, SHACL, ontology, projection) does not need it: pip install -r requirements.txt. "
            f"Detail: {exc}"
        )
    if isinstance(exc, TimeoutError):
        return HTTPException(status_code=504, detail=str(exc))
    if isinstance(exc, ValueError):
        return client_error(str(exc))
    msg = scrub_secrets(str(exc) or exc.__class__.__name__)
    if msg == "Connection error." or "Connection error" in msg:
        return service_unavailable(
            "LLM connection failed (HTTPS). Install truststore: "
            "`python -m pip install truststore certifi`, restart the API, "
            "or check OPENAI_API_KEY and network/proxy settings."
        )
    return service_unavailable(msg)
