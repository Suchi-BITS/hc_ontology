"""A guided tour of the system. Works offline: no Docker, no Neo4j, no API keys.

    python scripts/demo.py             # RDF/OWL/SHACL/SPARQL/projection tour
    python scripts/demo.py --neo4j     # also load Neo4j and query it (needs Neo4j running: your Neo4j Desktop database, or `dev.py up` for Docker)

The tour shows the architecture's one rule: RDF/OWL/SHACL is the authority, Neo4j is derived from it.
"""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HC = "http://example.org/healthcare-hospital.owl#"


def title(text: str) -> None:
    print(f"\n{'=' * 78}\n{text}\n{'=' * 78}")


def local(term) -> str:
    return str(term).split("#")[-1]


def show(rows, header=None, limit=8) -> None:
    rows = list(rows)
    if header:
        print("   " + " | ".join(header))
    for row in rows[:limit]:
        print("   " + " | ".join(str(c) for c in row))
    if len(rows) > limit:
        print(f"   ... {len(rows) - limit} more")
    if not rows:
        print("   (no rows)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--neo4j", action="store_true", help="also load Neo4j and run Cypher against it")
    args = parser.parse_args()

    import rdflib
    from rdflib import OWL, RDF, XSD, Literal, Namespace

    from core.dependencies import get_shacl_validator
    from services.graph_projection import build_projection

    hc = Namespace(HC)
    from core.dataset import Dataset

    dataset = Dataset.default()
    graph = dataset.graph()
    validator = get_shacl_validator()

    title("1. The authoritative model: RDF / OWL")
    print(f"   {dataset.label}: {len(graph)} triples")
    print(f"   {len(set(graph.subjects(RDF.type, OWL.Class)))} classes, "
          f"{len(set(graph.subjects(RDF.type, OWL.ObjectProperty)))} object properties, "
          f"{len(set(graph.subjects(RDF.type, OWL.DatatypeProperty)))} datatype properties, "
          f"{len(set(graph.subjects(RDF.type, OWL.NamedIndividual)))} individuals")
    print("   Specialty is a property, not a subclass; Metformin is a plain Medication with a category:")
    show([(local(d), local(s)) for d, s in graph.query(
        f"SELECT ?d ?s WHERE {{ ?d a <{HC}Doctor> ; <{HC}hasSpecialty> ?s }} ORDER BY ?d")], ["doctor", "specialty"])

    title("2. Validation: SHACL decides what valid data is")
    result = validator.validate_graph(graph, data_source="sample")
    s = result.summary
    print(f"   conforms={s.conforms}  violations={s.violation_count}  warnings={s.warning_count}  infos={s.info_count}")

    broken = rdflib.Graph()
    for t in graph:
        broken.add(t)
    broken.remove((hc.PatientJohn, hc.dateOfBirth, None))
    broken.add((hc.PrescriptionDiabetesBob, hc.containsMedication, hc.Amoxicillin))  # Bob is allergic to it
    bad = validator.validate_graph(broken, data_source="deliberately broken copy")
    print("   Now break a copy on purpose (remove John's birth date; prescribe Bob an allergen):")
    for v in [v for v in bad.violations if v.severity == "Violation"]:
        print(f"   VIOLATION  {local(v.focus_node)}: {v.message}")

    title("3. Competency questions: SPARQL over the same RDF")
    queries = [
        ("cq03_patient_conditions", "Which diagnoses does each patient have?", None),
        ("cq11_patients_on_antidiabetics", "Which patients take an antidiabetic medication?", None),
        ("cq13_diagnoses_per_doctor", "How many diagnoses has each doctor made?", None),
        ("cq14_all_persons", "Who is a Person? (subclass path, no reasoner)", None),
        ("cq15_unfulfilled_appointments", "Which appointments have no encounter yet?", None),
    ]
    for name, question, _ in queries:
        text = (ROOT / "sparql" / f"{name}.rq").read_text(encoding="utf-8")
        rows = [tuple(local(x) if isinstance(x, rdflib.URIRef) else x.toPython() for x in r) for r in graph.query(text)]
        print(f"\n   {question}   [{name}.rq]")
        show(rows, limit=5)

    title("4. Derived projection: RDF to a property graph (no database needed)")
    projection = build_projection(graph)
    info = projection.summary()
    print(f"   {info['nodes']} nodes, {info['classes']} class nodes, {info['relationships']} relationships; "
          f"fingerprint {info['fingerprint'][:16]}...")
    john = next(n for n in projection.nodes if n.properties["name"] == "PatientJohn")
    print(f"   PatientJohn labels: {', '.join(john.labels)}   (superclass Person is inherited)")
    print(f"   identity (iri): {john.iri}")
    dx = next(n for n in projection.nodes if n.properties["name"] == "DiagnosisHypertension")
    codes = [projection.node(e.target).properties["codeValue"] for e in projection.edges_of("HASCODE") if e.source == dx.iri]
    print(f"   DiagnosisHypertension has {len(codes)} codes preserved: {', '.join(sorted(codes))}")

    if not args.neo4j:
        print("\n   To load this into Neo4j (start your Neo4j Desktop database first, or `dev.py up` for Docker):  python scripts/dev.py load  &&  "
              "python scripts/dev.py demo --neo4j")
        print("\nDemo finished.")
        return 0

    title("5. Neo4j: the same graph, queried with Cypher")
    from core.config import get_settings
    from services.neo4j_exporter import Neo4jExporter

    settings = get_settings()
    uri = urlparse(settings["neo4j_uri"])
    try:
        with socket.create_connection((uri.hostname or "localhost", uri.port or 7687), timeout=2):
            pass
    except OSError:
        print(f"   Neo4j is not reachable at {uri.hostname}:{uri.port or 7687}. Start your Neo4j Desktop database (or `python scripts/dev.py up` for Docker).")
        return 1
    exporter = Neo4jExporter(validator=validator)
    try:
        result = exporter.sync()
        print(f"   Synchronized: {result['nodes']} nodes, {result['classes']} classes, "
              f"{result['relationships']} relationships (SHACL-gated, scoped to the projection)")
        cypher = [
            ("Patients with a Condition (superclass label)", "MATCH (p:Patient)-[:HASCONDITION]->(c:Condition) RETURN p.name AS patient, c.diagnosisName AS condition ORDER BY patient"),
            ("Doctors and specialties", "MATCH (d:Doctor)-[:HASSPECIALTY]->(s:Specialty) RETURN d.name AS doctor, s.name AS specialty ORDER BY doctor"),
        ]
        with exporter.driver.session(database=exporter.database) as session:
            for label, query in cypher:
                print(f"\n   {label}\n   {query}")
                show([tuple(r.values()) for r in session.run(query)], limit=5)
    finally:
        exporter.close()
    print("\nDemo finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
