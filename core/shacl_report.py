"""Convert pySHACL validation results into JSON-friendly structures and HTML."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from rdflib import Graph, RDF
from rdflib.namespace import SH


@dataclass
class ValidationViolation:
    focus_node: str | None = None
    result_path: str | None = None
    value: str | None = None
    message: str | None = None
    severity: str | None = None
    source_shape: str | None = None
    source_constraint: str | None = None


@dataclass
class ValidationSummary:
    conforms: bool
    total_violations: int
    violation_count: int
    warning_count: int
    info_count: int
    shapes_used: list[str] = field(default_factory=list)
    data_source: str | None = None
    validated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class ValidationResult:
    summary: ValidationSummary
    violations: list[ValidationViolation] = field(default_factory=list)
    report_graph_turtle: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "conforms": self.summary.conforms,
            "summary": asdict(self.summary),
            "violations": [asdict(v) for v in self.violations],
        }


class ShaclReportFormatter:
    """Formats pySHACL results into structured JSON and optional HTML."""

    SEVERITY_LABELS = {
        str(SH.Violation): "Violation",
        str(SH.Warning): "Warning",
        str(SH.Info): "Info",
    }

    def format(
        self,
        conforms: bool,
        results_graph: Graph,
        *,
        shapes_used: list[str] | None = None,
        data_source: str | None = None,
        include_turtle: bool = False,
    ) -> ValidationResult:
        violations = self._extract_violations(results_graph)

        violation_count = sum(1 for v in violations if v.severity == "Violation")
        warning_count = sum(1 for v in violations if v.severity == "Warning")
        info_count = sum(1 for v in violations if v.severity == "Info")

        summary = ValidationSummary(
            conforms=conforms,
            total_violations=len(violations),
            violation_count=violation_count,
            warning_count=warning_count,
            info_count=info_count,
            shapes_used=shapes_used or [],
            data_source=data_source,
        )

        turtle = None
        if include_turtle:
            turtle = results_graph.serialize(format="turtle")

        return ValidationResult(
            summary=summary,
            violations=violations,
            report_graph_turtle=turtle,
        )

    def to_html(self, result: ValidationResult) -> str:
        s = result.summary
        status = "CONFORMS" if s.conforms else "DOES NOT CONFORM"
        color = "#0a7a2f" if s.conforms else "#b00020"

        rows = []
        for v in result.violations:
            rows.append(
                "<tr>"
                f"<td>{_esc(v.severity)}</td>"
                f"<td>{_esc(v.focus_node)}</td>"
                f"<td>{_esc(v.result_path)}</td>"
                f"<td>{_esc(v.message)}</td>"
                f"<td>{_esc(v.value)}</td>"
                "</tr>"
            )

        empty_row = '<tr><td colspan="5">No issues</td></tr>'
        body_rows = "".join(rows) or empty_row
        table = (
            "<table border='1' cellpadding='6' cellspacing='0'>"
            "<thead><tr>"
            "<th>Severity</th><th>Focus node</th><th>Path</th>"
            "<th>Message</th><th>Value</th>"
            "</tr></thead>"
            f"<tbody>{body_rows}</tbody>"
            "</table>"
        )

        shapes_list = _esc(", ".join(s.shapes_used))
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>SHACL Validation Report</title></head>
<body style="font-family: system-ui, sans-serif; margin: 2rem;">
  <h1>SHACL Validation Report</h1>
  <p><strong style="color:{color}">{status}</strong></p>
  <ul>
    <li>Validated at: {_esc(s.validated_at)}</li>
    <li>Data source: {_esc(s.data_source)}</li>
    <li>Total results: {s.total_violations}</li>
    <li>Violations: {s.violation_count} · Warnings: {s.warning_count} · Info: {s.info_count}</li>
    <li>Shapes: {shapes_list}</li>
  </ul>
  {table}
</body></html>"""

    def _extract_violations(self, results_graph: Graph) -> list[ValidationViolation]:
        violations: list[ValidationViolation] = []
        for result in results_graph.subjects(RDF.type, SH.ValidationResult):
            severity_uri = results_graph.value(result, SH.resultSeverity)
            severity = self.SEVERITY_LABELS.get(str(severity_uri), str(severity_uri))

            messages = list(results_graph.objects(result, SH.resultMessage))
            message = "; ".join(str(m) for m in messages) if messages else None

            violations.append(
                ValidationViolation(
                    focus_node=_term_str(results_graph.value(result, SH.focusNode)),
                    result_path=_term_str(results_graph.value(result, SH.resultPath)),
                    value=_term_str(results_graph.value(result, SH.value)),
                    message=message,
                    severity=severity,
                    source_shape=_term_str(results_graph.value(result, SH.sourceShape)),
                    source_constraint=_term_str(
                        results_graph.value(result, SH.sourceConstraintComponent)
                    ),
                )
            )

        # Stable order for tests / API consumers
        severity_order = {"Violation": 0, "Warning": 1, "Info": 2}
        violations.sort(
            key=lambda v: (
                severity_order.get(v.severity or "", 9),
                v.focus_node or "",
                v.result_path or "",
            )
        )
        return violations


def _term_str(term: Any) -> str | None:
    if term is None:
        return None
    return str(term)


def _esc(value: str | None) -> str:
    if value is None:
        return ""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
