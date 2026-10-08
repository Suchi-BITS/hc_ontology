"""Read-only verification of a live Neo4j database against the RDF projection.

    connection_report(driver, database)       is it reachable, online, which version, how big?
    compare_projection(driver, db, projection) does the database equal what the RDF says it should?

Everything here is read-only: sessions are opened with READ_ACCESS, and no statement can write. The functions return
plain data (and a list of problems), so the CLI (scripts/verify_neo4j.py), the dev command and the live tests all
report the same thing. No password is ever read or printed here.
"""

from __future__ import annotations

import datetime
from collections import Counter
from typing import Any

from core.graph_domains import AGENT_MEMORY_LABELS, APPLICATION_LABELS, PROJECTION_LABELS, SEMANTIC_INDEX_LABELS

RESOURCE = "Resource"
CLASS = "OntologyClass"
META = "ProjectionMeta"


def _read(driver, database, cypher, **params):
    from neo4j import READ_ACCESS

    with driver.session(database=database, default_access_mode=READ_ACCESS) as session:
        return [r.data() for r in session.run(cypher, **params)]


def domain_of(labels: list[str]) -> str:
    """Which graph domain a node belongs to, from its labels (see core/graph_domains.py)."""
    s = set(labels)
    if s & set(PROJECTION_LABELS):
        return "projection"
    if s & set(AGENT_MEMORY_LABELS):
        return "agent-memory"
    if s & set(SEMANTIC_INDEX_LABELS):
        return "semantic-index"
    if s & set(APPLICATION_LABELS):
        return "application"
    return "other"


def connection_report(driver, database: str) -> dict[str, Any]:
    """Connectivity, database availability, server version and totals. Raises on connection failure."""
    driver.verify_connectivity()
    info = driver.get_server_info()
    report: dict[str, Any] = {"server_address": str(info.address), "agent": info.agent, "database": database}
    dbs = _read(driver, "system", "SHOW DATABASES YIELD name, currentStatus, default, role")
    mine = [d for d in dbs if d["name"] == database]
    report["databases"] = [d["name"] for d in dbs]
    report["status"] = mine[0]["currentStatus"] if mine else "MISSING"
    report["problems"] = []
    if not mine:
        report["problems"].append(f"database '{database}' does not exist (databases: {report['databases']})")
        return report
    if mine[0]["currentStatus"] != "online":
        report["problems"].append(f"database '{database}' is {mine[0]['currentStatus']}, not online")
        return report
    comp = _read(driver, database, "CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition")[0]
    report["version"], report["edition"] = comp["versions"][0], comp["edition"]
    report["nodes"] = _read(driver, database, "MATCH (n) RETURN count(n) AS c")[0]["c"]
    report["relationships"] = _read(driver, database, "MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
    domains: Counter = Counter()
    for row in _read(driver, database, "MATCH (n) RETURN labels(n) AS l, count(*) AS c"):
        domains[domain_of(row["l"])] += row["c"]
    report["domains"] = dict(domains)
    return report


def census(driver, database: str) -> dict[str, Any]:
    labels = _read(driver, database, "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS count ORDER BY count DESC, label")
    types = _read(driver, database, "MATCH ()-[r]->() RETURN type(r) AS relationship_type, count(*) AS count ORDER BY count DESC, relationship_type")
    return {"labels": {r["label"]: r["count"] for r in labels}, "relationship_types": {r["relationship_type"]: r["count"] for r in types}}


# ---- comparison with the projection -------------------------------------------------------------------

def normalise(value: Any) -> Any:
    """Make Python values and Neo4j driver values comparable: temporal types become ISO strings, lists keep order."""
    if hasattr(value, "to_native"):
        value = value.to_native()
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [normalise(v) for v in value]
    if isinstance(value, float) and value == int(value):
        return float(value)
    return value


def compare_projection(driver, database: str, projection) -> dict[str, Any]:
    """Compare the live Resource/OntologyClass nodes and relationships with the projection built from the RDF."""
    problems: list[str] = []
    live_nodes = _read(driver, database, f"MATCH (n:{RESOURCE}) RETURN n.iri AS iri, labels(n) AS labels, properties(n) AS props")
    expected = {n.iri: n for n in projection.nodes}
    live_iris = [r["iri"] for r in live_nodes]
    result: dict[str, Any] = {"expected_nodes": len(expected), "live_nodes": len(live_nodes)}

    dup = [i for i, c in Counter(live_iris).items() if c > 1]
    missing = sorted(set(expected) - set(live_iris))
    extra = sorted(set(live_iris) - set(expected))
    no_iri = sum(1 for i in live_iris if not i)
    if dup:
        problems.append(f"{len(dup)} IRI(s) appear on more than one node, for example {dup[:3]}")
    if missing:
        problems.append(f"{len(missing)} projected node(s) are missing from Neo4j, for example {missing[:3]}")
    if extra:
        problems.append(f"{len(extra)} Resource node(s) are not in the RDF, for example {extra[:3]}")
    if no_iri:
        problems.append(f"{no_iri} Resource node(s) have no iri")

    label_bad, prop_bad = [], []
    for row in live_nodes:
        want = expected.get(row["iri"])
        if want is None:
            continue
        if sorted(row["labels"]) != sorted({RESOURCE, *want.labels}):
            label_bad.append((row["iri"].split("#")[-1], sorted(row["labels"]), sorted({RESOURCE, *want.labels})))
        live_props = {k: normalise(v) for k, v in row["props"].items()}
        want_props = {k: normalise(v) for k, v in want.properties.items()}
        if live_props != want_props:
            diff = sorted(k for k in set(live_props) | set(want_props) if live_props.get(k) != want_props.get(k))
            prop_bad.append((row["iri"].split("#")[-1], diff))
    if label_bad:
        problems.append(f"{len(label_bad)} node(s) carry the wrong labels, for example {label_bad[:2]}")
    if prop_bad:
        problems.append(f"{len(prop_bad)} node(s) differ in properties, for example {prop_bad[:3]}")
    result["label_mismatches"], result["property_mismatches"] = len(label_bad), len(prop_bad)

    live_classes = {r["iri"] for r in _read(driver, database, f"MATCH (c:{CLASS}) RETURN c.iri AS iri")}
    want_classes = {c.iri for c in projection.classes}
    result["expected_classes"], result["live_classes"] = len(want_classes), len(live_classes)
    if live_classes != want_classes:
        problems.append(f"class nodes differ: missing {sorted(want_classes - live_classes)[:3]}, extra {sorted(live_classes - want_classes)[:3]}")

    live_edges = Counter(
        (r["s"], r["t"], r["o"], bool(r["inf"]))
        for r in _read(
            driver, database,
            f"MATCH (a)-[r]->(b) WHERE (a:{RESOURCE} OR a:{CLASS}) AND (b:{RESOURCE} OR b:{CLASS}) "
            "RETURN a.iri AS s, type(r) AS t, b.iri AS o, coalesce(r.inferred, false) AS inf",
        )
    )
    want_edges = Counter((e.source, e.rel_type, e.target, bool(e.inferred)) for e in projection.edges)
    result["expected_relationships"], result["live_relationships"] = sum(want_edges.values()), sum(live_edges.values())
    if live_edges != want_edges:
        lost = want_edges - live_edges
        added = live_edges - want_edges
        if lost:
            problems.append(f"{sum(lost.values())} projected relationship(s) are missing, for example {[(a.split('#')[-1], t, b.split('#')[-1]) for a, t, b, _ in list(lost)[:3]]}")
        if added:
            problems.append(f"{sum(added.values())} relationship(s) in Neo4j are not in the projection (or are duplicated), for example {[(a.split('#')[-1], t, b.split('#')[-1]) for a, t, b, _ in list(added)[:3]]}")

    meta = _read(driver, database, f"MATCH (m:{META}) RETURN m.fingerprint AS fingerprint, m.source AS source")
    result["metadata_fingerprint"] = meta[0]["fingerprint"] if meta else None
    if not meta:
        problems.append("no ProjectionMeta node: the database has not been loaded by the exporter")
    elif meta[0]["fingerprint"] != projection.fingerprint():
        problems.append("ProjectionMeta fingerprint differs from the RDF's current projection (the database is stale)")

    result["problems"] = problems
    return result
