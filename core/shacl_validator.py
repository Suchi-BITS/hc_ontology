"""SHACL validation engine backed by pySHACL."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Iterable

from rdflib import RDF, RDFS, Graph, URIRef

from core.shacl_exceptions import ShaclDataLoadError, ShaclValidationError
from core.shacl_loader import ShaclLoader
from core.shacl_report import ShaclReportFormatter, ValidationResult

logger = logging.getLogger("healthcare_ontology.shacl")


def entail_hierarchy(graph: Graph) -> Graph:
    """Return a copy of ``graph`` with ONLY subclass and subproperty entailments added.

    Why not pySHACL's ``inference="rdfs"``? Full RDFS inference also applies ``rdfs:domain``
    and ``rdfs:range`` *as entailments*: pointing ``hc:hasEncounter`` at a Doctor would make
    that Doctor "an Encounter", and the ``sh:class`` check meant to catch the mistake would
    pass. Validation must treat a domain/range violation as an error, not as a new fact.

    What is entailed: a node typed with a class is also typed with its superclasses (so a
    Diagnosis is a Condition), and a statement made with a property also holds for its
    super-properties (so hasDiagnosis implies hasCondition).
    """
    out = Graph()
    for triple in graph:
        out.add(triple)

    def closure(pairs):
        direct: dict = {}
        for child, parent in pairs:
            if isinstance(child, URIRef) and isinstance(parent, URIRef) and child != parent:
                direct.setdefault(child, set()).add(parent)
        result: dict = {}
        for start in direct:
            seen, stack = set(), list(direct[start])
            while stack:
                current = stack.pop()
                if current not in seen:
                    seen.add(current)
                    stack.extend(direct.get(current, ()))
            result[start] = seen
        return result

    super_classes = closure(graph.subject_objects(RDFS.subClassOf))
    for node, cls in list(graph.subject_objects(RDF.type)):
        for ancestor in super_classes.get(cls, ()):
            out.add((node, RDF.type, ancestor))

    super_props = closure(graph.subject_objects(RDFS.subPropertyOf))
    if super_props:
        for s, p, o in list(graph):
            for ancestor in super_props.get(p, ()):
                out.add((s, ancestor, o))
    return out


class ShaclValidator:
    """Validate RDF/OWL data graphs against SHACL shapes."""

    def __init__(
        self,
        loader: ShaclLoader | None = None,
        formatter: ShaclReportFormatter | None = None,
        owl_file=None,
        validation_mode: str = "warn",
        data_dir: str | Path | None = None,
    ):
        self.loader = loader or ShaclLoader()
        self.formatter = formatter or ShaclReportFormatter()
        # A Dataset (schema + sample data) or a path to one RDF file; None means the configured dataset.
        self.owl_file = owl_file
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

        data_graph = entail_hierarchy(data_graph)

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
                inference="none",
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
        from core.dataset import DatasetError, as_dataset

        dataset = as_dataset(owl_path if owl_path else self.owl_file)
        try:
            data_graph = dataset.graph()
        except DatasetError as exc:
            raise ShaclDataLoadError(str(exc)) from exc
        return self.validate_graph(
            data_graph,
            shape_files=shape_files,
            data_source=dataset.label,
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
        from core.dataset import as_dataset

        dataset = as_dataset(self.owl_file)
        try:
            import pyshacl  # noqa: F401

            pyshacl_ok = True
        except ImportError:
            pyshacl_ok = False

        return {
            "status": "healthy" if shapes["ready"] and pyshacl_ok else "degraded",
            "pyshacl_installed": pyshacl_ok,
            "owl_file": dataset.label,
            "owl_exists": all(p.is_file() for p in dataset.paths),
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
