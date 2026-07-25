"""SHACL validation engine backed by pySHACL."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Iterable

from rdflib import Graph

from core.shacl_exceptions import ShaclDataLoadError, ShaclValidationError
from core.shacl_loader import ShaclLoader
from core.shacl_report import ShaclReportFormatter, ValidationResult

logger = logging.getLogger("healthcare_ontology.shacl")


class ShaclValidator:
    """Validate RDF/OWL data graphs against SHACL shapes."""

    def __init__(
        self,
        loader: ShaclLoader | None = None,
        formatter: ShaclReportFormatter | None = None,
        owl_file: str | None = None,
        validation_mode: str = "warn",
        data_dir: str | Path | None = None,
    ):
        self.loader = loader or ShaclLoader()
        self.formatter = formatter or ShaclReportFormatter()
        self.owl_file = owl_file or "healthcare_ontology.owl"
        self.validation_mode = (validation_mode or "warn").lower()
        self.data_dir = Path(data_dir) if data_dir else None

    @property
    def allow_warnings(self) -> bool:
        """In strict mode, warnings fail conformance."""
        return self.validation_mode != "strict"

    def load_data_graph(
        self,
        *,
        path: str | Path | None = None,
        data: str | None = None,
        rdf_format: str = "xml",
    ) -> Graph:
        graph = Graph()
        try:
            if path is not None:
                p = Path(path)
                if not p.is_file():
                    raise ShaclDataLoadError(f"Data file not found: {p}")
                graph.parse(str(p), format=rdf_format)
            elif data is not None:
                graph.parse(data=data, format=rdf_format)
            else:
                raise ShaclDataLoadError("Provide either path or data")
        except ShaclDataLoadError:
            raise
        except Exception as exc:
            raise ShaclDataLoadError(f"Failed to load RDF data: {exc}") from exc
        return graph

    def validate_graph(
        self,
        data_graph: Graph,
        *,
        shape_files: Iterable[str] | None = None,
        data_source: str | None = None,
        include_turtle: bool = False,
        abort_on_first: bool = False,
        allow_warnings: bool | None = None,
    ) -> ValidationResult:
        shapes_graph = self.loader.load(shape_files)

        used = (
            list(shape_files)
            if shape_files is not None
            else self.loader.list_shape_files()
        )

        try:
            from pyshacl import validate
        except ImportError as exc:
            raise ShaclValidationError(
                "pyshacl is not installed. Add pyshacl to requirements and pip install."
            ) from exc

        warn_ok = self.allow_warnings if allow_warnings is None else allow_warnings

        try:
            conforms, results_graph, _text = validate(
                data_graph,
                shacl_graph=shapes_graph,
                abort_on_first=abort_on_first,
                allow_infos=True,
                allow_warnings=warn_ok,
                meta_shacl=False,
                advanced=True,
                inference="rdfs",
                inplace=False,
            )
        except Exception as exc:
            raise ShaclValidationError(f"pySHACL validation failed: {exc}") from exc

        return self.formatter.format(
            bool(conforms),
            results_graph,
            shapes_used=used,
            data_source=data_source,
            include_turtle=include_turtle,
        )

    def validate_ontology(
        self,
        owl_path: str | Path | None = None,
        *,
        shape_files: Iterable[str] | None = None,
        include_turtle: bool = False,
    ) -> ValidationResult:
        path = Path(owl_path) if owl_path else Path(self.owl_file)
        data_graph = self.load_data_graph(path=path, rdf_format="xml")
        return self.validate_graph(
            data_graph,
            shape_files=shape_files,
            data_source=str(path),
            include_turtle=include_turtle,
        )

    def validate_rdf_text(
        self,
        data: str,
        *,
        rdf_format: str = "turtle",
        shape_files: Iterable[str] | None = None,
        include_turtle: bool = False,
    ) -> ValidationResult:
        data_graph = self.load_data_graph(data=data, rdf_format=rdf_format)
        return self.validate_graph(
            data_graph,
            shape_files=shape_files,
            data_source=f"inline:{rdf_format}",
            include_turtle=include_turtle,
        )

    def validate_data_file(
        self,
        relative_or_absolute: str | Path,
        *,
        shape_files: Iterable[str] | None = None,
        include_turtle: bool = False,
    ) -> ValidationResult:
        """Validate a fixture under data/ (or an absolute path)."""
        path = Path(relative_or_absolute)
        if not path.is_file() and self.data_dir is not None:
            candidate = self.data_dir / relative_or_absolute
            if candidate.is_file():
                path = candidate
            else:
                sample = self.data_dir / "sample_instances" / Path(relative_or_absolute).name
                if sample.is_file():
                    path = sample
        rdf_format = _guess_format(path.name)
        data_graph = self.load_data_graph(path=path, rdf_format=rdf_format)
        return self.validate_graph(
            data_graph,
            shape_files=shape_files,
            data_source=str(path),
            include_turtle=include_turtle,
        )

    def validate_file(
        self,
        file_bytes: bytes,
        filename: str,
        *,
        shape_files: Iterable[str] | None = None,
        include_turtle: bool = False,
    ) -> ValidationResult:
        rdf_format = _guess_format(filename)
        suffix = Path(filename).suffix or ".rdf"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            data_graph = self.load_data_graph(path=tmp_path, rdf_format=rdf_format)
            return self.validate_graph(
                data_graph,
                shape_files=shape_files,
                data_source=filename,
                include_turtle=include_turtle,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def health(self) -> dict:
        shapes = self.loader.health()
        owl = Path(self.owl_file)
        try:
            import pyshacl  # noqa: F401

            pyshacl_ok = True
        except ImportError:
            pyshacl_ok = False

        return {
            "status": "healthy" if shapes["ready"] and pyshacl_ok else "degraded",
            "pyshacl_installed": pyshacl_ok,
            "owl_file": str(owl),
            "owl_exists": owl.is_file(),
            "validation_mode": self.validation_mode,
            "data_dir": str(self.data_dir) if self.data_dir else None,
            "shapes": shapes,
        }


def _guess_format(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".ttl") or lower.endswith(".turtle"):
        return "turtle"
    if lower.endswith(".nt"):
        return "nt"
    if lower.endswith(".n3"):
        return "n3"
    if lower.endswith(".jsonld") or lower.endswith(".json-ld"):
        return "json-ld"
    return "xml"
