"""Deterministic RDF -> property-graph projection (pure logic, no Neo4j).

RDF/OWL/SHACL is the semantic authority. Neo4j is a *derived* operational
projection. This module turns an rdflib ``Graph`` into a ``Projection`` (plain
data) that a writer can load into any property-graph store. It never talks to a
database and never writes back to RDF.

Mapping (see docs/semantic-authority-and-graph-projection.md):

    named individual            -> node  (:Resource:<asserted types>:<all superclasses>)
    IRI                         -> node property ``iri`` (the identity; unique)
    local name of the IRI       -> node property ``name`` (display / query convenience only)
    asserted rdf:type IRIs      -> node property ``rdfTypes`` (asserted, not inferred)
    owl:Class                   -> node (:OntologyClass {iri, name, ...})
    rdfs:subClassOf (named)     -> (:OntologyClass)-[:SUBCLASS_OF]->(:OntologyClass)
    rdf:type                    -> (:Resource)-[:INSTANCE_OF]->(:OntologyClass)
    object-valued triple        -> relationship, type = UPPERCASE local name of the predicate
    literal-valued triple       -> node property, key = local name of the predicate
                                   functional property  -> scalar
                                   anything else        -> list (never reduced to the first value)

The output is deterministic: nodes, edges and list values are sorted, so the
same RDF always yields the same ``Projection`` and the same ``fingerprint()``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from rdflib import OWL, RDF, RDFS, BNode, Graph, Literal, URIRef

RESOURCE_LABEL = "Resource"
CLASS_LABEL = "OntologyClass"
SUBCLASS_REL = "SUBCLASS_OF"
INSTANCE_REL = "INSTANCE_OF"
RESERVED_KEYS = frozenset({"iri", "name", "rdfTypes", "external", "definedClass"})

_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# rdf:type objects that describe the schema/vocabulary machinery, not domain classes.
_META_TYPES = frozenset(
    {
        OWL.Class, RDFS.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty,
        RDF.Property, OWL.FunctionalProperty, OWL.InverseFunctionalProperty, OWL.TransitiveProperty,
        OWL.SymmetricProperty, OWL.Ontology, OWL.Restriction, OWL.AllDisjointClasses,
        OWL.AllDifferent, OWL.NamedIndividual, OWL.Thing,
    }
)
# Predicates handled structurally, never as properties or relationships.
_STRUCTURAL_PREDICATES = frozenset(
    {
        RDF.type, RDFS.subClassOf, OWL.equivalentClass, OWL.disjointWith, OWL.sameAs,
        OWL.differentFrom, OWL.inverseOf, RDFS.domain, RDFS.range, RDFS.subPropertyOf,
        OWL.imports, OWL.versionIRI, OWL.versionInfo,
    }
)


class ProjectionError(ValueError):
    """The RDF cannot be projected faithfully. ``problems`` lists every defect found."""

    def __init__(self, problems: Iterable[str]):
        self.problems = list(problems)
        shown = "; ".join(self.problems[:5])
        extra = f" (+{len(self.problems) - 5} more)" if len(self.problems) > 5 else ""
        super().__init__(f"Invalid RDF for projection: {shown}{extra}")


def local_name(iri: str) -> str:
    """Local part of an IRI: after '#', otherwise after the last '/'."""
    text = str(iri)
    if "#" in text:
        return text.rsplit("#", 1)[1]
    return text.rstrip("/").rsplit("/", 1)[-1]


@dataclass(frozen=True)
class ProjectedNode:
    iri: str
    labels: tuple[str, ...]
    properties: dict[str, Any]

    def label_key(self) -> tuple[str, ...]:
        return self.labels


@dataclass(frozen=True)
class ProjectedEdge:
    source: str
    rel_type: str
    target: str
    source_label: str
    target_label: str
    inferred: bool = False  # True when entailed by owl:inverseOf / rdfs:subPropertyOf, not asserted


@dataclass
class Projection:
    nodes: list[ProjectedNode] = field(default_factory=list)  # Resource nodes (individuals)
    classes: list[ProjectedNode] = field(default_factory=list)  # OntologyClass nodes
    edges: list[ProjectedEdge] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # information deliberately not projected

    # ---- derived views --------------------------------------------------
    @property
    def class_labels(self) -> list[str]:
        return sorted({c.properties["name"] for c in self.classes})

    def node(self, iri: str) -> ProjectedNode:
        for n in self.nodes:
            if n.iri == iri:
                return n
        raise KeyError(iri)

    def edges_of(self, rel_type: str) -> list[ProjectedEdge]:
        return [e for e in self.edges if e.rel_type == rel_type]

    def summary(self) -> dict[str, Any]:
        rel_counts: dict[str, int] = {}
        for e in self.edges:
            rel_counts[e.rel_type] = rel_counts.get(e.rel_type, 0) + 1
        return {
            "nodes": len(self.nodes),
            "classes": len(self.classes),
            "relationships": len(self.edges),
            "relationship_types": dict(sorted(rel_counts.items())),
            "fingerprint": self.fingerprint(),
            "not_projected": list(self.notes),
        }

    # ---- determinism ----------------------------------------------------
    def canonical(self) -> dict[str, Any]:
        return {
            "nodes": [
                {"iri": n.iri, "labels": list(n.labels), "properties": _canon(n.properties)}
                for n in self.nodes
            ],
            "classes": [
                {"iri": c.iri, "labels": list(c.labels), "properties": _canon(c.properties)}
                for c in self.classes
            ],
            "edges": [
                [e.source_label, e.source, e.rel_type, e.target_label, e.target, e.inferred] for e in self.edges
            ],
        }

    def fingerprint(self) -> str:
        blob = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Value handling
# ---------------------------------------------------------------------------

def _to_native(lit: Literal) -> Any:
    """Typed Python value for a literal. Nothing is stringified unless the type is unknown."""
    py = lit.toPython()
    if isinstance(py, Literal):  # no Python mapping for the datatype (for example xsd:string, xsd:anyURI)
        return str(lit)
    if isinstance(py, bool):
        return py
    if isinstance(py, (int, float, str)) and not isinstance(py, URIRef):
        return py
    if isinstance(py, Decimal):
        return float(py)
    if isinstance(py, (datetime, date)):
        return py
    return str(lit)  # unknown or ill-typed datatype: keep the lexical form


def _canon_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"datetime": value.isoformat()}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, list):
        return [_canon_value(v) for v in value]
    return value


def _canon(properties: dict[str, Any]) -> dict[str, Any]:
    return {k: _canon_value(v) for k, v in sorted(properties.items())}


def _sort_key(value: Any) -> tuple[str, str]:
    canon = _canon_value(value)
    return (type(value).__name__, json.dumps(canon, sort_keys=True))


def _require_safe(name: str, what: str, iri: str, problems: list[str]) -> bool:
    if not _SAFE_NAME.match(name):
        problems.append(f"{what} name {name!r} from <{iri}> is not a safe identifier")
        return False
    return True


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_FORMATS = {".owl": "xml", ".rdf": "xml", ".xml": "xml", ".ttl": "turtle", ".nt": "nt", ".jsonld": "json-ld"}


def load_graph(source: "str | Path | Graph") -> Graph:
    """Parse an RDF file (format from the extension). Parse failures become ProjectionError."""
    if isinstance(source, Graph):
        return source
    from core.dataset import Dataset, DatasetError

    if isinstance(source, Dataset):
        try:
            return source.graph()
        except DatasetError as exc:
            raise ProjectionError([str(exc)]) from exc
    path = Path(source)
    if not path.is_file():
        raise ProjectionError([f"RDF file not found: {path}"])
    fmt = _FORMATS.get(path.suffix.lower())
    if fmt is None:
        raise ProjectionError([f"unsupported RDF file extension {path.suffix!r}"])
    graph = Graph()
    try:
        graph.parse(path, format=fmt)
    except Exception as exc:  # rdflib raises many parser-specific exceptions
        raise ProjectionError([f"cannot parse {path.name} as {fmt}: {exc}"]) from exc
    return graph


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def build_projection(source: "str | Path | Graph") -> Projection:
    """Build the deterministic projection of an RDF graph, or raise ProjectionError."""
    graph = load_graph(source)
    problems: list[str] = []

    if len(graph) == 0:
        raise ProjectionError(["the RDF graph is empty"])
    if (None, RDF.type, OWL.Ontology) not in graph:
        raise ProjectionError(["no owl:Ontology header: this is not an ontology document"])

    declared_classes = {
        c for c in graph.subjects(RDF.type, OWL.Class) if isinstance(c, URIRef) and c != OWL.Thing
    }
    object_props = set(graph.subjects(RDF.type, OWL.ObjectProperty))
    functional = set(graph.subjects(RDF.type, OWL.FunctionalProperty))

    # ---- class hierarchy (named classes only) -------------------------------
    parents: dict[URIRef, set[URIRef]] = {}
    for child, parent in graph.subject_objects(RDFS.subClassOf):
        if isinstance(child, URIRef) and isinstance(parent, URIRef) and parent != OWL.Thing and child != parent:
            parents.setdefault(child, set()).add(parent)

    def ancestors(cls: URIRef) -> set[URIRef]:
        seen: set[URIRef] = set()
        stack = list(parents.get(cls, ()))
        while stack:
            current = stack.pop()
            if current not in seen:
                seen.add(current)
                stack.extend(parents.get(current, ()))
        return seen

    # ---- individuals -------------------------------------------------------------
    schema_subjects = (
        declared_classes | object_props | set(graph.subjects(RDF.type, OWL.DatatypeProperty))
        | set(graph.subjects(RDF.type, OWL.AnnotationProperty))
    )
    individuals: dict[URIRef, set[URIRef]] = {}
    for subject in set(s for s in graph.subjects(RDF.type, None) if isinstance(s, URIRef)):
        if subject in schema_subjects:
            continue
        types = {t for t in graph.objects(subject, RDF.type) if isinstance(t, URIRef)}
        domain_types = types - _META_TYPES
        if domain_types or OWL.NamedIndividual in types:
            individuals[subject] = domain_types

    # ---- class nodes (declared + any type referenced by an individual) -----------
    class_iris: set[URIRef] = set(declared_classes)
    for types in individuals.values():
        class_iris |= types
    for cls in list(class_iris):
        class_iris |= ancestors(cls)

    class_names: dict[URIRef, str] = {}
    seen_names: dict[str, URIRef] = {}
    for cls in sorted(class_iris):
        name = local_name(cls)
        if not _require_safe(name, "class", str(cls), problems):
            continue
        if name in seen_names:
            problems.append(f"classes <{seen_names[name]}> and <{cls}> share the local name {name!r}")
            continue
        seen_names[name] = cls
        class_names[cls] = name

    # ---- property key / relationship type registries ----------------------------
    key_owner: dict[str, URIRef] = {}
    rel_owner: dict[str, URIRef] = {}

    def property_key(pred: URIRef) -> str | None:
        name = local_name(pred)
        if not _require_safe(name, "property", str(pred), problems):
            return None
        if name in RESERVED_KEYS:
            problems.append(f"property <{pred}> collides with the reserved key {name!r}")
            return None
        if key_owner.setdefault(name, pred) != pred:
            problems.append(f"properties <{key_owner[name]}> and <{pred}> share the key {name!r}")
            return None
        return name

    def relationship_type(pred: URIRef) -> str | None:
        name = local_name(pred)
        if not _require_safe(name, "relationship", str(pred), problems):
            return None
        rel = name.upper()
        if rel in (SUBCLASS_REL, INSTANCE_REL):
            problems.append(f"relationship <{pred}> collides with the reserved type {rel}")
            return None
        if rel_owner.setdefault(rel, pred) != pred:
            problems.append(f"relationships <{rel_owner[rel]}> and <{pred}> share the type {rel}")
            return None
        return rel

    def collect_properties(subject: URIRef) -> tuple[dict[str, Any], list[tuple[URIRef, URIRef]]]:
        """Literal-valued triples -> properties; IRI-valued triples -> candidate edges."""
        values: dict[str, list[Any]] = {}
        owners: dict[str, URIRef] = {}
        links: list[tuple[URIRef, URIRef]] = []
        for pred, obj in graph.predicate_objects(subject):
            if pred in _STRUCTURAL_PREDICATES:
                continue
            if isinstance(obj, Literal):
                key = property_key(pred)
                if key is None:
                    continue
                values.setdefault(key, []).append(_to_native(obj))
                owners[key] = pred
            elif isinstance(obj, URIRef):
                links.append((pred, obj))
            elif isinstance(obj, BNode):
                projection_notes.add(f"blank-node value of <{pred}> on <{subject}> was not projected")
        props: dict[str, Any] = {}
        for key, vals in values.items():
            unique = sorted({json.dumps(_canon_value(v), sort_keys=True): v for v in vals}.values(), key=_sort_key)
            kinds = {type(v).__name__ for v in unique}
            if len(kinds) > 1:
                problems.append(
                    f"<{subject}> mixes datatypes {sorted(kinds)} for <{owners[key]}>; "
                    "a property-graph list must be homogeneous"
                )
                continue
            if owners[key] in functional:
                if len(unique) > 1:
                    problems.append(
                        f"<{subject}> has {len(unique)} values for functional property <{owners[key]}>"
                    )
                    continue
                props[key] = unique[0]
            else:
                props[key] = unique
        return props, links

    projection_notes: set[str] = set()
    projection = Projection()

    # ---- class nodes ----------------------------------------------------------------
    for cls in sorted(class_names):
        name = class_names[cls]
        props, _links = collect_properties(cls)
        props.update({"iri": str(cls), "name": name})
        if cls not in declared_classes:
            props["external"] = True
        if (cls, OWL.equivalentClass, None) in graph:
            props["definedClass"] = True
            projection_notes.add(
                "equivalentClass axioms are flagged (definedClass=true) but their class expressions "
                "stay in RDF; use the RDF store/reasoner to evaluate them"
            )
        projection.classes.append(ProjectedNode(str(cls), (CLASS_LABEL,), dict(sorted(props.items()))))

    # ---- individual nodes --------------------------------------------------------------
    node_iris = set(individuals)
    pending_edges: list[ProjectedEdge] = []
    asserted_links: list[tuple[URIRef, URIRef, URIRef]] = []
    for subject in sorted(individuals):
        asserted = individuals[subject]
        label_set = {RESOURCE_LABEL}
        for cls in asserted | {a for t in asserted for a in ancestors(t)}:
            if cls in class_names:
                label_set.add(class_names[cls])
        props, links = collect_properties(subject)
        name = local_name(subject)
        props.update(
            {
                "iri": str(subject),
                "name": name,
                "rdfTypes": sorted(str(t) for t in asserted),
            }
        )
        # extra literal-less IRI links to non-individuals are kept as string lists, never dropped
        external_refs: dict[str, list[str]] = {}
        for pred, obj in links:
            if obj in node_iris:
                rel = relationship_type(pred)
                if rel:
                    pending_edges.append(ProjectedEdge(str(subject), rel, str(obj), RESOURCE_LABEL, RESOURCE_LABEL))
                    asserted_links.append((subject, pred, obj))
            elif pred in object_props:
                problems.append(f"<{subject}> -> <{pred}> -> <{obj}>: the target is not defined in this graph")
            else:
                key = property_key(pred)
                if key:
                    external_refs.setdefault(key, []).append(str(obj))
        for key, refs in external_refs.items():
            props[key] = sorted(set(refs))
        projection.nodes.append(
            ProjectedNode(str(subject), tuple(sorted(label_set)), dict(sorted(props.items())))
        )
        for t in sorted(asserted):
            if t in class_names:
                pending_edges.append(
                    ProjectedEdge(str(subject), INSTANCE_REL, str(t), RESOURCE_LABEL, CLASS_LABEL)
                )

    for child in sorted(parents):
        for parent in sorted(parents[child]):
            if child in class_names and parent in class_names:
                pending_edges.append(
                    ProjectedEdge(str(child), SUBCLASS_REL, str(parent), CLASS_LABEL, CLASS_LABEL)
                )

    # ---- entailed relationships: owl:inverseOf and rdfs:subPropertyOf ---------------
    # These are logical consequences of the schema, not new facts. They are marked
    # inferred=True so asserted and entailed edges stay distinguishable, and they let a
    # query use either direction (hasDiagnosis / diagnosisForPatient) or a super-property.
    supers: dict[URIRef, set[URIRef]] = {}
    for sub, sup in graph.subject_objects(RDFS.subPropertyOf):
        if isinstance(sub, URIRef) and isinstance(sup, URIRef) and sub != sup:
            supers.setdefault(sub, set()).add(sup)
    inverses: dict[URIRef, set[URIRef]] = {}
    for a, b in graph.subject_objects(OWL.inverseOf):
        if isinstance(a, URIRef) and isinstance(b, URIRef):
            inverses.setdefault(a, set()).add(b)
            inverses.setdefault(b, set()).add(a)

    def expansions(pred: URIRef) -> set[tuple[URIRef, bool]]:
        seen = {(pred, False)}
        stack = [(pred, False)]
        while stack:
            current, flipped = stack.pop()
            for nxt, flip in [(s, flipped) for s in supers.get(current, ())] + [
                (i, not flipped) for i in inverses.get(current, ())
            ]:
                if (nxt, flip) not in seen:
                    seen.add((nxt, flip))
                    stack.append((nxt, flip))
        return seen - {(pred, False)}

    asserted_keys = {(e.source, e.rel_type, e.target) for e in pending_edges}
    for subject, pred, obj in asserted_links:
        for other, flipped in expansions(pred):
            rel = relationship_type(other)
            if not rel:
                continue
            src, dst = (obj, subject) if flipped else (subject, obj)
            if (str(src), rel, str(dst)) in asserted_keys:
                continue
            pending_edges.append(
                ProjectedEdge(str(src), rel, str(dst), RESOURCE_LABEL, RESOURCE_LABEL, inferred=True)
            )

    if problems:
        raise ProjectionError(sorted(set(problems)))

    projection.edges = sorted(
        set(pending_edges), key=lambda e: (e.source_label, e.source, e.rel_type, e.target_label, e.target)
    )
    projection.notes = sorted(projection_notes)
    return projection


# ---------------------------------------------------------------------------
# Human-readable Cypher rendering (GET /neo4j/export; the writer uses parameters)
# ---------------------------------------------------------------------------

def cypher_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, datetime):
        return f'datetime("{value.isoformat()}")'
    if isinstance(value, date):
        return f'date("{value.isoformat()}")'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(cypher_literal(v) for v in value) + "]"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    return f'"{text}"'


def to_cypher_script(projection: Projection) -> list[str]:
    """Idempotent MERGE statements equivalent to the parameterized load. For inspection only."""
    statements: list[str] = []
    for c in projection.classes:
        statements.append(
            f"MERGE (n:{CLASS_LABEL} {{iri: {cypher_literal(c.iri)}}}) SET n = {_map_literal(c.properties)}"
        )
    for n in projection.nodes:
        extra = "".join(f":{label}" for label in n.labels if label != RESOURCE_LABEL)
        statements.append(
            f"MERGE (n:{RESOURCE_LABEL} {{iri: {cypher_literal(n.iri)}}}) SET n{extra} SET n = {_map_literal(n.properties)}"
        )
    for e in projection.edges:
        statements.append(
            f"MATCH (a:{e.source_label} {{iri: {cypher_literal(e.source)}}}), "
            f"(b:{e.target_label} {{iri: {cypher_literal(e.target)}}}) MERGE (a)-[:{e.rel_type}]->(b)"
            + (" // entailed" if e.inferred else "")
        )
    return statements


def _map_literal(props: dict[str, Any]) -> str:
    return "{" + ", ".join(f"{k}: {cypher_literal(v)}" for k, v in sorted(props.items())) + "}"
