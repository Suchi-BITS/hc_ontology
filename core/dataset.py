"""The runtime dataset: the ontology SCHEMA plus (optionally) the synthetic SAMPLE DATA, as one RDF graph.

    ontology/healthcare_schema.ttl   the TBox: classes, properties, vocabularies   (what kinds of things exist)
    data/sample_data.ttl             the ABox: synthetic patients, encounters, ...  (which things exist)
    ----------------------------------------------------------------------------
    Dataset.graph()                  the union, which SHACL, SPARQL, the reasoner and the projection consume

Everything that used to read one combined `healthcare_ontology.owl` now asks a Dataset. A Dataset can also be a
single RDF file (a schema alone, or a custom file in a test), and the sample data can be switched off entirely
(SAMPLE_DATA_FILE empty): the platform then runs on the schema alone.

This module imports only rdflib, so the SPARQL worker process starts quickly and the core stays light.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from rdflib import OWL, RDF, XSD, Graph, Literal, URIRef

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_RELATIVE = "ontology/healthcare_schema.ttl"
DATA_RELATIVE = "data/sample_data.ttl"

SCHEMA_IRI = "http://example.org/healthcare-hospital.owl"
DATA_IRI = "http://example.org/healthcare-hospital-sample-data"
HC = SCHEMA_IRI + "#"

_FORMATS = {".ttl": "turtle", ".turtle": "turtle", ".owl": "xml", ".rdf": "xml", ".xml": "xml", ".nt": "nt"}


class DatasetError(ValueError):
    """A dataset file is missing, has an unknown format, or does not parse."""


def _format(path: Path) -> str:
    fmt = _FORMATS.get(path.suffix.lower())
    if fmt is None:
        raise DatasetError(f"unsupported RDF file extension {path.suffix!r} ({path.name})")
    return fmt


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def parse_into(graph: Graph, path: Path) -> None:
    if not path.is_file():
        raise DatasetError(f"RDF file not found: {path}")
    try:
        graph.parse(path, format=_format(path))
    except DatasetError:
        raise
    except Exception as exc:  # rdflib raises many parser-specific exceptions
        raise DatasetError(f"cannot parse {path.name}: {exc}") from exc


@dataclass(frozen=True)
class Dataset:
    schema: Path
    data: Path | None = None

    # ---- construction --------------------------------------------------------------------------------
    @classmethod
    def default(cls) -> "Dataset":
        """The configured dataset: ONTOLOGY_SCHEMA_FILE plus SAMPLE_DATA_FILE (empty means no sample data)."""
        from core.config import get_settings

        s = get_settings()
        schema = _resolve(s["ontology_schema_file"])
        data = s["sample_data_file"]
        return cls(schema, _resolve(data) if data else None)

    @classmethod
    def single(cls, path: str | Path) -> "Dataset":
        """One RDF file used as the whole dataset (a schema alone, or a custom or test file)."""
        return cls(Path(path))

    # ---- reading ---------------------------------------------------------------------------------------
    @property
    def paths(self) -> list[Path]:
        return [p for p in (self.schema, self.data) if p is not None]

    @property
    def label(self) -> str:
        return " + ".join(p.name for p in self.paths)

    def stamp(self) -> tuple:
        """Changes when any file changes (used by workers to know when to reload)."""
        return tuple(p.stat().st_mtime_ns if p.is_file() else None for p in self.paths)

    def graph(self, *, normalise_strings: bool = False) -> Graph:
        """The union of the schema and the sample data, as one graph.

        normalise_strings: store `"x"^^xsd:string` as the plain literal `"x"`. In RDF 1.1 they are the same value,
        but rdflib matches them as different terms in a triple pattern, so a natural query such as
        `?c hc:codeValue "E11"` would otherwise silently return nothing.
        """
        graph = Graph()
        for path in self.paths:
            parse_into(graph, path)
        if normalise_strings:
            for s, p, o in list(graph):
                if isinstance(o, Literal) and o.datatype == XSD.string:
                    graph.remove((s, p, o))
                    graph.add((s, p, Literal(str(o))))
        return graph

    def rdfxml(self) -> bytes:
        """The union as ONE RDF/XML document, for Owlready2 (which cannot read Turtle).

        See `monolithic`: this is a runtime view; no file of this form is stored.
        """
        text = monolithic(self.graph()).serialize(format="xml")
        return text.encode("utf-8") if isinstance(text, str) else text

    def load_owlready(self):
        """Load the union into Owlready2 (the object model behind the ontology service)."""
        from owlready2 import World

        world = World()
        return world.get_ontology(SCHEMA_IRI + "#").load(fileobj=io.BytesIO(self.rdfxml()))

    def checksum(self) -> str:
        import hashlib

        h = hashlib.sha256()
        for p in self.paths:
            h.update(p.read_bytes() if p.is_file() else b"")
        return h.hexdigest()


def monolithic(graph: Graph) -> Graph:
    """A copy of a merged graph that looks like ONE ontology: the sample-data ontology header and every
    owl:imports are dropped, so a tool that resolves imports (Owlready2, a reasoner) does not go looking for
    the schema on the network. The instances and the schema are untouched."""
    view = Graph()
    header = URIRef(DATA_IRI)
    for s, p, o in graph:
        if s == header or p == OWL.imports:
            continue
        view.add((s, p, o))
    return view


def as_dataset(source) -> Dataset:
    """A Dataset, a path to one RDF file, or None for the configured default."""
    if source is None:
        return Dataset.default()
    if isinstance(source, Dataset):
        return source
    return Dataset.single(source)


# ---- writing (used by the two generators) --------------------------------------------------------------

def write_turtle(graph: Graph, path: str | Path, prefixes: dict[str, str], header: str = "") -> None:
    """Deterministic Turtle: blank nodes are canonicalised and rdflib sorts the output, so the same graph
    always produces the same bytes. Written atomically."""
    import os
    import tempfile

    from rdflib.compare import to_canonical_graph

    canonical = Graph()
    for triple in to_canonical_graph(graph):
        canonical.add(triple)
    for prefix, iri in prefixes.items():
        canonical.bind(prefix, iri, override=True)
    text = canonical.serialize(format="turtle")
    text = text if isinstance(text, str) else text.decode("utf-8")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".ttl", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(header + text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
