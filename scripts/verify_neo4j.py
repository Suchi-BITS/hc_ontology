"""Verify a LIVE Neo4j database (for example one run by Neo4j Desktop). Read-only; never prints the password.

    python scripts/verify_neo4j.py                 # connectivity, database, version, totals
    python scripts/verify_neo4j.py --projection    # also compare the database with the RDF projection
    python scripts/verify_neo4j.py --census        # also list labels and relationship types

Uses the application's own configuration (core/config.py): NEO4J_URI, NEO4J_USERNAME (or NEO4J_USER),
NEO4J_PASSWORD, NEO4J_DATABASE. Exits 0 on PASS, 1 on FAIL, 2 when Neo4j is not reachable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--projection", action="store_true", help="compare nodes, labels, properties and relationships with the RDF projection")
    parser.add_argument("--census", action="store_true", help="list node labels and relationship types")
    args = parser.parse_args()

    from core.config import get_settings, require_neo4j_password

    s = get_settings()
    print("Neo4j verification")
    print("------------------")
    print(f"URI: {s['neo4j_uri']}")
    print(f"User: {s['neo4j_username']}")
    print(f"Database: {s['neo4j_database']}")
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            s["neo4j_uri"], auth=(s["neo4j_username"], require_neo4j_password()),
            connection_timeout=8, connection_acquisition_timeout=8, max_transaction_retry_time=2,
        )
    except RuntimeError as exc:  # missing password
        print(f"Result: FAIL ({exc})")
        return 2
    from services.neo4j_verify import census, compare_projection, connection_report

    try:
        report = connection_report(driver, s["neo4j_database"])
    except Exception as exc:  # noqa: BLE001 - the driver raises several types
        message = str(exc).replace(s["neo4j_password"] or "\0", "***")
        print(f"Status: UNREACHABLE ({type(exc).__name__}: {message[:200]})")
        print("Neo4j is not running or is not reachable. Start your Neo4j Desktop database, then check NEO4J_URI,")
        print("NEO4J_USERNAME and NEO4J_PASSWORD in .env. (Nothing was created or changed.)")
        print("Result: FAIL")
        return 2

    print(f"Server: {report['server_address']}  ({report['agent']})")
    print(f"Status: {report['status'].upper()}")
    if report["problems"]:
        for problem in report["problems"]:
            print(f"Problem: {problem}")
        print("Result: FAIL")
        return 1
    print(f"Neo4j version: {report['version']} ({report['edition']})")
    print(f"Nodes: {report['nodes']}")
    print(f"Relationships: {report['relationships']}")
    print("Graph domains (by label): " + ", ".join(f"{k}={v}" for k, v in sorted(report["domains"].items())) if report["domains"] else "Graph domains: (empty)")
    problems: list[str] = []
    if report["domains"].get("other"):
        print(f"Note: {report['domains']['other']} node(s) belong to no known graph domain (for example nodes written by an "
              "older exporter). They are not part of the projection and are never modified by it.")

    if args.census:
        data = census(driver, s["neo4j_database"])
        print("Labels: " + ", ".join(f"{k}={v}" for k, v in data["labels"].items()))
        print("Relationship types: " + ", ".join(f"{k}={v}" for k, v in data["relationship_types"].items()))

    if args.projection:
        from core.dataset import Dataset
        from services.graph_projection import build_projection

        projection = build_projection(Dataset.default())
        result = compare_projection(driver, s["neo4j_database"], projection)
        print(f"Projection check: nodes {result['live_nodes']}/{result['expected_nodes']}, classes {result['live_classes']}/{result['expected_classes']}, "
              f"relationships {result['live_relationships']}/{result['expected_relationships']}, "
              f"label mismatches {result['label_mismatches']}, property mismatches {result['property_mismatches']}")
        problems += result["problems"]
        for problem in result["problems"]:
            print(f"Problem: {problem}")

    driver.close()
    print(f"Result: {'FAIL' if problems else 'PASS'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
