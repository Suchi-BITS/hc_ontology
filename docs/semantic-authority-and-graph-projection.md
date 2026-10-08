# Semantic Authority and Graph Projection

**Principle.** RDF, OWL and SHACL are the *semantic authority*. Neo4j is a *derived operational projection*. Facts enter the system through the semantic layer, are validated there, and are copied one way into Neo4j. Nothing is ever copied back, and Neo4j is never allowed to become a second source of truth.

```
   SOURCE DATA / AUTHORING
           |
           v
   +-----------------------+        +--------------------+
   |  RDF / OWL model      |------->|  SHACL shapes      |
   |  (ontology + data)    |        |  (validation gate) |
   +-----------------------+        +--------------------+
           |   AUTHORITATIVE                |
           +---------------+----------------+
                           | only valid RDF passes
                           v
                 deterministic projection
                 (services/graph_projection.py)
                    |                 |
                    v                 v
              Neo4j projection    Search / AI projection
              (operational,       (embeddings of ontology
               rebuildable)        concepts, rebuildable)
```

## 1. Why this architecture

A single system that is asked to be both a *model of meaning* and a *fast operational store* does both badly.

| | RDF / OWL / SHACL | Neo4j property graph |
|---|---|---|
| Identity | global IRIs, mergeable across sources | local node ids |
| Meaning | classes, hierarchy, inverses, axioms, a reasoner can derive new facts | none built in; the schema is conventions |
| Validation | SHACL, expressive and standard | constraints on labels and properties only |
| Strength | agreement about what the data *means* | fast traversal, application queries, vector index |
| Weakness | operational ergonomics | semantics live in application code |

Making RDF authoritative means the meaning of the data is defined once, in a standard, validated, versioned form. Making Neo4j a *projection* means it can be dropped and rebuilt at any time, so it cannot drift, accumulate unvalidated edits, or disagree with the model: if it is wrong, you rebuild it. The alternative (editing Neo4j and exporting to RDF, or editing both) produces two truths and no way to say which is right.

## 2. What is authoritative and what is derived

| Artifact | Role | Kind |
|---|---|---|
| `scripts/generate_hc_ontology.py` | Source of the ontology schema (TBox) and its controlled vocabularies | **Authoritative source** |
| `ontology/healthcare_schema.ttl` | The schema artifact, generated from the script. A test fails if it differs from the script's output, so it cannot be hand-edited | **Authoritative (generated)** |
| `data/source/*.csv`, `scripts/generate_sample_data.py` | Source of the synthetic instances (ABox) | **Authoritative source** |
| `data/sample_data.ttl` | The instance artifact, generated from the CSVs. The runtime dataset is the union of this and the schema ([schema-and-sample-data.md](schema-and-sample-data.md)) | **Authoritative (generated)** |
| `shapes/*.ttl` | SHACL shapes: what valid data looks like | **Authoritative** |
| `data/sample_instances/*.ttl` | Valid/invalid fixtures that pin the shapes' behavior | Authoritative test data |
| Neo4j labels `Resource`, `OntologyClass`, `ProjectionMeta` | Operational view of the RDF | **Derived**, rebuildable |
| Neo4j `OntologyConcept` + vector index | Embeddings of ontology classes (search/AI projection) | **Derived**, rebuildable |
| `data/healthcare_term_aliases.json` | Lexical aid for retrieval | Non-authoritative helper; synonyms should eventually move into the ontology as `skos:altLabel` |
| Neo4j `Document`, `DocumentSection` | User-supplied documents | Application data (not derived, not rebuildable) |
| Neo4j `AgentSession`, `AgentTurn`, `AgentEvent`, `AgentProcedure`, `SessionSummary` | Agent runtime memory | Application state (not derived, not rebuildable) |

### Where multiple sources of truth existed before this change

1. **A second, lossy exporter.** `HealthcareOntology.export_neo4j_cypher()` produced its own Cypher alongside `Neo4jExporter`. Both used Owlready2's object model (not the RDF), so each had its own idea of the graph. *Removed.*
2. **A seed endpoint that edited the ontology.** `POST /neo4j/seed-demo` created individuals in OWL, rewrote the OWL file, and then wiped Neo4j with `MATCH (n) DETACH DELETE n`. Data entry shortcuts could corrupt the model, and the wipe destroyed agent memory and embeddings. *Removed; demo data now lives in the generator.*
3. **An exporter that rewrote meaning.** It kept the first type and first value, dropped the hierarchy, and identified nodes by name. The graph was a different, poorer model than the RDF. *Replaced by the projection.*
4. **A label collision.** The ontology class `Procedure` and agent procedural memory's `:Procedure` shared a label in one database. *Memory renamed to `:AgentProcedure`, with migration of existing nodes.*

## 3. The projection

Code: `services/graph_projection.py` (pure logic, no database), `services/neo4j_exporter.py` (writer).

Pipeline: parse RDF → SHACL gate → `build_projection()` → statement plan → one Neo4j write transaction.

### 3.1 Identity strategy

```
RDF IRI  --->  Neo4j property `iri`   (the identity; uniquely constrained)
local name --> Neo4j property `name`  (display and query convenience only)
```

Two individuals called `john` in different namespaces are two nodes. Relationship endpoints are matched by `iri` **and an explicit label**, never by name or without a label (the old exporter matched `MATCH (a {name: $a})` across all nodes). `name` stays because queries and the agent's prompts filter by it; it is not trusted for identity.

### 3.2 What is preserved

| RDF | Neo4j | Notes |
|---|---|---|
| individual | `(:Resource {iri, name, rdfTypes, ...})` | |
| every asserted `rdf:type` | a label **and** `rdfTypes` (IRIs) **and** `(:Resource)-[:INSTANCE_OF]->(:OntologyClass)` | multiple types are all kept |
| superclasses of those types | additional labels | `MATCH (c:Condition)` finds diagnoses; this is RDFS entailment, materialized as labels. `rdfTypes` still records what was asserted |
| `owl:Class` | `(:OntologyClass {iri, name, label, comment, ...})` | classes referenced but not declared (for example `skos:Concept`) are kept and flagged `external: true` |
| `rdfs:subClassOf` between named classes | `(:OntologyClass)-[:SUBCLASS_OF]->(:OntologyClass)` | the hierarchy is **not flattened**; for example `Specialty ⊑ skos:Concept`, `Diagnosis ⊑ Condition` |
| object-valued triple | relationship, type = `UPPERCASE(localname)` | for example `hasDiagnosis` → `HASDIAGNOSIS` |
| `owl:inverseOf`, `rdfs:subPropertyOf` | extra relationships with `inferred = true` | entailed by the schema, marked so asserted facts stay distinguishable; lets a query use either direction or a super-property |
| literal-valued triple | node property, key = local name | native types: `xsd:date` → date, `xsd:dateTime` → datetime with offset, `xsd:decimal` → float, `xsd:boolean` → boolean |
| functional property | scalar | the ontology states "at most one value" |
| any other property | **list of all values**, sorted | never reduced to the first value; a lone value is still a list |
| `owl:equivalentClass` | class property `definedClass: true` | the expression itself stays in RDF (see limitations) |
| annotation properties (`rdfs:label`, `rdfs:comment`, `skos:prefLabel`, `skos:notation`, ...) | properties | `skos:inScheme` becomes the `INSCHEME` relationship |

This is why the ontology declares single-valued attributes **functional by default**: it is the ontology, not the exporter, that decides what is a scalar. Contact data (`phoneNumber`, `emailAddress`, `address`, `emergencyContact`) is genuinely multi-valued and projects as lists, so queries test it with `'x' IN n.phoneNumber`.

### 3.3 Determinism

The same RDF always produces the same logical graph:

* nodes, classes, edges and list values are sorted; the projection has a SHA-256 `fingerprint()`;
* the fingerprint does not depend on triple order (tested by shuffling the graph);
* the writer is idempotent: MERGE by `iri`, full replacement of properties and labels, rebuild of relationships among projection nodes, pruning of projection nodes no longer in the RDF;
* the only time-dependent value is `syncedAt`, stored on a separate `:ProjectionMeta` node, not in the compared data.

### 3.4 Rejecting invalid RDF

Nothing partial is loaded. The projection raises `ProjectionError` (HTTP 422 with a `problems` list) for: unparseable or missing files, an empty graph, a document with no `owl:Ontology` header, an object property pointing at an entity that is not in the graph, a functional property with several values, mixed datatypes in one list (a Neo4j limitation), local-name collisions (two classes or two properties that would map to the same label or key), and names that are not safe Cypher identifiers. Before projection, the RDF is validated against the SHACL shapes; any `Violation` raises `ProjectionRejected`. The SHACL gate can be skipped only by passing `validate=False` in code; the HTTP API has no such switch.

### 3.5 Injection safety

Labels and relationship types come from the validated ontology (checked against `^[A-Za-z][A-Za-z0-9_]*$`), never from request input. Every *value* travels as a query parameter.

## 4. Graph domains and what may be deleted

One Neo4j database holds several kinds of state. They are separated by label (`core/graph_domains.py`); Neo4j Community has a single user database, so labels are the available boundary.

| Domain | Labels | Owner | Rebuildable? |
|---|---|---|---|
| Domain knowledge | `Resource`, `OntologyClass` | RDF projection | yes |
| Operational metadata | `ProjectionMeta` | RDF projection | yes |
| Semantic index | `OntologyConcept` (+ vector index) | embedding sync | yes |
| Application data | `Document`, `DocumentSection` | document ingestion | **no** |
| Agent memory | `AgentSession`, `AgentTurn`, `AgentEvent`, `AgentProcedure`, `SessionSummary` | agent runtime | **no** |

Rules enforced in code and tests:

* The projection touches only `Resource`, `OntologyClass`, `ProjectionMeta`. A test asserts the generated statements contain none of the other labels.
* The class-name set of the ontology must not intersect the labels of any other domain (a test; this caught the `Procedure` collision).
* **No application endpoint clears the database.** `POST /neo4j/seed-demo` was removed; `POST /neo4j/load` is a scoped, idempotent synchronization. A test scans the source tree for an unscoped `MATCH (n) ... DETACH DELETE`.
* A development reset exists only as `Neo4jExporter.reset_projection()` via `scripts/seed_neo4j_demo.py --yes --reset-projection`. It is refused unless `ENVIRONMENT` is `development`/`dev`/`test`/`local` **and** `ALLOW_PROJECTION_RESET=true`, and it removes only the three projection labels. It cannot be reached over HTTP.

Embeddings: `OntologyConcept` is derived from the ontology's class annotations and stays in its own label and vector index. Rebuilding the domain projection does not touch it, and it can be regenerated with `POST /embedding/sync`.

## 5. Operating it

```bash
python scripts/generate_hc_ontology.py                # author: regenerate the schema
python scripts/generate_sample_data.py                # author: regenerate the sample data
pytest tests/test_ontology.py tests/test_clinical_shapes.py   # model + shapes
GET  /neo4j/projection                                 # preview: counts, fingerprint, notes (no database)
POST /neo4j/load                                       # synchronize Neo4j from the RDF
python scripts/seed_neo4j_demo.py --yes                # development: sync + bootstrap procedural memory
```

Typical flow for a change: edit the generator or a shape → regenerate → tests → `POST /neo4j/load`. Never edit Neo4j to change what the data means; change the RDF and resynchronize.

## 6. Querying across the two representations

* **Meaning, validation, reasoning, SPARQL:** use the RDF (rdflib/SPARQL, SHACL, a reasoner).
* **Application queries, traversal, agent Cypher, vector search:** use Neo4j.
* **Reasoner-inferred facts** (for example `AntidiabeticMedication` membership) are *not* in the projection unless a reasoned graph is passed to `build_projection()`. The projection accepts any rdflib `Graph`, so a pipeline can project the output of a reasoner.

## 7. Known limitations

* **Complex class expressions** (equivalence, restrictions, disjointness) are not projected as structure. Defined classes are flagged; evaluate them in RDF/with a reasoner.
* **Transitive closures** (`partOfLocation`) are not materialized; Cypher uses variable-length paths over the asserted containment relationships instead (for example `[:CONTAINSWARD|CONTAINSROOM|CONTAINSBED*]`).
* **Hierarchy is materialized as labels** (flat set) plus `SUBCLASS_OF` edges; a node with many types carries many labels.
* **Language tags** on literals are not kept as separate properties (the text is kept).
* **`xsd:decimal` becomes float** (Neo4j has no decimal type).
* **Homogeneous lists only:** a property whose values mix datatypes is rejected.
* **Rebuild is one transaction.** Fine for thousands of nodes; a larger graph needs batching.
* **Sync is pull, on demand.** There is no continuous synchronization, event stream or change capture, deliberately: a deterministic rebuild is simpler to reason about and to test.
* **Not verified against a live Neo4j in this repository's tests.** The statement plan, the transaction order, the gate, and the guards are verified with a recording driver; run `POST /neo4j/load` against a real instance to confirm the Cypher in your Neo4j version (5.x).
* **Existing databases:** nodes written by the old exporter (label-only, keyed by `name`) are not migrated. Run the sync to create `Resource` nodes; remove the old nodes manually if they are no longer wanted. Procedural-memory nodes labelled `:Procedure` are migrated to `:AgentProcedure` automatically.
