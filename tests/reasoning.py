"""Helper: run the OWL reasoner (HermiT via Owlready2) on an rdflib graph.

xsd:date is outside the OWL 2 datatype map, so HermiT rejects it. The reasoner therefore
sees a *view* of the graph with xsd:date literals and xsd:date ranges removed; nothing else
changes. Needs Java.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from rdflib import RDFS, XSD, Graph, Literal

_skip_without_java = pytest.mark.skipif(shutil.which("java") is None, reason="Java is required for the OWL reasoner")


def needs_java(test):
    """Mark a test as reasoner-backed and skip it when Java is unavailable."""
    return pytest.mark.reasoner(_skip_without_java(test))


def strip_dates(graph: Graph) -> Graph:
    view = Graph()
    for s, p, o in graph:
        if isinstance(o, Literal) and o.datatype == XSD.date:
            continue
        if p == RDFS.range and o == XSD.date:
            continue
        view.add((s, p, o))
    return view


def reason(graph: Graph):
    """Return (world, ontology) after classification. Raises OwlReadyInconsistentOntologyError if inconsistent."""
    from owlready2 import World, sync_reasoner

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "reasoner_view.owl"
        from core.dataset import monolithic

        strip_dates(monolithic(graph)).serialize(path, format="xml")
        world = World()
        onto = world.get_ontology("file://" + str(path).replace("\\", "/")).load()
        sync_reasoner(world, infer_property_values=True, debug=0)
        return world, onto
