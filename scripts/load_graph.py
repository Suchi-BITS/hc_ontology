"""Load the ontology and data into Neo4j as a derived projection.

    python scripts/load_graph.py --dry-run        # plan only: no database needed
    python scripts/load_graph.py                  # synchronize Neo4j from the RDF
    python scripts/load_graph.py --wait 90        # wait up to 90 s for Neo4j to accept connections
    python scripts/load_graph.py --verify         # after loading, count what is in Neo4j and compare

RDF/OWL/SHACL is the authority; Neo4j is rebuilt from it. The load is SHACL-gated, idempotent and
scoped to the projection labels (it never touches agent memory, documents or embeddings).
Needs NEO4J_PASSWORD (see .env.example). Does not need an OpenAI key.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def wait_for_neo4j(exporter, seconds: int) -> None:
    deadline = time.monotonic() + seconds
    last = None
    while True:
        try:
            exporter.driver.verify_connectivity()
            return
        except Exception as exc:  # driver raises several types while the server boots
            last = exc
            if time.monotonic() >= deadline:
                raise SystemExit(
                    f"Neo4j is not reachable after {seconds}s: {last}\n"
                    "Start your Neo4j Desktop database (or `python scripts/dev.py up` for the optional Docker one) and check NEO4J_URI / NEO4J_PASSWORD in .env."
                )
            time.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="validate and plan only; do not touch Neo4j")
    parser.add_argument("--wait", type=int, default=0, metavar="SECONDS", help="wait for Neo4j to become reachable")
    parser.add_argument("--verify", action="store_true", help="count nodes and relationships in Neo4j afterwards")
    parser.add_argument("--allow-foreign-data", action="store_true",
                        help="load even if the database already holds nodes from other graph domains (default: refuse)")
    args = parser.parse_args()

    from core.config import get_settings
    from core.dependencies import get_shacl_validator
    from services.graph_projection import ProjectionError
    from services.neo4j_exporter import ForeignDataPresent, Neo4jExporter

    exporter = Neo4jExporter(validator=get_shacl_validator())  # the configured dataset: schema + sample data
    try:
        projection = exporter.plan()
    except ProjectionError as exc:
        print(f"REJECTED (nothing was loaded): {exc}")
        for problem in exc.problems:
            print(f"  - {problem}")
        return 2
    info = projection.summary()
    print(f"Plan: {info['nodes']} nodes, {info['classes']} classes, {info['relationships']} relationships "
          f"(fingerprint {info['fingerprint'][:16]}...)")
    if args.dry_run:
        print("Dry run: Neo4j was not contacted.")
        return 0

    try:
        if args.wait:
            wait_for_neo4j(exporter, args.wait)
        result = exporter.apply(projection, allow_foreign=args.allow_foreign_data)
    except ForeignDataPresent as exc:
        print("REFUSED (nothing was written):")
        for problem in exc.problems:
            print(f"  - {problem}")
        return 2
    except RuntimeError as exc:  # missing NEO4J_PASSWORD
        print(f"Cannot load: {exc}")
        return 2
    print(f"Loaded into database '{result['database']}': {result['nodes']} nodes, {result['classes']} classes, "
          f"{result['relationships']} relationships")

    if args.verify:
        with exporter.driver.session(database=exporter.database) as session:
            nodes = session.run("MATCH (n:Resource) RETURN count(n) AS c").single()["c"]
            classes = session.run("MATCH (n:OntologyClass) RETURN count(n) AS c").single()["c"]
            rels = session.run(
                "MATCH (a)-[r]->(b) WHERE (a:Resource OR a:OntologyClass) AND (b:Resource OR b:OntologyClass) "
                "RETURN count(r) AS c"
            ).single()["c"]
        ok = (nodes, classes, rels) == (info["nodes"], info["classes"], info["relationships"])
        print(f"Verified in Neo4j: {nodes} nodes, {classes} classes, {rels} relationships -> {'OK' if ok else 'MISMATCH'}")
        if not ok:
            return 1
    exporter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
