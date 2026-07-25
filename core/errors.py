"""HTTP error helpers — consistent status semantics."""

from __future__ import annotations

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


def map_query_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, QueryValidationError):
        return from_validation_result(exc.result)
    if isinstance(exc, TimeoutError):
        return HTTPException(status_code=504, detail=str(exc))
    if isinstance(exc, ValueError):
        return client_error(str(exc))
    return service_unavailable(str(exc))
