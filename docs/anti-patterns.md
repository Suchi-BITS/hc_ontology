# Anti-patterns: eight mistakes this project demonstrates or avoids

Each entry has the same shape: **the mistake**, **why it is tempting**, **what goes wrong**, **what this project does instead**, **the evidence** (a test or a file you can run), and **trade-offs**. Several of these were real defects in an earlier version of this repository, found by the audit; where that is so, it says so. A mistake you have seen fail is worth more than a rule you have been told.

| # | Anti-pattern | Where it was a real defect | Evidence |
|---|---|---|---|
| 1 | Ontology as database schema | Yes (audit) | `tests/test_ontology.py` |
| 2 | Strings for dates | Yes | `test_no_temporal_property_is_a_string` |
| 3 | Names as identity | Yes | `test_node_identity_is_the_iri_not_the_name` |
| 4 | OWL for validation | Avoided | `docs/ontology-engineering.md` section 10 |
| 5 | SHACL for inference | Yes, found while building | `test_audit_regressions.py` |
| 6 | Dropping RDF semantics in the projection | Yes (audit) | `tests/test_graph_projection.py` |
| 7 | Trusting client-provided roles | Yes (audit) | `test_a_forged_admin_role_header_grants_nothing` |
| 8 | Unsafe destructive graph operations | Yes (audit) | `test_reset_is_refused_unless_development_and_explicitly_enabled` |

---

## 1. Ontology as database schema

**The mistake.** Modelling tables: one class per table, one property per column, a class hierarchy invented to group things the way a menu groups dishes.

**Why tempting.** You already have a schema; translating it feels like progress, and it is how most people first meet the word "class".

**What goes wrong.** An ontology says what things *are* and how they relate, in a way that supports inference. A schema says how to store records. In the earlier version, medications were created as subclasses of category classes (`Analgesic`, `Antidiabetic`), so a medication's identity and its therapeutic category were the same fact. A seed script then created Metformin and Insulin as `Analgesic`, and nothing in the model could object, because "being an analgesic" was just a table the row had been put in.

**What this project does.** A medication is a `Medication`; its category is *data* (`medicationCategory` pointing at a SKOS concept). "Antidiabetic medication" is a **defined class**: anything with that category is classified into it by a reasoner. A test removes Metformin's category and shows the antidiabetic query lose Alice, which proves the answer comes from a modelled fact.

**Evidence.** `docs/ontology-engineering.md` sections 2, 11 and 15; `test_removed_modeling_would_break_the_antidiabetic_query`; `test_committed_ontology_classifies_medications_like_the_reference`.

**Trade-offs.** A modelled category is one more join than a subclass, and the reasoner is optional machinery. In return, a drug can have several categories (Aspirin is both Analgesic and Antiplatelet) and a wrong one is a data error you can detect, not a modelling error you cannot.

## 2. Strings for dates

**The mistake.** `"2026-03-01"` or `"1st March"` as a `xsd:string`.

**Why tempting.** It round-trips through every tool without thought.

**What goes wrong.** A string date cannot be ordered, compared or checked. `"2026-13-40"` is as valid as any other string. Worse, a datetime without a zone is ambiguous: `09:30` in whose morning?

**What this project does.** Birth, onset and prescription dates are `xsd:date`; instants (encounter start/end, observation time) are `xsd:dateTime` **with a time zone**, and the shape rejects one without. The data contract rejects impossible dates, future birth dates, an encounter ending before it starts, and an encounter before the patient was born, before any RDF exists.

**Evidence.** `test_no_temporal_property_is_a_string`; `data/sample_instances/invalid_encounter_no_timezone.ttl`; fixtures `patient_impossible_date`, `encounter_no_timezone`, `encounter_ends_before_start` in `data/invalid_source/`.

**Trade-offs.** Typed dates are less forgiving at the import boundary: messy source data must be cleaned or rejected, not stored. That is the point. Also note that time zones do not fix wrong clocks.

## 3. Names as identity

**The mistake.** Using a person's or thing's name as its key: `MERGE (p {name: "John Doe"})`.

**Why tempting.** Names are readable, and in a demo every name is unique.

**What goes wrong.** Two patients called John Doe become one node, and a prescription lands on the wrong chart. Relationship writes that match endpoints by name alone, without a label, can attach an edge to a node of a different kind. The old exporter did both.

**What this project does.** Identity is the **IRI**. The sample data uses ids (`PatientJohn`), the projection merges on the IRI, relationships connect by IRI with explicit endpoint labels, a uniqueness constraint is declared on it, and the data contract also flags the same person entered twice under two ids (`duplicate_person`, `duplicate_mrn`). Business identifiers (an MRN, a license number) are `Identifier` nodes with a system, a value and a type, never the key.

**Evidence.** `test_node_identity_is_the_iri_not_the_name`, `test_nodes_are_merged_on_iri_not_on_name`, `test_schema_declares_iri_uniqueness`; `docs/ontology-engineering.md` section 6.

**Trade-offs.** IRIs are less pleasant to read, so the projection also stores a `name` property for display. The discipline is: show names, key on IRIs.

## 4. Using OWL for validation

**The mistake.** Writing `minCardinality 1` on `dateOfBirth` and expecting a patient without one to be rejected.

**Why tempting.** It looks like a constraint, and it reads like the rule you mean.

**What goes wrong.** OWL reasons under the **open-world assumption**: a missing birth date means "not yet known", not "invalid". A reasoner will happily conclude the patient *has* some birth date it has not been told. Nothing is ever rejected, and the file still loads.

**What this project does.** OWL carries meaning only: the class hierarchy, property characteristics, inverses, disjointness, a few defined classes. "Required", "exactly one", "must be a date with a zone" are SHACL, which uses closed-world checking on the data you actually have. `docs/ontology-engineering.md` section 10 lists, constraint by constraint, which layer owns it, and the README has a short table ("SHACL vs OWL").

**Evidence.** `shapes/` (for example `patient_shapes.ttl` demands a birth date); `data/sample_instances/invalid_patient_missing_dob.ttl` fails with `Patient must have a dateOfBirth.`; `tests/test_shape_contracts.py`.

**Trade-offs.** Two languages to learn instead of one, and you must keep them in step: a property the ontology calls functional is checked for single-valuedness by a shape, not by OWL.

## 5. Using SHACL for inference

**The mistake.** Letting the validator derive facts, then validating the derived graph. pySHACL can run RDFS inference before validation; it looks harmless.

**Why tempting.** It makes subclass-aware shapes (`Patient` is a `Person`) work with one flag.

**What goes wrong.** Full RDFS inference also applies `rdfs:range` and `rdfs:domain` as **typing rules**. If a prescription points `prescribedBy` at a nurse, the range says "doctor", so inference *concludes the nurse is a doctor*, and the doctor-only shape passes. The validator repaired the very error it exists to catch. This was found while building the test suite: wrong-target relationships passed.

**What this project does.** Validation runs with `inference="none"` after a deliberately narrow closure (`entail_hierarchy`): subclass and sub-property only, no domain/range typing. Inference that has a place in the pipeline (OWL classification, inverse edges) is done by the OWL reasoner or the projection and is named as such. Wrong-kind relationships are caught by the shapes, and an OWL reasoner independently flags them as inconsistent.

**Evidence.** `core/shacl_validator.py` (`entail_hierarchy`); `test_owl_reasoner_catches_a_relationship_used_by_the_wrong_kind_of_thing`; `docs/testing-strategy.md` section 4.

**Trade-offs.** Shapes must name the superclass explicitly where they mean it, because nothing is inferred behind their back. That is more typing, and a lot more honesty.

## 6. Dropping RDF semantics in the graph projection

**The mistake.** Exporting RDF to a property graph as "nodes with a label and some strings".

**Why tempting.** The first working export is always the simplest one.

**What goes wrong.** The old exporter used only the first `rdf:type` as a label, so `MATCH (p:Person)` returned nothing even though every doctor and patient is a person. It kept only the first value of a multi-valued property, stringified typed literals, upper-cased relationship names into run-together words (`HASDIAGNOSIS`), and ignored inverse and super-properties. A property graph that cannot answer what the ontology says is a different, worse model with the same name.

**What this project does.** The projection is a deterministic function of the RDF: IRI identity, **all** superclass labels, asserted types kept distinct from inherited ones, typed literals, multi-valued properties as lists, inferred inverse and super-property edges marked as inferred, and an `INSTANCE_OF`/`SUBCLASS_OF` structure for the model itself. Invalid RDF is rejected by the SHACL gate rather than projected. It is also fingerprinted, so an unchanged input gives an unchanged output.

**Evidence.** `test_individuals_carry_all_superclass_labels`, `test_asserted_types_stay_distinguishable_from_inherited_labels`, `test_entailed_inverse_and_superproperty_edges_are_present_and_marked`; `tests/test_projection_oracle.py` (an independent oracle for the projection, with seeded defects, each detected for the right reason); `docs/semantic-authority-and-graph-projection.md`.

**Trade-offs.** The projection has more nodes, more labels and more edges than a naive export, and rebuilding it is a sync, not an append. The graph is *derived*: you never edit it by hand, you edit the RDF and re-project.

## 7. Trusting client-provided roles

**The mistake.** Reading `X-Role: admin` from the request and acting on it.

**Why tempting.** It makes role-based access control demonstrable in ten lines.

**What goes wrong.** Any client can send any header. The earlier API accepted `X-Role` and `X-Tenant-ID` as facts, so anyone who knew the header names was an administrator of any tenant.

**What this project does.** Identity, role and tenant come from a **server-side credential** (the API key is hashed on disk; only the hash is stored). Authentication says who you are; authorization checks a server-side permission table; the tenant is the identity's and a request naming another tenant is refused with 403. A forged role header is ignored in both directions and logged for investigation. The agent's Principal and tenant context are derived from the same authenticated identity.

**Evidence.** `test_a_forged_admin_role_header_grants_nothing`, `test_a_forged_role_cannot_even_elevate_a_real_admin_to_platform_admin`, `test_the_role_header_is_ignored_in_both_directions`; `docs/security-architecture.md`.

**Trade-offs.** You must provision credentials (`python scripts/dev.py credential add ...`), and a development convenience mode exists that is announced at startup and refuses to run outside development. API keys are a floor, not a ceiling: a real deployment would put OIDC in front.

## 8. Unsafe destructive graph operations

**The mistake.** `MATCH (n) DETACH DELETE n` as the "reset" step, run from a seed script, a startup hook or an HTTP endpoint.

**Why tempting.** Idempotent seeding is easiest if you start from empty.

**What goes wrong.** The same database holds agent memory, uploaded documents and embeddings. A reset that deletes everything destroys data the ontology never owned. Exposed over HTTP, it is a one-request outage; behind a flag that defaults on, it is a matter of time.

**What this project does.** Three layers. The projection is scoped by label and only ever prunes **projection labels**, so memory and documents are untouched by construction. Resetting the projection is refused unless the environment is development *and* an explicit flag is set. The seed script is a development tool with no HTTP route. Generated queries run in a read-only transaction behind a structural allow-list, so even a clever model cannot write.

**Evidence.** `test_every_delete_is_scoped_to_projection_labels`, `test_sync_only_touches_projection_labels`, `test_reset_is_refused_unless_development_and_explicitly_enabled`, `test_reset_in_development_removes_only_projection_labels`; `core/graph_domains.py`; `docs/security-and-configuration.md`.

**Trade-offs.** "Start clean" needs one more word (`--reset-projection`) and a development environment; production deployments change data by a scoped, repeatable sync. Neo4j Community has no per-database roles, so the read-only transaction and the allow-list stand in for a restricted database user; this is not verified against a live server here.

---

## A short test for your own project

Ask of any design: *If this assumption is wrong, does something reject it, or does something silently accept it?* Anti-patterns 1, 2, 3 and 6 are all "silently accept". Anti-pattern 4 is a tool that accepts by design. Anti-pattern 5 is a tool that accepts by being helpful. Anti-patterns 7 and 8 are "accept from whoever asks". Every fix above is the same fix: put a checkable rule at the boundary, and write the test that shows it firing.
