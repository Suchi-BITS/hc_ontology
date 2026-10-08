"""Neo4j writer for the RDF projection.

RDF/OWL/SHACL is the semantic authority; Neo4j is a derived operational view.
This module is the ONLY path from the ontology into the clinical Neo4j layer:

    healthcare_schema.ttl + sample_data.ttl -> [SHACL gate] -> graph_projection.build_projection()
                            -> Statement list -> Neo4j (one write transaction)

Guarantees:

* Deterministic and idempotent: the same RDF always produces the same logical graph;
  running it twice changes nothing.
* One-way: nothing is ever read back from Neo4j into RDF.
* Scoped: it only creates, updates and deletes nodes labelled ``Resource``,
  ``OntologyClass`` or ``ProjectionMeta``. Agent memory, documents and embeddings are
  other labels and are never touched (see core/graph_domains.py).
* Safe by construction: values travel as query parameters; labels and relationship
  types come from the validated ontology, never from request input.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import get_settings, require_neo4j_password
from core.graph_domains import (
    AGENT_MEMORY_LABELS,
    APPLICATION_LABELS,
    PROJECTION_LABELS,
    SEMANTIC_INDEX_LABELS,
    require_reset_allowed,
)
from services.graph_projection import (
    CLASS_LABEL,
    RESOURCE_LABEL,
    Projection,
    ProjectionError,
    build_projection,
    load_graph,
)

logger = logging.getLogger("healthcare_ontology.projection")

PROJECTION_ID = "hc-core"
META_LABEL = "ProjectionMeta"


class ProjectionRejected(ProjectionError):
    """The RDF violates the SHACL shapes, so it is not loaded into the projection."""


class ForeignDataPresent(ProjectionError):
    """The target database already holds nodes that belong to none of this project's graph domains.

    Typical case: a database filled by an older exporter (name-keyed nodes with labels such as Patient but no IRI).
    Projecting into it would put two different representations of the same entities side by side, so a query for
    `(:Patient)` would return both. Nothing is written; point NEO4J_DATABASE at an empty database, or pass
    allow_foreign=True (load_graph.py --allow-foreign-data) if the mixing is intended.
    """


@dataclass(frozen=True)
class Statement:
    cypher: str
    params: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Statement planning (pure; unit-tested without Neo4j)
# ---------------------------------------------------------------------------

def schema_statements() -> list[str]:
    """Uniqueness on the IRI (the identity) and a lookup index on the display name."""
    return [
        f"CREATE CONSTRAINT resource_iri IF NOT EXISTS FOR (n:{RESOURCE_LABEL}) REQUIRE n.iri IS UNIQUE",
        f"CREATE CONSTRAINT ontology_class_iri IF NOT EXISTS FOR (n:{CLASS_LABEL}) REQUIRE n.iri IS UNIQUE",
        f"CREATE CONSTRAINT projection_meta_id IF NOT EXISTS FOR (n:{META_LABEL}) REQUIRE n.id IS UNIQUE",
        f"CREATE INDEX resource_name IF NOT EXISTS FOR (n:{RESOURCE_LABEL}) ON (n.name)",
    ]


def write_statements(projection: Projection, *, meta: dict[str, Any] | None = None) -> list[Statement]:
    """All statements that make Neo4j equal to the projection, in execution order."""
    out: list[Statement] = []

    # 1. class nodes
    if projection.classes:
        out.append(
            Statement(
                f"UNWIND $rows AS row MERGE (c:{CLASS_LABEL} {{iri: row.iri}}) SET c = row.props",
                {"rows": [{"iri": c.iri, "props": c.properties} for c in projection.classes]},
            )
        )

    # 2. individual nodes, grouped by label set so labels can be written literally
    all_class_labels = projection.class_labels
    remove_clause = f"REMOVE n:{':'.join(all_class_labels)} " if all_class_labels else ""
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for node in projection.nodes:
        groups.setdefault(node.labels, []).append({"iri": node.iri, "props": node.properties})
    for labels in sorted(groups):
        out.append(
            Statement(
                f"UNWIND $rows AS row MERGE (n:{RESOURCE_LABEL} {{iri: row.iri}}) "
                f"{remove_clause}SET n:{':'.join(labels)} SET n = row.props",
                {"rows": groups[labels]},
            )
        )

    # 3. relationships among projection nodes are rebuilt (never relationships to other domains)
    out.append(
        Statement(
            f"MATCH (a)-[r]->(b) WHERE (a:{RESOURCE_LABEL} OR a:{CLASS_LABEL}) "
            f"AND (b:{RESOURCE_LABEL} OR b:{CLASS_LABEL}) DELETE r"
        )
    )
    edge_groups: dict[tuple[str, str, str, bool], list[dict[str, str]]] = {}
    for e in projection.edges:
        edge_groups.setdefault((e.rel_type, e.source_label, e.target_label, e.inferred), []).append(
            {"s": e.source, "t": e.target}
        )
    for (rel, src_label, tgt_label, inferred) in sorted(edge_groups):
        flag = " SET r.inferred = true" if inferred else ""
        out.append(
            Statement(
                f"UNWIND $rows AS row MATCH (a:{src_label} {{iri: row.s}}) MATCH (b:{tgt_label} {{iri: row.t}}) "
                f"CREATE (a)-[r:{rel}]->(b){flag}",
                {"rows": edge_groups[(rel, src_label, tgt_label, inferred)]},
            )
        )

    # 4. prune projection nodes that no longer exist in the RDF
    out.append(
        Statement(
            f"MATCH (n:{RESOURCE_LABEL}) WHERE NOT n.iri IN $iris DETACH DELETE n",
            {"iris": [n.iri for n in projection.nodes]},
        )
    )
    out.append(
        Statement(
            f"MATCH (n:{CLASS_LABEL}) WHERE NOT n.iri IN $iris DETACH DELETE n",
            {"iris": [c.iri for c in projection.classes]},
        )
    )

    # 5. operational metadata about the last synchronization
    out.append(
        Statement(
            f"MERGE (m:{META_LABEL} {{id: $id}}) SET m = $meta",
            {"id": PROJECTION_ID, "meta": {"id": PROJECTION_ID, **(meta or {})}},
        )
    )
    return out


def reset_statements() -> list[Statement]:
    """Remove ONLY the projection. Anything with another label is out of reach."""
    return [Statement(f"MATCH (n:{label}) DETACH DELETE n") for label in PROJECTION_LABELS]


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------

class Neo4jExporter:
    """Synchronizes the Neo4j projection from the authoritative RDF file."""

    def __init__(self, owl_file: str | Path | None = None, *, driver=None, database: str | None = None, validator=None):
        from core.dataset import as_dataset

        settings = get_settings()
        self.dataset = as_dataset(owl_file)  # schema + sample data, or one RDF file
        self.owl_file = self.dataset
        self.database = database or settings["neo4j_database"]
        self._driver = driver
        self._validator = validator

    # ---- planning (no database) -----------------------------------------
    def plan(self, *, validate: bool = True) -> Projection:
        """Load the RDF, gate it through SHACL, and build the projection. Touches no database."""
        from core.dataset import DatasetError

        try:
            graph = self.dataset.graph()
        except DatasetError as exc:
            raise ProjectionError([str(exc)]) from exc
        if validate:
            self._gate(graph)
        return build_projection(graph)

    def _gate(self, graph) -> None:
        validator = self._validator
        if validator is None:
            from core.dependencies import get_shacl_validator

            validator = get_shacl_validator()
        result = validator.validate_graph(graph, data_source=self.dataset.label)
        violations = [v for v in result.violations if v.severity == "Violation"]
        if violations:
            raise ProjectionRejected(
                f"{v.focus_node.rsplit('#', 1)[-1]}: {v.message}" for v in violations[:20]
            )

    # ---- database -------------------------------------------------------
    @property
    def driver(self):
        if self._driver is None:
            from neo4j import GraphDatabase  # only writing needs the driver; planning and validation do not

            s = get_settings()
            self._driver = GraphDatabase.driver(
                s["neo4j_uri"], auth=(s["neo4j_username"], require_neo4j_password())
            )
        return self._driver

    def sync(self, *, validate: bool = True, allow_foreign: bool = False) -> dict[str, Any]:
        """Make Neo4j's projection equal to the RDF. Idempotent. Scoped to the projection labels."""
        projection = self.plan(validate=validate)
        return self.apply(projection, validated=validate, allow_foreign=allow_foreign)

    export = sync  # backwards-compatible name used by routers/scripts

    def foreign_nodes(self) -> dict[str, Any]:
        """Read-only: nodes in the target database whose labels belong to no known graph domain."""
        known = list(PROJECTION_LABELS) + list(SEMANTIC_INDEX_LABELS) + list(APPLICATION_LABELS) + list(AGENT_MEMORY_LABELS)
        with self.driver.session(database=self.database) as session:
            row = session.run(
                "MATCH (n) WHERE none(l IN labels(n) WHERE l IN $known) "
                "RETURN count(n) AS c, collect(DISTINCT labels(n))[..5] AS sample",
                known=known,
            ).single()
        return {"count": int(row.get("c", 0) or 0), "sample": list(row.get("sample") or [])}

    def apply(self, projection: Projection, *, validated: bool = True, allow_foreign: bool = False) -> dict[str, Any]:
        if not allow_foreign:
            foreign = self.foreign_nodes()
            if foreign["count"]:
                raise ForeignDataPresent([
                    f"database '{self.database}' already holds {foreign['count']} node(s) outside this project's graph domains "
                    f"(label sets such as {foreign['sample']}). Loading would mix two representations of the same entities. "
                    "Use an empty database (NEO4J_DATABASE), or pass allow_foreign=True / --allow-foreign-data if you intend it. "
                    "Nothing was written."
                ])
        meta = {
            "fingerprint": projection.fingerprint(),
            "source": self.dataset.label,
            "nodes": len(projection.nodes),
            "classes": len(projection.classes),
            "relationships": len(projection.edges),
            "shaclValidated": validated,
            "syncedAt": datetime.now(timezone.utc).isoformat(),
        }
        statements = write_statements(projection, meta=meta)
        with self.driver.session(database=self.database) as session:
            for ddl in schema_statements():
                session.run(ddl)

            def work(tx):
                for st in statements:
                    tx.run(st.cypher, **st.params)

            session.execute_write(work)
        logger.info("Projection synchronized: %s", {k: meta[k] for k in ("nodes", "classes", "relationships")})
        return {
            "status": "success",
            "database": self.database,
            "scope": list(PROJECTION_LABELS),
            "nodes": meta["nodes"],
            "classes": meta["classes"],
            "relationships": meta["relationships"],
            "fingerprint": meta["fingerprint"],
            "shacl_validated": validated,
            "not_projected": projection.notes,
        }

    def reset_projection(self) -> dict[str, Any]:
        """Development only: remove the projection (and nothing else). Refused in production."""
        require_reset_allowed()
        with self.driver.session(database=self.database) as session:

            def work(tx):
                for st in reset_statements():
                    tx.run(st.cypher, **st.params)

            session.execute_write(work)
        return {"status": "projection removed", "scope": list(PROJECTION_LABELS), "database": self.database}

    def summary(self) -> dict[str, Any]:
        """Counts for the projection only (other domains are reported by their own services)."""
        counts: dict[str, int] = {}
        with self.driver.session(database=self.database) as session:
            for label in PROJECTION_LABELS:
                counts[label] = session.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"]
        return {"database": self.database, **counts}

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None
