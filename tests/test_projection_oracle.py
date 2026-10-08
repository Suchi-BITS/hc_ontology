"""Does the RDF -> property-graph projection lose anything? An independent oracle.

The oracle re-derives, from the raw RDF triples alone, what MUST be present in the projection:
every asserted type, every literal value, every relationship between individuals, every
subclass link, and identity by IRI. It shares no code with the projection builder.

Then comes the part that makes the oracle trustworthy: we build deliberately DEGRADED
projections that reproduce the defects of the old exporter (first type only, first value only,
flattened hierarchy, identity by name, dropped relationships) and require the oracle to catch
each one. A check that cannot fail proves nothing.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from pathlib import Path

from core.dataset import Dataset

import pytest
from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef

from services.graph_projection import (
    SUBCLASS_REL,
    ProjectedNode,
    Projection,
    build_projection,
    local_name,
)

ROOT = Path(__file__).resolve().parent.parent
RICH = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.org/t#> .
<http://example.org/t> a owl:Ontology .
ex:Person a owl:Class . ex:Patient a owl:Class ; rdfs:subClassOf ex:Person .
ex:Staff a owl:Class ; rdfs:subClassOf ex:Person .
ex:phone a owl:DatatypeProperty . ex:name2 a owl:DatatypeProperty, owl:FunctionalProperty .
ex:knows a owl:ObjectProperty .
ex:alice a owl:NamedIndividual, ex:Patient, ex:Staff ; ex:phone "3", "1", "2" ; ex:name2 "Alice" ; ex:knows ex:bob .
ex:bob a owl:NamedIndividual, ex:Patient ; ex:phone "9" .
<http://other.example.org/id#alice> a owl:NamedIndividual, ex:Patient .
"""


def rich_graph() -> Graph:
    return Graph().parse(data=RICH, format="turtle")


def lost(graph: Graph, projection: Projection) -> list[str]:
    """Everything the RDF says about an individual that the projection does not carry."""
    problems: list[str] = []
    by_iri = {n.iri: n for n in projection.nodes}
    declared = {c for c in graph.subjects(RDF.type, OWL.Class) if isinstance(c, URIRef)}
    parents: dict = {}
    for child, parent in graph.subject_objects(RDFS.subClassOf):
        if isinstance(child, URIRef) and isinstance(parent, URIRef) and parent != OWL.Thing:
            parents.setdefault(child, set()).add(parent)

    def ancestors(c):
        seen, stack = set(), list(parents.get(c, ()))
        while stack:
            x = stack.pop()
            if x not in seen:
                seen.add(x)
                stack.extend(parents.get(x, ()))
        return seen

    meta = {OWL.NamedIndividual, OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.Ontology,
            OWL.FunctionalProperty, OWL.Restriction, OWL.AllDisjointClasses, OWL.AnnotationProperty,
            OWL.TransitiveProperty}
    individuals = {
        s for s in graph.subjects(RDF.type, OWL.NamedIndividual) if isinstance(s, URIRef)
    }
    edges = {(e.source, e.rel_type, e.target) for e in projection.edges}

    for ind in individuals:
        node = by_iri.get(str(ind))
        if node is None:
            problems.append(f"node missing for <{ind}>")  # identity is the IRI
            continue
        if node.properties.get("iri") != str(ind):
            problems.append(f"iri property wrong for <{ind}>")
        asserted = {t for t in graph.objects(ind, RDF.type) if isinstance(t, URIRef) and t not in meta}
        if set(node.properties.get("rdfTypes", [])) != {str(t) for t in asserted}:
            problems.append(f"asserted types of <{ind}> not preserved")
        for t in asserted | {a for t in asserted for a in ancestors(t)}:
            if local_name(t) not in node.labels:
                problems.append(f"label {local_name(t)} missing on <{ind}>")
        for pred, obj in graph.predicate_objects(ind):
            if pred in (RDF.type, RDFS.subClassOf):
                continue
            key = local_name(pred)
            if isinstance(obj, Literal):
                value = node.properties.get(key)
                values = value if isinstance(value, list) else [value]
                wanted = obj.toPython() if not isinstance(obj.toPython(), Literal) else str(obj)
                if isinstance(wanted, Decimal):  # documented: Neo4j has no decimal type
                    wanted = float(wanted)
                if wanted not in values:
                    problems.append(f"value {wanted!r} of {key} lost on <{ind}>")
            elif isinstance(obj, URIRef) and obj in individuals:
                if (str(ind), key.upper(), str(obj)) not in edges:
                    problems.append(f"relationship {key} <{ind}> -> <{obj}> lost")
    for child, parent in ((c, p) for c in declared for p in parents.get(c, ()) if p in declared):
        if (str(child), SUBCLASS_REL, str(parent)) not in edges:
            problems.append(f"subclass link {local_name(child)} -> {local_name(parent)} lost")
    return problems


# ---- the oracle passes on faithful projections ----------------------------------------

def test_oracle_finds_nothing_lost_on_the_real_ontology():
    graph = Dataset.default().graph()
    assert lost(graph, build_projection(graph)) == []


def test_oracle_finds_nothing_lost_on_a_graph_with_multiple_types_and_values():
    graph = rich_graph()
    assert lost(graph, build_projection(graph)) == []


def test_oracle_inputs_really_contain_what_it_checks():
    """Guard against a vacuous oracle: the data must actually have multi-type, multi-value, hierarchy."""
    graph = rich_graph()
    alice = URIRef("http://example.org/t#alice")
    assert len(set(graph.objects(alice, RDF.type)) - {OWL.NamedIndividual}) == 2
    assert len(list(graph.objects(alice, URIRef("http://example.org/t#phone")))) == 3
    real = Dataset.default().graph()
    assert len(list(real.subject_objects(RDFS.subClassOf))) > 40


# ---- degraded projections: each reproduces an old-exporter defect ----------------------------

def rebuild(projection: Projection, *, nodes=None, edges=None) -> Projection:
    return dataclasses.replace(
        projection,
        nodes=projection.nodes if nodes is None else nodes,
        edges=projection.edges if edges is None else edges,
    )


def with_props(node: ProjectedNode, **changes) -> ProjectedNode:
    props = {**node.properties, **changes}
    return dataclasses.replace(node, properties=props)


def drop_types(p: Projection) -> Projection:
    """Keep only the first type (the old `individual.is_a[0]`), no superclass labels."""
    out = []
    for n in p.nodes:
        types = n.properties["rdfTypes"][:1]
        keep = {"Resource"} | {local_name(t) for t in types}
        out.append(dataclasses.replace(with_props(n, rdfTypes=types), labels=tuple(sorted(keep))))
    return rebuild(p, nodes=out)


def first_value_only(p: Projection) -> Projection:
    out = []
    for n in p.nodes:
        changes = {k: v[:1] for k, v in n.properties.items() if isinstance(v, list) and k != "rdfTypes"}
        out.append(with_props(n, **changes))
    return rebuild(p, nodes=out)


def flatten_hierarchy(p: Projection) -> Projection:
    """No SUBCLASS_OF edges and no inherited labels."""
    out = []
    for n in p.nodes:
        keep = {"Resource"} | {local_name(t) for t in n.properties["rdfTypes"]}
        out.append(dataclasses.replace(n, labels=tuple(sorted(keep))))
    return rebuild(p, nodes=out, edges=[e for e in p.edges if e.rel_type != SUBCLASS_REL])


def identity_by_name(p: Projection) -> Projection:
    """Merge nodes that share a display name (the old MERGE on {name})."""
    seen: dict[str, ProjectedNode] = {}
    for n in p.nodes:
        seen.setdefault(n.properties["name"], n)
    return rebuild(p, nodes=list(seen.values()))


def drop_relationships(p: Projection) -> Projection:
    return rebuild(p, edges=[e for e in p.edges if e.rel_type == SUBCLASS_REL or e.rel_type == "INSTANCE_OF"])


DEFECTS = {
    "first_type_only": (drop_types, "types"),
    "first_value_only": (first_value_only, "lost"),
    "flattened_hierarchy": (flatten_hierarchy, "subclass link"),
    "identity_by_name": (identity_by_name, "node missing"),
    "dropped_relationships": (drop_relationships, "relationship"),
}


@pytest.mark.parametrize("defect", sorted(DEFECTS))
def test_the_oracle_catches_each_old_exporter_defect(defect):
    degrade, expected = DEFECTS[defect]
    graph = rich_graph()
    problems = lost(graph, degrade(build_projection(graph)))
    assert any(expected in p or "label" in p for p in problems), f"the oracle failed to detect {defect}: {problems}"


@pytest.mark.parametrize("defect", ["first_type_only", "flattened_hierarchy", "dropped_relationships"])
def test_the_oracle_also_catches_those_defects_on_the_real_ontology(defect):
    degrade, _ = DEFECTS[defect]
    graph = Dataset.default().graph()
    assert lost(graph, degrade(build_projection(graph)))


def test_each_defect_is_detected_for_the_right_reason():
    graph = rich_graph()
    base = build_projection(graph)
    assert any("asserted types" in p for p in lost(graph, drop_types(base)))
    assert any("phone" in p for p in lost(graph, first_value_only(base)))
    assert any("subclass link" in p for p in lost(graph, flatten_hierarchy(base)))
    assert any("node missing" in p for p in lost(graph, identity_by_name(base)))
    assert any("relationship knows" in p for p in lost(graph, drop_relationships(base)))
