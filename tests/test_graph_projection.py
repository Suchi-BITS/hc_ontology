"""RDF -> property-graph projection: semantics, identity, determinism, rejection.

These tests need no Neo4j. They exercise services/graph_projection.py (pure logic)
and the statement planner of services/neo4j_exporter.py.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest
from rdflib import OWL, RDF, Graph, URIRef

from services.graph_projection import (
    INSTANCE_REL,
    SUBCLASS_REL,
    ProjectionError,
    build_projection,
    cypher_literal,
    load_graph,
    local_name,
    to_cypher_script,
)
from services.neo4j_exporter import reset_statements, schema_statements, write_statements

ROOT = Path(__file__).resolve().parent.parent
from core.dataset import Dataset  # noqa: E402

OWL_FILE = Dataset.default()  # schema + sample data
HC = "http://example.org/healthcare-hospital.owl#"


@pytest.fixture(scope="module")
def projection():
    return build_projection(OWL_FILE)


@pytest.fixture(scope="module")
def source_graph():
    return OWL_FILE.graph()


def ttl(body: str) -> Graph:
    """A tiny valid ontology document plus the given statements."""
    g = Graph()
    g.parse(
        data="""
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix ex: <http://example.org/t#> .
        <http://example.org/t> a owl:Ontology .
        """
        + body,
        format="turtle",
    )
    return g


def node_by_name(projection, name):
    return next(n for n in projection.nodes if n.properties["name"] == name)


# ---------------------------------------------------------------------------
# Classes, hierarchy, multiple types
# ---------------------------------------------------------------------------

def test_every_rdf_class_appears_as_an_ontology_class_node(projection, source_graph):
    declared = {local_name(c) for c in source_graph.subjects(RDF.type, OWL.Class) if isinstance(c, URIRef)}
    projected = {c.properties["name"] for c in projection.classes}
    assert declared <= projected, sorted(declared - projected)
    assert len(declared) >= 55


def test_class_hierarchy_is_preserved(projection):
    pairs = {(local_name(e.source), local_name(e.target)) for e in projection.edges_of(SUBCLASS_REL)}
    for child, parent in [
        ("Doctor", "Practitioner"), ("Practitioner", "Person"), ("Patient", "Person"),
        ("Diagnosis", "Condition"), ("VitalSign", "Observation"), ("Hospital", "Organization"),
        ("Bed", "Location"), ("Specialty", "Concept"),
    ]:
        assert (child, parent) in pairs, (child, parent)


def test_individuals_carry_all_superclass_labels(projection):
    john = node_by_name(projection, "PatientJohn")
    assert {"Resource", "Patient", "Person"} == set(john.labels)
    dx = node_by_name(projection, "DiagnosisHypertension")
    assert {"Resource", "Diagnosis", "Condition"} == set(dx.labels)
    drs = node_by_name(projection, "DrSmith")
    assert {"Doctor", "Practitioner", "Person"} <= set(drs.labels)


def test_specialty_is_a_concept_node_not_a_label_on_the_doctor(projection):
    assert "Cardiologist" not in node_by_name(projection, "DrSmith").labels
    edges = [e for e in projection.edges_of("HASSPECIALTY") if e.source == HC + "DrSmith"]
    assert [e.target for e in edges] == [HC + "SpecialtyCardiology"]
    assert "Specialty" in node_by_name(projection, "SpecialtyCardiology").labels


def test_multiple_rdf_types_are_all_preserved():
    p = build_projection(ttl("""
        ex:Patient a owl:Class . ex:Practitioner a owl:Class . ex:Person a owl:Class .
        ex:Patient rdfs:subClassOf ex:Person . ex:Practitioner rdfs:subClassOf ex:Person .
        ex:nurse1 a owl:NamedIndividual, ex:Practitioner, ex:Patient .
    """))
    n = p.nodes[0]
    assert set(n.labels) == {"Resource", "Patient", "Practitioner", "Person"}
    assert n.properties["rdfTypes"] == [
        "http://example.org/t#Patient", "http://example.org/t#Practitioner",
    ]
    assert len([e for e in p.edges if e.rel_type == INSTANCE_REL and e.source == n.iri]) == 2


def test_asserted_types_stay_distinguishable_from_inherited_labels(projection):
    john = node_by_name(projection, "PatientJohn")
    assert john.properties["rdfTypes"] == [HC + "Patient"]  # Person is inherited, not asserted


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def test_node_identity_is_the_iri_not_the_name(projection):
    iris = [n.iri for n in projection.nodes]
    assert len(iris) == len(set(iris))
    john = node_by_name(projection, "PatientJohn")
    assert john.iri == HC + "PatientJohn"
    assert john.properties["iri"] == john.iri
    assert john.properties["name"] == "PatientJohn"  # display / query convenience only


def test_same_name_in_two_namespaces_stays_two_nodes():
    g = ttl("""
        ex:Person a owl:Class .
        <http://a.example.org/id#john> a owl:NamedIndividual, ex:Person .
        <http://b.example.org/id#john> a owl:NamedIndividual, ex:Person .
    """)
    p = build_projection(g)
    assert len(p.nodes) == 2
    assert {n.properties["name"] for n in p.nodes} == {"john"}
    assert len({n.iri for n in p.nodes}) == 2


def test_relationships_connect_by_iri_with_explicit_labels(projection):
    for e in projection.edges:
        assert e.source_label in ("Resource", "OntologyClass")
        assert e.target_label in ("Resource", "OntologyClass")
    stmts = [s.cypher for s in write_statements(projection) if "CREATE (a)-[" in s.cypher]
    assert stmts and all("MATCH (a:" in s and "MATCH (b:" in s for s in stmts)
    assert not any(re.search(r"MATCH \(a \{", s) for s in stmts)  # the old label-less match


# ---------------------------------------------------------------------------
# Relationships and properties
# ---------------------------------------------------------------------------

def test_every_asserted_relationship_between_individuals_is_projected(projection, source_graph):
    names = {URIRef(n.iri) for n in projection.nodes}
    declared = set(source_graph.subjects(RDF.type, OWL.ObjectProperty))
    expected = {
        (str(s), local_name(p).upper(), str(o))
        for s, p, o in source_graph
        if p in declared and s in names and o in names
    }
    got = {(e.source, e.rel_type, e.target) for e in projection.edges if not e.inferred}
    assert expected <= got, sorted(expected - got)[:5]
    assert len(expected) > 150


def test_multi_valued_relationships_keep_every_value(projection):
    cats = {local_name(e.target) for e in projection.edges_of("MEDICATIONCATEGORY") if e.source == HC + "Aspirin"}
    assert cats == {"MedCategoryAnalgesic", "MedCategoryAntiplatelet"}
    codes = {local_name(e.target) for e in projection.edges_of("HASCODE") if e.source == HC + "DiagnosisHypertension"}
    assert codes == {"Icd10_I10", "Snomed_38341003"}


def test_non_functional_property_is_a_complete_sorted_list_functional_is_scalar():
    p = build_projection(ttl("""
        ex:phone a owl:DatatypeProperty . ex:age a owl:DatatypeProperty, owl:FunctionalProperty .
        ex:P a owl:Class .
        ex:a a owl:NamedIndividual, ex:P ; ex:phone "300", "100", "200" ; ex:age 41 .
    """))
    props = p.nodes[0].properties
    assert props["phone"] == ["100", "200", "300"]
    assert props["age"] == 41


def test_functional_property_with_two_values_is_rejected():
    with pytest.raises(ProjectionError, match="functional"):
        build_projection(ttl("""
            ex:age a owl:DatatypeProperty, owl:FunctionalProperty . ex:P a owl:Class .
            ex:a a owl:NamedIndividual, ex:P ; ex:age 41, 42 .
        """))


def test_values_keep_native_types(projection):
    john = node_by_name(projection, "PatientJohn").properties
    assert john["dateOfBirth"] == datetime.date(1985, 3, 14)
    enc = node_by_name(projection, "Encounter001").properties
    assert isinstance(enc["encounterStart"], datetime.datetime) and enc["encounterStart"].tzinfo is not None
    bp = node_by_name(projection, "Observation001").properties
    assert bp["observationValue"] == 152.0 and isinstance(bp["observationValue"], float)
    assert node_by_name(projection, "Icd10_I10").properties["codeSystem"] == "http://hl7.org/fhir/sid/icd-10"


def test_vocabulary_metadata_is_kept(projection):
    c = node_by_name(projection, "SpecialtyCardiology").properties
    assert c["prefLabel"] == ["Cardiology"] and c["label"] == ["Cardiology"]
    assert any(e.rel_type == "INSCHEME" and e.source == HC + "SpecialtyCardiology" for e in projection.edges)
    klass = next(c for c in projection.classes if c.properties["name"] == "Encounter").properties
    assert klass["comment"] and klass["label"] == ["Encounter"]


def test_defined_classes_are_flagged_and_their_limits_reported(projection):
    flagged = {c.properties["name"] for c in projection.classes if c.properties.get("definedClass")}
    assert flagged == {"AntidiabeticMedication", "InpatientEncounter"}
    assert any("equivalentClass" in note for note in projection.notes)


def test_entailed_inverse_and_superproperty_edges_are_present_and_marked(projection):
    inferred = {(e.rel_type) for e in projection.edges if e.inferred}
    assert {"DIAGNOSISFORPATIENT", "HASCONDITION", "ENCOUNTERFORPATIENT", "LOCATEDINROOM"} <= inferred
    asserted = {e.rel_type for e in projection.edges if not e.inferred}
    assert "HASDIAGNOSIS" in asserted and "HASDIAGNOSIS" not in inferred
    # an entailed edge never duplicates an asserted one
    keys = [(e.source, e.rel_type, e.target) for e in projection.edges]
    assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_repeated_projection_is_identical(projection):
    again = build_projection(OWL_FILE)
    assert again.fingerprint() == projection.fingerprint()
    assert again.canonical() == projection.canonical()


def test_projection_does_not_depend_on_triple_order(source_graph, projection):
    shuffled = Graph()
    for triple in reversed(sorted(source_graph, key=lambda t: tuple(map(str, t)))):
        shuffled.add(triple)
    assert build_projection(shuffled).fingerprint() == projection.fingerprint()


def test_statement_plan_is_identical_across_runs(projection):
    a = [(s.cypher, s.params) for s in write_statements(build_projection(OWL_FILE))]
    b = [(s.cypher, s.params) for s in write_statements(projection)]
    assert a == b


def test_projection_changes_when_the_rdf_changes(source_graph, projection):
    altered = Graph()
    for t in source_graph:
        altered.add(t)
    altered.remove((URIRef(HC + "PatientJohn"), URIRef(HC + "bloodGroup"), None))
    assert build_projection(altered).fingerprint() != projection.fingerprint()


# ---------------------------------------------------------------------------
# Invalid RDF is rejected, not half-loaded
# ---------------------------------------------------------------------------

def test_unparseable_file_is_rejected(tmp_path):
    bad = tmp_path / "broken.owl"
    bad.write_text("<rdf:RDF this is not xml", encoding="utf-8")
    with pytest.raises(ProjectionError, match="cannot parse"):
        build_projection(bad)


def test_missing_file_and_unknown_extension_are_rejected(tmp_path):
    with pytest.raises(ProjectionError, match="not found"):
        build_projection(tmp_path / "nope.owl")
    other = tmp_path / "data.csv"
    other.write_text("a,b", encoding="utf-8")
    with pytest.raises(ProjectionError, match="unsupported"):
        load_graph(other)


def test_empty_graph_is_rejected():
    with pytest.raises(ProjectionError, match="empty"):
        build_projection(Graph())


def test_document_without_ontology_header_is_rejected():
    g = Graph().parse(data="@prefix ex: <http://example.org/t#> . ex:a ex:b ex:c .", format="turtle")
    with pytest.raises(ProjectionError, match="owl:Ontology"):
        build_projection(g)


def test_dangling_object_property_target_is_rejected():
    with pytest.raises(ProjectionError, match="not defined"):
        build_projection(ttl("""
            ex:P a owl:Class . ex:knows a owl:ObjectProperty .
            ex:a a owl:NamedIndividual, ex:P ; ex:knows ex:ghost .
        """))


def test_unsafe_names_cannot_reach_cypher():
    with pytest.raises(ProjectionError, match="safe identifier"):
        build_projection(ttl("""
            <http://example.org/t#Evil`) DETACH DELETE n //> a owl:Class .
            ex:a a owl:NamedIndividual .
        """.replace("`", "%60")))


def test_mixed_datatypes_in_one_property_are_rejected():
    with pytest.raises(ProjectionError, match="homogeneous"):
        build_projection(ttl("""
            ex:P a owl:Class . ex:v a owl:DatatypeProperty .
            ex:a a owl:NamedIndividual, ex:P ; ex:v "text", 7 .
        """))


def test_two_classes_with_the_same_local_name_are_rejected():
    with pytest.raises(ProjectionError, match="share the local name"):
        build_projection(ttl("""
            <http://a.example.org/x#Thing1> a owl:Class . <http://b.example.org/x#Thing1> a owl:Class .
        """))


def test_all_problems_are_reported_together():
    with pytest.raises(ProjectionError) as info:
        build_projection(ttl("""
            ex:P a owl:Class . ex:knows a owl:ObjectProperty .
            ex:age a owl:DatatypeProperty, owl:FunctionalProperty .
            ex:a a owl:NamedIndividual, ex:P ; ex:knows ex:ghost ; ex:age 1, 2 .
        """))
    assert len(info.value.problems) == 2


# ---------------------------------------------------------------------------
# Statements are parameterized and scoped
# ---------------------------------------------------------------------------

def test_values_never_appear_in_cypher_text(projection):
    statements = write_statements(projection)
    text = "\n".join(s.cypher for s in statements)
    for needle in ("PatientJohn", "Hypertension", "1985-03-14", HC):
        assert needle not in text
    assert any("PatientJohn" in str(s.params) for s in statements)


def test_every_delete_is_scoped_to_projection_labels(projection):
    for st in write_statements(projection) + reset_statements():
        if "DELETE" in st.cypher:
            assert re.search(r":(Resource|OntologyClass|ProjectionMeta)\b", st.cypher), st.cypher
            assert not re.search(r"MATCH \(\w*\)\s*(WHERE [^D]*)?DETACH DELETE", st.cypher), st.cypher
    assert all(not s.cypher.startswith("MATCH (n) ") for s in reset_statements())


def test_schema_declares_iri_uniqueness():
    ddl = "\n".join(schema_statements())
    assert "REQUIRE n.iri IS UNIQUE" in ddl and "Resource" in ddl and "OntologyClass" in ddl


def test_cypher_literals_are_escaped():
    assert cypher_literal('he said "hi"\n') == '"he said \\"hi\\"\\n"'
    assert cypher_literal(True) == "true"
    assert cypher_literal(datetime.date(2026, 3, 1)) == 'date("2026-03-01")'
    assert cypher_literal(["a", 2]) == '["a", 2]'


def test_cypher_script_is_idempotent_merge_only(projection):
    script = to_cypher_script(projection)
    assert script and all(s.startswith(("MERGE", "MATCH")) for s in script)
    assert not any("DELETE" in s for s in script)
    assert not any("CREATE " in s for s in script)


def test_ontology_class_names_never_collide_with_other_graph_domains(projection):
    """A class named like an application label would silently merge two kinds of state.

    The ontology class `Procedure` once collided with agent procedural memory's `:Procedure`
    label; memory now uses `:AgentProcedure`.
    """
    from core import graph_domains

    other = set(
        graph_domains.SEMANTIC_INDEX_LABELS + graph_domains.APPLICATION_LABELS + graph_domains.AGENT_MEMORY_LABELS
    )
    labels = {label for n in projection.nodes for label in n.labels}
    assert not (labels & other), sorted(labels & other)
    assert "Procedure" in labels  # the domain class is intact


def test_single_valued_attributes_project_as_scalars_and_contact_data_as_lists(projection):
    for node in projection.nodes:
        for key in ("firstName", "diagnosisName", "medicationName", "hospitalName", "bloodGroup"):
            if key in node.properties:
                assert not isinstance(node.properties[key], list), (node.iri, key)
    from services.graph_projection import build_projection as bp

    g = ttl("""
        ex:phoneNumber a owl:DatatypeProperty . ex:P a owl:Class .
        ex:a a owl:NamedIndividual, ex:P ; ex:phoneNumber "1" .
    """)
    assert bp(g).nodes[0].properties["phoneNumber"] == ["1"]  # a lone value of a non-functional property is still a list
