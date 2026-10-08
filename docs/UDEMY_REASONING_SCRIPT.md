# Udemy Video Script: Reasoning in the Healthcare Knowledge Graph

**Course module:** *OWL, Inference, SHACL Rules & Graph Reasoning*  
**Project:** `hc_ontology/`  
**Suggested runtime:** 75–90 minutes (3–4 videos)  
**Prerequisite:** Ingestion module (OWL → Neo4j export)

See also: [COURSE_STRUCTURE.md](../COURSE_STRUCTURE.md), [graph_schema_design.md](../graph_schema_design.md), [readme.md](../readme.md#shacl-vs-owl--who-owns-which-check)

---

## VIDEO 1 — Deductive reasoning & the two reasoning layers (22 min)

### Hook (2 min)

**[ON SCREEN]** Side-by-side:

- Protege: `Antibiotic` ⊑ `Medication`
- Neo4j Browser: `(p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis)`
- Swagger: `POST /validate/ontology` → violation report

**NARRATION**

> Reasoning is how a knowledge graph **derives conclusions** from facts and rules—not just stores them.
>
> In this project, reasoning is split across **two layers**:
>
> | Layer | Engine | What it derives |
> |-------|--------|-----------------|
> | **OWL / RDFS** | Schema + (optionally) OWL reasoner | Class membership, property constraints, subsumption |
> | **SHACL** | pySHACL + RDFS expansion | Validation violations, business-rule failures |
> | **Application / graph** | Python + Cypher + LLM agents | Traversal paths, multi-hop answers, grounded retrieval |
>
> This is important: **not every kind of inference runs automatically at API startup.** We'll map each topic to what the code actually does.

---

### Section 1.1 — Deductive reasoning

**Learning objective:** Define deductive reasoning and locate it in the architecture.

**NARRATION**

> **Deductive reasoning** starts from general rules and specific facts, then concludes something that *must* be true if the rules hold.
>
> Example rule in our ontology:
> *Every Prescription must have exactly one prescribedFor Patient.*
>
> Example fact:
> *PrescriptionDiabetesAlice is a Prescription.*
>
> Deductive conclusion:
> *PrescriptionDiabetesAlice must link to exactly one Patient*—or the data is inconsistent with the schema.

**[ON SCREEN — CODE]** `scripts/generate_hc_ontology.py`

```python
Prescription.is_a.append(
    prescribedBy.exactly(1, Doctor)
)

Prescription.is_a.append(
    prescribedFor.exactly(1, Patient)
)
```

**[ON SCREEN — DOC]** `readme.md` — SHACL vs OWL table

| Concern | Authoritative layer |
|---------|---------------------|
| Class hierarchy, reasoning, inferred facts | OWL + reasoner |
| Instance well-formedness (required fields, patterns, closed shapes) | SHACL |
| Business rules (e.g. “no prescription may contain a medication the patient is allergic to”) | SHACL (`sh:SPARQLConstraint` in `medication_shapes.ttl`) |

**NARRATION**

> The readme tells students the **design intent**: OWL owns taxonomy and inferred facts; SHACL owns instance checks and business rules. In code, both coexist—but they run at **different times** and **different endpoints**.

**[DEMO]**

```http
GET /stats
GET /classes
POST /validate/ontology
```

---

### Section 1.2 — OWL inference (schema-level)

**Learning objective:** See OWL restrictions and class hierarchy in the ontology; understand what is *not* running at runtime.

**NARRATION**

> **OWL inference** can infer:
> - Subclass relationships (`Cardiologist` is a `Doctor`)
> - Property chains and cardinality violations
> - Class membership from restrictions (e.g. something satisfying Prescription constraints)

**[ON SCREEN — OWL]** Open `healthcare_ontology.owl` — show `rdfs:subClassOf` for `Antibiotic`, `Analgesic`, etc.

**[ON SCREEN — CODE]** Medication hierarchy in `scripts/generate_hc_ontology.py`

```python
class Antibiotic(Medication):
    pass

class Analgesic(Medication):
    pass
```

**Honest implementation note (critical for students):**

**[ON SCREEN — CODE]** Top of `scripts/generate_hc_ontology.py`

```python
from owlready2 import (
    ...
    sync_reasoner_pellet
)
```

**NARRATION**

> `sync_reasoner_pellet` is **imported** but **never called** before save. The script writes `healthcare_ontology.owl` directly; the FastAPI app loads it with Owlready2 but does **not** sync a reasoner on boot.
>
> So: OWL inference is **encoded in the ontology**, not **materialized at runtime** in this course project. Students can extend it:

```python
# Extension lab (not in repo today):
with onto:
    sync_reasoner_pellet(infer_property_values=True)
onto.save(...)
```

> After reasoning, inferred triples (e.g. explicit `rdf:type Medication` for an `Antibiotic` individual) could be exported to Neo4j—today export only writes **asserted** individual properties.

**[ON SCREEN — CODE]** Neo4j export uses first explicit class only (`services/neo4j_exporter.py`):

```python
label = individual.is_a[0].name
```

**Teaching point:** `Metformin` exported as `:Analgesic`, not also `:Medication`, unless you add multi-label export or run a reasoner first.

---

### Section 1.3 — RDFS inference

**Learning objective:** Distinguish RDFS (subclass, subproperty, domain, range) from full OWL; find where RDFS inference *does* run.

**NARRATION**

> **RDFS inference** is lighter than OWL DL. It mainly propagates:
> - `A rdfs:subClassOf B` → instances of A are instances of B
> - Domain/range rules on properties

**Where it runs in our code:** `core/shacl_validator.py`

```python
conforms, results_graph, _text = validate(
    data_graph,
    shacl_graph=shapes_graph,
    ...
    inference="rdfs",
    inplace=False,
)
```

**NARRATION**

> pySHACL expands the data graph with **RDFS entailments before validating**. That means SHACL may “see” inferred types when checking shapes—without you manually asserting every superclass.

**Where it does NOT fully run:**

- `execute_sparql()` in `services/load_ontology.py` parses OWL into rdflib and runs raw SPARQL—**no OWL/RDFS reasoner attached**
- Neo4j clinical layer stores explicit edges only

**[DEMO LAB]**

```http
POST /validate
Content-Type: application/json

{
  "format": "turtle",
  "shape_files": ["patient_shapes.ttl"],
  "data": "@prefix hc: <http://example.org/healthcare-hospital.owl#> .\nhc:PatientAlice a hc:Patient ; hc:firstName \"Alice\" ."
}
```

Then break `bloodGroup` pattern and show SHACL failure from `shapes/patient_shapes.ttl` (`sh:pattern` for ABO types).

---

## VIDEO 2 — SHACL rules, chaining & rule-based reasoning (28 min)

### Section 2.1 — SHACL rules (constraint validation)

**Learning objective:** Read SHACL shapes; run validation API; understand SPARQL-based rules.

**NARRATION**

> **SHACL** (Shapes Constraint Language) is rule-based validation over RDF graphs. It does not replace OWL—it **checks** whether data conforms to expected shapes.

**Three rule styles in our repo:**

| Style | Example file | Rule type |
|-------|--------------|-----------|
| Property cardinality / datatype | `shapes/patient_shapes.ttl` | `sh:minCount`, `sh:pattern` |
| Shape composition | `shapes/patient_shapes.ttl` → `sh:node shapes:PersonShape` | Reusable sub-shapes |
| SPARQL constraint | `shapes/medication_shapes.ttl` | Multi-hop business rule |

**[ON SCREEN — FILE]** Allergy conflict rule in `shapes/medication_shapes.ttl`

```turtle
# Business rule OWL restrictions cannot express: do not prescribe a drug
# the patient is allergic to (allergyToMedication ∩ containsMedication).
shapes:PrescriptionAllergyConflictShape
    ...
        sh:select """
            ...
                $this hc:prescribedFor ?patient .
                $this hc:containsMedication ?med .
                ?patient hc:hasAllergy ?allergy .
                ?allergy hc:allergyToMedication ?med .
```

**NARRATION**

> This is a **4-hop graph pattern** encoded as a validation rule—not as an OWL restriction. If the pattern matches, the prescription is **invalid**. That's deductive checking: IF these edges exist, THEN violation.

**[ON SCREEN — FIXTURE]** `data/sample_instances/invalid_prescription_allergy.ttl`

**[DEMO]**

```http
POST /validate/file
(upload invalid_prescription_allergy.ttl)

GET /validation/report?format=html
```

Show `SHACL_VALIDATION_MODE=warn` vs `strict` in `.env`.

**Primary files:** `core/shacl_validator.py`, `core/shacl_loader.py`, `routers/shacl.py`, `shapes/`

---

### Section 2.2 — Forward chaining vs backward chaining

**Learning objective:** Map classical terms to engines in this project.

**NARRATION**

> **Forward chaining:** start from facts, apply rules, derive new facts until nothing changes.  
> **Backward chaining:** start from a goal, work backward to see if facts support it.

**Forward chaining in our codebase:**

| Mechanism | Where | What fires forward |
|-----------|-------|-------------------|
| pySHACL + RDFS | `ShaclValidator.validate_graph()` | Expands types, evaluates all shape rules |
| Neo4j export passes | `Neo4jExporter.export()` | Nodes → properties → relationships |
| Agent validation pipeline | `QueryValidator.run_all_checks()` | safety → syntax → schema → LIMIT |

**Backward chaining in our codebase:**

| Mechanism | Where | Goal-directed behavior |
|-----------|-------|------------------------|
| GraphRAG retrieve | `services/document_ingestor.py` | Query → concepts → **back** to document sections |
| SPARQL/Cypher | User/API query | Pattern matches work from desired variables backward to bindings |
| LLM Planner | `agents/nodes/planner.py` | Question → choose query path (cypher/sparql/ontology_only) |

**[ON SCREEN — DOC]** GraphRAG backward traversal (`graph_schema_design.md`)

```cypher
MATCH (ds:DocumentSection {tenant_id: $tenant_id})-[r:GROUNDS_IN]->(c:OntologyConcept)
WHERE c.name IN $concept_names
RETURN ds.section_id, ds.content, c.name, r.confidence_score
ORDER BY r.confidence_score DESC
```

**[DEMO]**

```http
POST /documents/graphrag/retrieve
{"query": "insulin dosage diabetes"}
```

---

### Section 2.3 — Rule-based reasoning (application rules)

**Learning objective:** Identify non-SHACL, non-OWL rule systems in the app.

**NARRATION**

> Not all rules are SHACL. Our app has **application-level rule engines**:

**1. Hardcoded NL rules** — `services/load_ontology.py` → `natural_language_query()`

```python
if "patients" in q and "hypertension" in q:
    ...
    for p in d.diagnosisForPatient:
        results.append(p.name)
    return results
return {"message": "No rule matched."}
```

**2. Agent planner heuristics** — `agents/nodes/planner.py` → `_heuristic_plan()`

**3. Query safety rules** — `core/cypher_validator.py`, `core/sparql_validator.py`

**4. Enterprise guardrails** — `enterprise/guardrails.py`

**[STUDENT EXERCISE]** Add one new rule to `_heuristic_plan`: questions mentioning "medication" route to `cypher`.

---

## VIDEO 3 — Graph traversal, multi-hop & inferred facts (25 min)

### Section 3.1 — Graph traversal reasoning (Python / Owlready2)

**Learning objective:** Follow explicit property chains in application code.

**NARRATION**

> **Graph traversal reasoning** walks known edges to answer questions. REST endpoints in `services/load_ontology.py`:

| API | Traversal path |
|-----|----------------|
| `GET /patients/{name}/diagnoses` | Patient → `hasDiagnosis` → Diagnosis |
| `GET /patients/{name}/treatments` | Patient → Diagnosis → `requiresTreatment` → Treatment |
| `GET /doctors/{name}/patients` | Doctor ← `diagnosedBy` ← Diagnosis → `diagnosisForPatient` → Patient |

**[DEMO]**

```http
GET /patients/PatientJohn/diagnoses
GET /patients/PatientJohn/treatments
GET /doctors/DrSmith/patients
```

**NARRATION**

> `get_doctor_patients` never uses a direct `Doctor→Patient` edge. It **derives** the relationship by traversing `diagnosedBy` and `diagnosisForPatient`. That's application-level inferred knowledge—computed at query time, not stored as a new edge.

---

### Section 3.2 — Multi-hop reasoning (Cypher & Neo4j)

**Learning objective:** Write and run multi-hop Cypher; connect to NL→Cypher agent.

**NARRATION**

> **Multi-hop reasoning** chains several relationships to reach a conclusion.

**Canonical course example (3-hop clinical path):**

```cypher
MATCH (p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis {diagnosisName: 'Diabetes'}),
      (rx:Prescription)-[:PRESCRIBEDFOR]->(p),
      (rx)-[:CONTAINSMEDICATION]->(m:Medication)
RETURN p.name, d.diagnosisName, m.medicationName
LIMIT 50
```

> Hop 1: patient to diagnosis  
> Hop 2: prescription to patient  
> Hop 3: prescription to medication  

**No single edge** connects patient to medication—reasoning requires composing hops.

**Agent neighborhood expansion (1-hop exploratory reasoning)** — `enterprise/hybrid_retrieval.py`:

```cypher
MATCH (n)
WHERE n.name = 'Diagnosis'
OPTIONAL MATCH (n)-[r]-(m)
RETURN n.name AS source, type(r) AS rel, m.name AS neighbor
```

**[DEMO]**

```http
POST /nl-to-cypher
POST /execute-cypher
POST /enterprise/hybrid-search
POST /agent/query
```

Show `reasoning` field in agent state from planner JSON. Note: LLM "reasoning" is **plan explanation**, not OWL logical inference.

---

### Section 3.3 — Derived relationships

**Learning objective:** Distinguish asserted vs derived edges in this architecture.

| Relationship | Asserted in OWL/Neo4j? | Derived how? |
|--------------|------------------------|--------------|
| `HASDIAGNOSIS` | ✅ Yes | Direct object property |
| `PRESCRIBEDFOR` / `CONTAINSMEDICATION` | ✅ Yes | Prescription bridge |
| `Doctor → Patient` | ❌ No direct edge | Python: via `diagnosedBy` + `diagnosisForPatient` |
| `DocumentSection → OntologyConcept` | ✅ `GROUNDS_IN` | Created at ingest from embedding similarity |
| `AgentTurn → OntologyConcept` | ✅ `USED_CONCEPT` | Created after agent run (`agents/memory.py`) |
| `Patient → Medication` | ❌ Not valid | Must compose through `Prescription` |

---

### Section 3.4 — Inferred facts (what exists vs what students should add)

**Learning objective:** Clear picture of inferred facts in production vs this course repo.

| Source | Inferred facts? | Materialized? |
|--------|-----------------|---------------|
| OWL reasoner (Pellet) | Possible, not wired | ❌ |
| pySHACL RDFS | Temporary for validation | ❌ (validation report only) |
| Python traversals | Computed answers | ❌ (JSON response only) |
| Cypher multi-hop | Computed at query time | ❌ |
| Embedding `is_a` in text | Semantic, not logical | Stored in concept embedding text |

**Extension capstone for students:**

1. Run `sync_reasoner_pellet()` after loading OWL  
2. Export inferred `rdf:type` triples to Neo4j as extra labels  
3. Materialize frequent derived paths as Cypher views or scheduled jobs  

---

## VIDEO 4 — Recap, comparison table & quiz (8 min)

### Master mapping table

| Topic | In this codebase? | Primary implementation |
|-------|-------------------|------------------------|
| Deductive reasoning | ✅ Design + partial runtime | OWL restrictions, SHACL SPARQL rules, traversals |
| OWL inference | ⚠️ Schema only | `scripts/generate_hc_ontology.py`, `healthcare_ontology.owl`; reasoner imported not invoked |
| RDFS inference | ✅ During SHACL | `inference="rdfs"` in `core/shacl_validator.py` |
| Rule-based reasoning | ✅ | SHACL shapes, `natural_language_query`, planner heuristics, query validators |
| SHACL rules | ✅ Full | `shapes/*.ttl`, `pyshacl`, `/validate/*` |
| Forward chaining | ✅ Partial | SHACL validation, export pipeline, validation stages |
| Backward chaining | ✅ Partial | GraphRAG retrieve, SPARQL/Cypher pattern matching |
| Graph traversal reasoning | ✅ | `load_ontology.py` traversals, Neo4j Cypher, hybrid neighborhood |
| Multi-hop reasoning | ✅ | Patient→Diagnosis→Treatment; Prescription path; SHACL allergy rule (4 hops) |
| Derived relationships | ✅ At query time | `get_doctor_patients`, `GROUNDS_IN`, `USED_CONCEPT` |
| Inferred facts | ⚠️ Limited | Not materialized in Neo4j; RDFS expansion during SHACL only |

### Three architecture principles

1. **OWL defines what the world means**—classes, properties, restrictions.  
2. **SHACL enforces what data is allowed**—including business rules OWL can't express cleanly.  
3. **Neo4j + agents answer questions**—through explicit and multi-hop traversal, not a running OWL reasoner in this course build.

### Quiz (5 questions)

1. Where does RDFS inference actually run in this project?  
2. Why doesn't `Metformin` automatically get a `:Medication` label in Neo4j today?  
3. Is the allergy-prescription conflict checked by OWL or SHACL?  
4. Name two backward-chaining patterns in the codebase.  
5. What's the difference between `get_doctor_patients()` and a direct `Doctor→Patient` edge?

### Hands-on lab sequence

```http
POST /neo4j/seed-demo
GET  /patients/PatientAlice/treatments
POST /validate/ontology
POST /validate/file          (invalid_prescription_allergy.ttl)
POST /nl-to-cypher           ("Which patients have diabetes and what medications...")
POST /agent/query            (same question — inspect plan reasoning + trace)
```

---

## Recording notes

- **Protege demo:** Show class hierarchy + `Prescription` restrictions; mention "Run reasoner" as extension not in API.  
- **Contrast slide:** Logical inference (SHACL/OWL) vs statistical retrieval (embeddings)—students confuse these often.  
- **Call out the `sync_reasoner_pellet` import**—great teaching moment about gap between ontology authoring and runtime reasoning.  
- **Use the diabetes/medication Cypher** as the flagship multi-hop example—it connects to the NL→Cypher module.

### Repository map for this module

| Topic | Primary files |
|-------|---------------|
| OWL restrictions | `scripts/generate_hc_ontology.py`, `healthcare_ontology.owl` |
| RDFS + SHACL | `core/shacl_validator.py`, `core/shacl_loader.py`, `shapes/` |
| Validation API | `routers/shacl.py`, `data/sample_instances/` |
| Graph traversals | `services/load_ontology.py`, `routers/patients.py`, `routers/doctors.py` |
| Multi-hop Cypher | `services/cypher_generator.py`, `services/seed_demo_data.py` |
| Backward chaining / GraphRAG | `services/document_ingestor.py`, `graph_schema_design.md` |
| Agent reasoning | `agents/nodes/planner.py`, `enterprise/hybrid_retrieval.py`, `agents/memory.py` |
