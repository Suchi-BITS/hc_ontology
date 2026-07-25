"""SHACL validation API routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse

from core.auth import verify_api_key
from core.dependencies import get_shacl_validator
from core.schemas import ValidateOntologyRequest, ValidateRdfRequest
from core.shacl_exceptions import (
    ShaclDataLoadError,
    ShaclShapeLoadError,
    ShaclValidationError,
)
from core.shacl_validator import ShaclValidator

router = APIRouter(tags=["SHACL"], dependencies=[Depends(verify_api_key)])

# In-memory last report for GET /validation/report
_last_report: dict | None = None


def _store_and_return(result) -> dict:
    global _last_report
    payload = result.to_dict()
    if result.report_graph_turtle:
        payload["report_turtle"] = result.report_graph_turtle
    _last_report = payload
    return payload


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ShaclShapeLoadError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, ShaclDataLoadError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, ShaclValidationError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.get("/validation/health")
def validation_health(validator: ShaclValidator = Depends(get_shacl_validator)):
    return validator.health()


@router.get("/validation/report")
def last_validation_report(
    format: str = Query(default="json", pattern="^(json|html)$"),
):
    """Return the most recent validation result from this process."""
    if _last_report is None:
        raise HTTPException(
            status_code=404,
            detail="No validation report yet. Call POST /validate or /validate/ontology first.",
        )
    if format == "html":
        from core.shacl_report import (
            ShaclReportFormatter,
            ValidationResult,
            ValidationSummary,
            ValidationViolation,
        )

        summary = ValidationSummary(**_last_report["summary"])
        violations = [ValidationViolation(**v) for v in _last_report["violations"]]
        result = ValidationResult(summary=summary, violations=violations)
        return HTMLResponse(ShaclReportFormatter().to_html(result))
    return _last_report


@router.post("/validate")
def validate_rdf(
    request: ValidateRdfRequest,
    validator: ShaclValidator = Depends(get_shacl_validator),
):
    """Validate an inline RDF document against SHACL shapes."""
    try:
        result = validator.validate_rdf_text(
            request.data,
            rdf_format=request.format,
            shape_files=request.shape_files,
            include_turtle=request.include_turtle,
        )
        return _store_and_return(result)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/validate/ontology")
def validate_ontology(
    request: ValidateOntologyRequest = Body(default_factory=ValidateOntologyRequest),
    validator: ShaclValidator = Depends(get_shacl_validator),
):
    """Validate the project healthcare OWL ontology against SHACL shapes."""
    try:
        result = validator.validate_ontology(
            owl_path=request.owl_path,
            shape_files=request.shape_files,
            include_turtle=request.include_turtle,
        )
        return _store_and_return(result)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/validate/file")
async def validate_file(
    file: UploadFile = File(...),
    shape_files: str | None = Form(
        default=None,
        description="Comma-separated shape filenames, or omit for all",
    ),
    include_turtle: bool = Form(default=False),
    validator: ShaclValidator = Depends(get_shacl_validator),
):
    """Validate an uploaded RDF/OWL file against SHACL shapes."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    names = None
    if shape_files:
        names = [s.strip() for s in shape_files.split(",") if s.strip()]

    filename = file.filename or "upload.rdf"
    try:
        result = validator.validate_file(
            content,
            filename,
            shape_files=names,
            include_turtle=include_turtle,
        )
        return _store_and_return(result)
    except Exception as exc:
        raise _map_error(exc) from exc
