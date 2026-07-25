from typing import Any, Literal

from pydantic import BaseModel, Field


class SparqlRequest(BaseModel):
    query: str


class NLQueryRequest(BaseModel):
    question: str = Field(..., min_length=1)


class LLMQueryRequest(BaseModel):
    question: str = Field(..., min_length=1)


class SparqlCypherRequest(BaseModel):
    query: str


class ExecuteCypherRequest(BaseModel):
    cypher: str


# ---------------------------------------------------------------------------
# SHACL request / response schemas (kept with other API models in core/)
# ---------------------------------------------------------------------------


_VALID_PATIENT_TURTLE = """\
@prefix hc: <http://example.org/healthcare-hospital.owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

hc:PatientAlice a hc:Patient ;
    hc:firstName "Alice"^^xsd:string ;
    hc:lastName "Nguyen"^^xsd:string ;
    hc:gender "female"^^xsd:string ;
    hc:dateOfBirth "1990-04-12"^^xsd:string ;
    hc:bloodGroup "O+"^^xsd:string ;
    hc:hasDiagnosis hc:DxAlice ;
    hc:hasMedicalRecord hc:MRAlice .

hc:DxAlice a hc:Diagnosis .
hc:MRAlice a hc:MedicalRecord .
"""


class ValidateRdfRequest(BaseModel):
    """Inline RDF payload for POST /validate."""

    data: str = Field(
        ...,
        min_length=1,
        description="RDF document as text (must be valid for the chosen format)",
        examples=[_VALID_PATIENT_TURTLE],
    )
    format: Literal["turtle", "xml", "nt", "n3", "json-ld"] = Field(
        default="turtle",
        description="RDF serialization format of `data`",
    )
    shape_files: list[str] | None = Field(
        default=None,
        description="Optional subset of shape paths (e.g. patient_shapes.ttl)",
        examples=[["patient_shapes.ttl"]],
    )
    include_turtle: bool = Field(
        default=False,
        description="Include raw SHACL report graph as Turtle",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "data": _VALID_PATIENT_TURTLE,
                    "format": "turtle",
                    "shape_files": ["patient_shapes.ttl"],
                    "include_turtle": False,
                },
                {
                    "data": (
                        "@prefix hc: <http://example.org/healthcare-hospital.owl#> .\n"
                        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n\n"
                        "hc:PatientNoDob a hc:Patient ;\n"
                        '    hc:firstName "Bob"^^xsd:string ;\n'
                        '    hc:bloodGroup "A+"^^xsd:string .\n'
                    ),
                    "format": "turtle",
                    "shape_files": ["patient_shapes.ttl"],
                    "include_turtle": False,
                },
            ]
        }
    }


class ValidateOntologyRequest(BaseModel):
    shape_files: list[str] | None = Field(
        default=None,
        description="Optional subset of shape paths; omit to use the full shapes package",
    )
    include_turtle: bool = False
    owl_path: str | None = Field(
        default=None,
        description="Optional override path; defaults to configured OWL file",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {},
                {
                    "shape_files": ["patient_shapes.ttl", "doctor_shapes.ttl"],
                    "include_turtle": False,
                },
            ]
        }
    }


class ViolationDetail(BaseModel):
    focus_node: str | None = None
    result_path: str | None = None
    value: str | None = None
    message: str | None = None
    severity: str | None = None
    source_shape: str | None = None
    source_constraint: str | None = None


class ValidationSummaryModel(BaseModel):
    conforms: bool
    total_violations: int
    violation_count: int
    warning_count: int
    info_count: int
    shapes_used: list[str] = Field(default_factory=list)
    data_source: str | None = None
    validated_at: str | None = None


class ValidationResponse(BaseModel):
    """Stable JSON envelope returned by SHACL endpoints."""

    conforms: bool
    summary: ValidationSummaryModel
    violations: list[ViolationDetail] = Field(default_factory=list)
    report_turtle: str | None = None

    @classmethod
    def from_engine_dict(cls, payload: dict[str, Any]) -> "ValidationResponse":
        return cls.model_validate(payload)
