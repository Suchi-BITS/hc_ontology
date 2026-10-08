"""Development helper: synchronize the Neo4j projection from the authoritative RDF.

Usage (from the hc_ontology directory):

    python scripts/seed_neo4j_demo.py --yes                       # sync projection + bootstrap procedures
    python scripts/seed_neo4j_demo.py --yes --reset-projection    # first remove the projection (dev only)

What this does NOT do: edit the ontology, clear the database, or touch agent memory,
documents or embeddings. ``--reset-projection`` removes only the RDF projection labels
(Resource, OntologyClass, ProjectionMeta) and is refused unless ENVIRONMENT is a
development value and ALLOW_PROJECTION_RESET=true.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="confirm that you want to write to Neo4j")
    parser.add_argument("--reset-projection", action="store_true", help="remove the projection first (development only)")
    args = parser.parse_args()
    if not args.yes:
        parser.error("refusing to run without --yes")

    from core.graph_domains import ResetNotAllowed, require_demo_allowed
    from services.graph_projection import ProjectionError
    from services.neo4j_exporter import Neo4jExporter
    from services.seed_demo_data import seed_demo_ontology_and_neo4j

    try:
        require_demo_allowed()
        if args.reset_projection:
            exporter = Neo4jExporter()
            try:
                print(exporter.reset_projection())
            finally:
                exporter.close()
        print(seed_demo_ontology_and_neo4j())
    except (ResetNotAllowed, ProjectionError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
