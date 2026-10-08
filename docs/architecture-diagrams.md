# Architecture diagrams

Nine diagrams, in the order a reader meets the ideas. They are ASCII so they survive any renderer, diff cleanly and can be copied into a book manuscript. Each names the files that implement the boxes, and each is accurate to this repository at the time of writing; the tests named under the diagrams are what keep them honest.

Conventions: `[ ]` is a thing you can open in the repository, `( )` is a process, `{ }` is a gate that can stop the flow, `==>` is the authoritative path, `-->` is a derived path.

## 1. Overall architecture

```text
                         CORE  (needs no LLM, no agent framework, no Neo4j server)
 +-------------------------------------------------------------------------------------+
 |                                                                                     |
 |  [data/source/*.csv]                                                                |
 |        |  (services/sample_data.py)                                                 |
 |        v                                                                            |
 |   {data contract}                                                                   |
 |        |                                                                            |
 |        v   (scripts/generate_hc_ontology.py)                                        |
 |   TBox: classes, properties, SKOS vocabularies  +  ABox: individuals                |
 |        |                                                                            |
 |        v                                                                            |
 |   {SHACL gate}  <----------- [shapes/*.ttl]                                         |
 |        |                                                                            |
 |        v                                                                            |
 |  [ontology/healthcare_schema.ttl] + [data/sample_data.ttl]  ==== THE AUTHORITY ==== |
 |            (the schema, TBox)           (the instances, ABox)  merged: core/dataset.py     |
 |        |                 \                                                          |
 |        | (rdflib)         \ (services/graph_projection.py)                          |
 |        v                   v                                                        |
 |   SPARQL  [sparql/*.rq]   {SHACL gate again} --> Neo4j projection (derived)         |
 |        \                   /                                                        |
 |         v                 v                                                         |
 |        HTTP API  (api.py, routers/)  -- authn -> authz -> tenant -> read-only exec  |
 +-------------------------------------------------------------------------------------+
                                   ^
                                   | consumes, never the reverse
 +-------------------------------------------------------------------------------------+
 |  ADVANCED (optional)  embeddings -> hybrid retrieval -> LLM query generation        |
 |                       -> validation -> human approval -> execution -> abstention    |
 |                       -> cited answer          memory: working/episodic/procedural/ |
 |                                                semantic                             |
 +-------------------------------------------------------------------------------------+
```

Why it looks like this: there is exactly one authority (the RDF file), every other representation is derived from it, and every arrow into a derived store passes through a validation gate. See [semantic-authority-and-graph-projection.md](semantic-authority-and-graph-projection.md) and [core-vs-ai-architecture.md](core-vs-ai-architecture.md).

## 2. Ontology lifecycle

```text
  domain question                "Which prescriptions conflict with an allergy?"
        |
        v
  competency question (CQ)       sparql/cq10_*.rq + expected answer           [competency-questions.md]
        |
        v
  model                          class? property? SKOS concept? CodeConcept?  [ontology-engineering.md]
        |
        v
  generator edit  --->  regenerate the schema   (python scripts/generate_hc_ontology.py)
                        and the sample data     (python scripts/generate_sample_data.py)
        |
        v
  +--------- checks that must all pass -----------------------------------------------+
  |  parse  |  generator == committed file  |  SHACL  |  reasoner consistent (Java)   |
  |  every class has a label  |  inverse pairs agree  |  no temporal property is str  |
  +---------------------------------------------------------------------------------- +
        |
        v
  CQs still return their hand-written answers?  --- no ---> the change broke a requirement
        |
       yes
        v
  commit the regenerated file  (a test fails if the file and the generator disagree)
```

Tests: `tests/test_ontology.py`, `tests/test_sparql_competency.py`, `scripts/validate.py`.

## 3. RDF pipeline

```text
 data/source/*.csv                 plain facts, one table per kind of thing
      |  load_dataset()
      v
 {data contract}                   references exist; ids unique; dates, codes, classifications valid
      |                            -> DataContractError lists EVERY problem, writes nothing
      v  build_sample_data()
 Owlready2 individuals             each row -> an IRI (http://example.org/healthcare-hospital.owl#PatientJohn),
      |                            a class, typed literals, links to other IRIs
      v  onto.save(tmp)
 temp .owl file
      |
      v
 {SHACL gate}                      fails -> the old file is untouched, nothing is written
      |
      v  os.replace()              atomic
 [data/sample_data.ttl]            Turtle; the instances only. [ontology/healthcare_schema.ttl] is the schema,
                                   generated separately, and the two are merged at read time
```

Walk through it with [sample-data-and-semantic-mapping.md](sample-data-and-semantic-mapping.md). Tests: `tests/test_sample_data.py` (50 deliberately broken inputs).

## 4. SHACL validation

```text
 data graph  [.owl or .ttl]            shapes graph  [shapes/*.ttl, loaded via shapes_manifest.ttl]
      |                                      |
      v                                      |
 (entail_hierarchy)                          |
   adds: x a Patient  =>  x a Person         |
   adds: sub-property => super-property      |
   NOTHING else: no domain/range typing      |
      |                                      |
      +------------------+-------------------+
                         v
              (pySHACL, inference = none)
                         |
            +------------+-------------+
            v            v             v
        Violation     Warning         Info        (severity is part of the shape)
            |
            v
   conforms = False  -->  the gate stops the load / the write / the API call
```

The closure is deliberately narrow. If SHACL were allowed to infer types from `rdfs:range`, a relationship pointing at the wrong kind of thing would be *made* valid by the inference. See anti-pattern 5 in [anti-patterns.md](anti-patterns.md). Code: `core/shacl_validator.py`.

## 5. Competency-question flow

```text
 BUSINESS QUESTION            "Is any patient prescribed a drug they are allergic to?"
      |
      v
 COMPETENCY QUESTION          CQ10 (list) and CQ19 (yes/no)
      |
      v
 ONTOLOGY MODEL               Prescription, Allergy, Medication
      |                       prescribedFor, containsMedication, hasAllergy, allergyToMedication
      v
 RDF DATA                     PrescriptionDiabetesBob, AllergyBobAmoxicillin, ...
      |
      v
 SPARQL                       sparql/cq10_medication_allergy_conflicts.rq
      |
      v
 EXPECTED RESULT              written by hand BEFORE running: none on clean data
      |
      v
 TEST                         mutate the graph (add a real conflict) -> the query must now find it
```

The mutation step is what makes an empty answer meaningful. Full table: [competency-questions.md](competency-questions.md).

## 6. RDF to Neo4j projection

```text
 [ontology/healthcare_schema.ttl] + [data/sample_data.ttl]   (merged by core/dataset.py)
      |  rdflib
      v
 {SHACL gate}  invalid RDF -> ProjectionRejected, nothing is written
      |
      v
 (entail)      superclass labels, inverse edges, super-properties          marked "inferred"
      |
      v
 Projection (pure data, deterministic, fingerprinted)
      |   node identity     = the IRI            (never the name)
      |   labels            = class + all superclasses    (MATCH (p:Person) works)
      |   asserted types    = kept separately from inherited labels
      |   edges             = by IRI with explicit endpoint labels
      |   literals          = typed, multi-valued kept as lists
      v
 (writer)  MERGE on IRI; stale nodes pruned; every DELETE scoped to projection labels
      |
      v
 Neo4j   [projection labels]   |   [agent memory labels]   |   [document/embedding labels]
              rebuilt freely         never touched              never touched
```

Verified live against Neo4j Desktop ([NEO4J_DESKTOP_LIVE_VERIFICATION.md](NEO4J_DESKTOP_LIVE_VERIFICATION.md)); the loader refuses a database that already holds nodes from another graph domain ([neo4j-desktop.md](neo4j-desktop.md)). Run the planning half with no database: `python scripts/validate.py` step 4 (`124 nodes, 58 classes, 476 relationships`). Tests: `tests/test_graph_projection.py`, `tests/test_projection_oracle.py`, `tests/test_neo4j_sync.py`.

## 7. Healthcare interoperability

```text
   other systems                                this project
   -------------                                ------------
   EHR / lab / pharmacy      codes:   ICD-10, SNOMED CT, LOINC, RxNorm
          |                                  |
          |  never copied in                 v
          |                    CodeConcept { codeSystem (anyURI), codeValue, codeDisplay }
          |                                  ^
          |  bind by reference               |  hasCode
          +--------------------------------> Diagnosis | Observation | Medication
                                             |
   shared vocabularies (SKOS):  administrative gender, encounter type (AMB, IMP, EMER, VR),
                                specialty, medication category
                                             |
                                             v
   RDF in, RDF out:  Turtle / RDF-XML / N-Triples,  SPARQL endpoint,  SHACL report  (HTTP)
```

What is implemented: the code-binding pattern, SKOS vocabularies, the check-digit rules for SNOMED CT and LOINC, standards-style identifiers (system + value + type) and RDF interchange. What is **not**: a FHIR or HL7 v2 mapper. The model deliberately mirrors FHIR's shape (Encounter, Condition, Observation, Medication) so that a mapper is a table, not a redesign; that table is an exercise, not shipped code. See [book-chapter-mapping.md](book-chapter-mapping.md), chapter 12.

## 8. RAG architecture (optional layer)

```text
 question
    |
    v
 {guardrails}  injection / PII patterns          enterprise/guardrails.py
    |
    v
 (hybrid_retrieve)   candidate ontology concepts
    |-- lexical channel   names, synonyms, token overlap          no model needed
    |-- graph channel     keyword hits + neighbourhood traversal
    |-- vector channel    embeddings (OpenAI) + Neo4j vector index
    v
 (rerank + error budget)    which channel the evidence rests on
    |
    v
 ontology context  ---->  (generator: LLM writes SPARQL or Cypher using THESE terms)
                                   |
                                   v
                          {validators: syntax, allow-list, ontology terms, safety policy}
                                   |
                                   v
                          (read-only execution)  ---> result rows
                                   |
                                   v
                          provenance: query + concepts + rows + retrieval trace
```

"Retrieval" here finds *ontology concepts to ground a query*, not passages of prose. The answer is only as good as the rows. See [core-vs-ai-architecture.md](core-vs-ai-architecture.md) section 6.

## 9. Agent architecture (optional layer)

```text
 START
   |
   v
 memory_load --> planner --> ontology --> query --> validation ----+
                                            ^           |          |
                                            +-- retry --+          | fails after retries
                                                        | ok       v
                                                        v      respond_failed ---+
                                                  {human_gate}                    |
                                         risky? -> interrupt: approve / reject    |
                                                        |                         |
                                          rejected -----+--> END                  |
                                                        | approved                |
                                                        v                         |
                                                    execution                     |
                                                        |                         |
                                                        v                         v
                                                  {abstention} <------------------+
                                       refuse: no provenance / low confidence /
                                               execution failed / human rejected
                                                        |
                                                        v
                                                    response --> END
                                           (structured answer + citations + trace)
```

Two nodes can stop the flow without an answer: the human gate and abstention. That is a feature (see [core-vs-ai-architecture.md](core-vs-ai-architecture.md) section 8). Code: `agents/graph.py`, `agents/nodes/`, `enterprise/abstention.py`.
