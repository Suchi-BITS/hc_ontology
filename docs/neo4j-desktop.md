# Neo4j Desktop: the reference graph database

The reference environment for this project's graph layer is a **local Neo4j Desktop database**. It is the one that has been exercised end to end against the real application; see [NEO4J_DESKTOP_LIVE_VERIFICATION.md](NEO4J_DESKTOP_LIVE_VERIFICATION.md) for exactly what was run and what it showed.

## 1. What is verified, and what is not

| Arrangement | Status |
|---|---|
| **Python application, running locally, to Neo4j Desktop on `localhost:7687`** | **Verified** (Neo4j 5.20.0, Windows 11, Python 3.11.8) |
| API container, to a Docker Neo4j (`docker_compose.yaml`) | **Not verified.** The Compose file is kept and its configuration was checked statically; no container was started |
| Kubernetes, to Neo4j | **Not verified** |
| Neo4j Aura | **Not verified** |
| Neo4j Community edition | **Not verified** (the verified server was Neo4j Desktop's Enterprise-licensed development build; nothing the project uses is Enterprise-only, but this has not been tested) |

```text
A. Local development and reference verification          B. Optional containerised application (not verified)

   Python application                                        API container
        |   bolt                                                  |   bolt
        v                                                         v
   Neo4j Desktop (localhost:7687)                            the Neo4j endpoint you configure
                                                             (for example `docker_compose.yaml`'s `neo4j` service)
```

`docker_compose.yaml` still contains a `neo4j` service, because it is useful for people who want one command to start the whole stack. It was neither removed nor used for the reference verification. APOC is not required anywhere.

## 2. Setup

1. **Install Neo4j Desktop** (https://neo4j.com/download/).
2. **Create a local database** (a DBMS) and **set its password**. Neo4j 5.x is required (the project uses vector indexes only for the optional AI layer).
3. **Start it.** A Desktop DBMS listens on `bolt://localhost:7687` by default.
4. **Create or choose an empty database inside it.** The default database is named `neo4j`. The projection should go into a database that holds nothing else: see section 4.
5. **Configure** `.env` (copy `.env.example`; the file is git-ignored and the password is never committed):

   ```text
   NEO4J_URI=bolt://localhost:7687
   NEO4J_USERNAME=neo4j          # NEO4J_USER is accepted as an alias
   NEO4J_PASSWORD=<your-password>
   NEO4J_DATABASE=neo4j
   ```

6. **Check the connection** (read-only; never prints the password):

   ```bash
   python scripts/dev.py doctor --neo4j
   python scripts/dev.py verify-neo4j
   ```

7. **Load the projection** (SHACL-gated, idempotent, scoped to its own labels):

   ```bash
   python scripts/dev.py load
   ```

8. **Validate**: `python scripts/dev.py validate` (offline: contract, SHACL, projection plan).
9. **Verify the live graph against the RDF**, then query it:

   ```bash
   python scripts/dev.py verify-neo4j --projection --census
   python scripts/dev.py demo --neo4j
   ```

   Then try `MATCH (p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis) RETURN p.name, d.diagnosisName` in Neo4j Browser.

Example output of step 6:

```text
Neo4j verification
------------------
URI: bolt://localhost:7687
User: neo4j
Database: neo4j
Server: 127.0.0.1:7687  (Neo4j/5.20.0)
Status: ONLINE
Neo4j version: 5.20.0 (enterprise)
Nodes: 183
Relationships: 476
Graph domains (by label): projection=183
Result: PASS
```

If Neo4j is not running the command says so, changes nothing, and exits non-zero (`2`). It does not start a container and does not create a database.

## 3. Where the data comes from, and who is the authority

```text
 ontology/healthcare_schema.ttl  +  data/sample_data.ttl      the RDF/OWL dataset: THE AUTHORITY
        |                |                  |
        |                |                  +--> SHACL validation        (shapes/)
        |                +---------------------> SPARQL / semantic queries (sparql/, the reasoner)
        |
        +--> SHACL gate --> projection (services/graph_projection.py) --> Neo4j   DERIVED, rebuildable
                                                                              |
                                                                              +--> API graph queries (/execute-cypher)
```

Neo4j is **not** the ontology store. Everything in it can be rebuilt from the RDF with `python scripts/dev.py load`; nothing is edited in Neo4j by hand; `/sparql` is answered from the RDF, not from Neo4j. If the two ever disagree, the RDF is right and `verify-neo4j --projection` tells you.

## 4. One rule you need to know: use an empty database

`python scripts/dev.py load` **refuses** to project into a database that already holds nodes outside this project's graph domains, and writes nothing. Why: an older version of this project exported nodes keyed by `name`, with labels such as `Patient` or `Neurologist` and no `iri`. Projecting into such a database would put two representations of the same people side by side, so `MATCH (p:Patient)` would return both. The check is read-only and runs before any write.

The graph domains that are allowed to share a database, and never touch each other, are: the **projection** (`Resource`, `OntologyClass`, `ProjectionMeta`), **agent memory** (`AgentSession`, `AgentTurn`, `AgentEvent`, `AgentProcedure`, `SessionSummary`), **documents** (`Document`, `DocumentSection`) and the **semantic index** (`OntologyConcept`). Point `NEO4J_DATABASE` at an empty database, or use `--allow-foreign-data` if you really intend to mix.

## 5. What the projection does to the RDF

Verified against the live database: [the full results are in the report](NEO4J_DESKTOP_LIVE_VERIFICATION.md).

| RDF | Neo4j |
|---|---|
| An individual | A node `:Resource` plus its class and **all superclass** labels (`:Resource:Person:Patient`); its identity is the **`iri` property**, under a uniqueness constraint. The display name is a separate `name` property |
| A class | A node `:OntologyClass`, linked by `SUBCLASS_OF` to its parent and by `INSTANCE_OF` from each individual |
| An object property assertion | A relationship named after the property (`HASDIAGNOSIS`); relationships to the same target are never collapsed |
| An inverse or super-property that follows from the schema | A relationship marked `inferred: true`; never stored as asserted |
| A datatype property | A typed node property (`xsd:date` becomes a `DATE`, `xsd:dateTime` a `ZONED DATETIME`, decimals `FLOAT`); multi-valued ones become lists |

Intentionally **not** projected (also reported by the projection itself): OWL restrictions and `equivalentClass` definitions (defined classes are flagged on their class node), domain/range axioms, disjointness, and anything a reasoner would derive beyond the inverse and super-property edges above. The projection is a read model for graph queries, not a reasoner.

## 6. Troubleshooting

See [troubleshooting.md](troubleshooting.md), section "Neo4j".
