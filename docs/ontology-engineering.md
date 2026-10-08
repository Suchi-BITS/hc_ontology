# Ontology Engineering Guide

This document explains how the healthcare ontology is modeled and why. It is written to be reusable as book material: each section states a modeling problem, the decision, and the trade-off.

**Scope statement.** This is an *educational reference ontology* for hospital care. It is not a clinical system and must not be used with real patient data. It is deliberately small: 56 classes, 86 object properties (27 inverse pairs), 74 datatype properties.

Source of truth: [`scripts/generate_hc_ontology.py`](../scripts/generate_hc_ontology.py) writes `ontology/healthcare_schema.ttl`: the schema (TBox) and its controlled vocabularies, and nothing else. The synthetic instances (ABox) are a separate artifact, `data/sample_data.ttl`, built by `scripts/generate_sample_data.py`; see [schema-and-sample-data.md](schema-and-sample-data.md). A test fails if a committed file differs from its generator's output, so edit the generator, never the Turtle.

---

## 1. Modeling principles

1. **Classes are kinds of things; properties relate things; vocabularies list allowed values.** A medication's therapeutic category is a value from a list, so it is a property pointing to a controlled-vocabulary concept, not a subclass.
2. **OWL carries meaning. SHACL carries rules about data.** OWL axioms are used where a reasoner can derive something useful. "This field is required" is a data-quality rule and lives in SHACL (section 10).
3. **Identity is not a label.** An entity's IRI identifies it. Names are display attributes. Business identifiers and external codes are modeled explicitly (sections 6 and 8).
4. **Model the record, not the disease.** A `Diagnosis` individual is one clinician's finding about one patient at one time. The *kind* of disease is its code. Sharing one "Diabetes" individual between patients was the old model's central error.
5. **Do not add a class to increase the count.** Each class below has a justification (section 3).
6. **Stay bounded.** Hospital administration and a simple clinical core. Anything else is an extension (section 12).

## 2. From database schema to ontology: current → problems → target

| Aspect | Before (schema in OWL) | After |
|---|---|---|
| Specialty | `Cardiologist ⊑ Doctor`, ten `*Department` subclasses | `Doctor` + `hasSpecialty` → `Specialty` concept (SKOS) |
| Medication kind | `Analgesic`, `Antibiotic`, … subclasses; seed code made *Metformin* an `Analgesic` | `Medication` + `medicationCategory` → `MedicationCategory` concept; `AntidiabeticMedication` is a *defined* class inferred by a reasoner |
| Care episode | `Appointment`, `Admission`, `Discharge`, `EmergencyCase`, three `*Record` subclasses, no common concept | one `Encounter` with `encounterType`; `Appointment` is the *plan* and may be fulfilled by an `Encounter` |
| Clinical facts | `Diagnosis` only, code as a string | `Condition` → `Diagnosis`; `Observation` (value, unit, time); `Procedure`; all coded with `hasCode` |
| Relations | hand-written pairs (`hasDiagnosis`/`diagnosisForPatient`) with no link | `owl:inverseOf`, sub-properties, one transitive property |
| Dates | `xsd:string` everywhere | `xsd:date` for calendar dates, `xsd:dateTime` with offset for instants |
| Identity | names; empty `personId`/`patientNumber` | opaque IRIs + `Identifier` (system, value, type, assigner) |
| Terminology | `diagnosisCode "I10"` | `CodeConcept` (codeSystem, codeValue, codeDisplay) |
| Annotations | 12 of 75 classes labeled | every class has a label and a definition; every property has a label and comment |
| "Required" fields as OWL | 20 cardinality restrictions used as "required field" rules (they do not validate under the open-world assumption) | removed; enforced by SHACL |
| Disjointness | `Patient ⊥ Doctor ⊥ Nurse …`; `Surgery ⊥ Procedure` | roles may overlap; `Surgery ⊑ Procedure`; disjointness only between truly distinct categories |

## 3. The healthcare core and why each class exists

| Class | Justification | Decision on the candidate list |
|---|---|---|
| `Person`, `Patient`, `Practitioner` | People are the actors. `Practitioner` is the range of `participatesIn` and the parent of `Doctor`, `Nurse`, `Pharmacist`, `Technician`. | `Practitioner` added. |
| `Organization`, `Hospital`, `Department` | Needed as the assigner of identifiers and the provider of encounters; `Hospital` and `Department` are both organizations. | `Organization` added; `HealthcareFacility` **not** added (it would duplicate `Hospital` in this scope). |
| `Location`, `Ward`, `Room`, `Bed` | Physical containment is a real reasoning case (transitive `partOfLocation`) and the place of an encounter. | `Location` added. |
| `Encounter` | The pivotal clinical concept: ties patient, practitioners, time, setting, diagnoses, observations, procedures together. | Added. |
| `Condition`, `Diagnosis` | A `Condition` is a recorded health problem (can exist before a formal diagnosis); a `Diagnosis` is a condition established by a clinician. | Both kept: `Diagnosis ⊑ Condition`. |
| `Observation`, `VitalSign`, `DiagnosticResult` | Measurements with value, unit, time, and code. A test result *is* an observation. | `Observation` added; `LabResult` replaced by `DiagnosticResult ⊑ Observation`. |
| `Procedure`, `Surgery` | Discrete actions. | `Surgery ⊑ Procedure` (was disjoint from it). |
| `Medication`, `Prescription` | A drug concept, and the order for it. | `MedicationRequest` **not** added: `Prescription` is that concept (FHIR `MedicationRequest`). |
| `Allergy` | A patient's adverse reaction to a medication. | `AllergyIntolerance` **not** added: `Allergy` is that concept. |
| `CarePlan` | Retained; used by sample data. | Kept as is. |
| `Identifier`, `CodeConcept` | Business identifiers and external-terminology bindings. | Added (sections 6, 8). |
| `Specialty`, `AdministrativeGender`, `EncounterType`, `MedicationCategory` | Controlled vocabularies (section 7). | Added. |
| `DiagnosticTest`, `LaboratoryTest`, `ImagingStudy` | An MRI is not a laboratory test; both are diagnostic tests. | `DiagnosticTest` and `ImagingStudy` added. |

Retained from the original (administrative extension, intentionally thin): `InsurancePolicy`, `InsuranceClaim`, `Billing`, `Invoice`, `Vaccination`, `MedicalDevice`, `Ambulance`, `ClinicalNote`, `MedicalRecord`, and the treatment-modality subclasses (see below).

**Why treatment modalities stay subclasses.** `MedicationTreatment`, `PhysicalTherapy`, `RadiationTherapy`, `Chemotherapy`, `SurgicalTreatment` are different *kinds* of intervention with different related entities (a surgical treatment involves a `Surgery`). That is a legitimate class hierarchy. Specialty was different: a cardiologist is a doctor *with a specialty*, not a different kind of entity.

## 4. Encounter

```
Patient --hasEncounter--> Encounter <--participatesIn-- Practitioner
                           |  |  |
                           |  |  +--involvesProcedure--> Procedure
                           |  +-----includesObservation--> Observation
                           +--------diagnoses-----------> Condition
Appointment --fulfilledBy--> Encounter        Encounter --encounterType--> EncounterType (SKOS)
Encounter --encounterLocation--> Location     Encounter --serviceProvider--> Organization
```

Design points:

* **Appointment vs Encounter.** An appointment is a plan; an encounter is what happened. They are disjoint, linked by `fulfilledBy`. A no-show is an appointment with no encounter.
* **`encounterType` is a property, not subclasses.** `Admission`, `EmergencyCase` and `Discharge` used to be unrelated classes. Setting is a value (ambulatory, inpatient, emergency, virtual), so it is a SKOS concept. Where classification by setting is useful, a **defined class** is used: `InpatientEncounter ≡ Encounter ⊓ (encounterType value Inpatient)`; the reasoner classifies `Encounter006` into it. A discharge is simply the end of an inpatient encounter (`encounterEnd`).
* **Names.** The relationships are named for what they mean, not `hasX`: `participatesIn`, `diagnoses`, `includesObservation`, `involvesProcedure`. The patient-level `hasObservation` already existed (patient → observation), so the encounter-level link is `includesObservation`.
* **Limitation.** A participant's *role* in an encounter (attending, consultant) is an n-ary relationship and is not modeled; add an `EncounterParticipation` class if needed.

## 5. Specialty modeling

`Cardiologist ⊑ Doctor` fails three tests:

1. **Role vs type.** Being a cardiologist is a qualification a doctor holds, not a different kind of entity. A doctor with two specialties would need two classes.
2. **Explosion.** Every specialty adds classes to `Doctor` *and* to `Department`.
3. **Closed world in an open-world language.** Adding a specialty should be a data change, not a schema change.

Decision: `hasSpecialty` (domain: `Practitioner` or `Department`) → `Specialty`, where `Specialty` is an OWL class that is a subclass of `skos:Concept`, and each specialty (`SpecialtyCardiology`, …) is an individual in a `skos:ConceptScheme`. The class exists **only to type the vocabulary** so domains, ranges and SHACL `sh:class` checks stay precise; there is no `Specialty` hierarchy of practitioners. Specialties may later gain `skos:broader` links (for example cardiology → internal medicine) without touching the class model.

When a subclass *is* right: the original `Treatment` subclasses, `Surgery ⊑ Procedure`, `Diagnosis ⊑ Condition`.

## 6. Identifiers and URI strategy

Separate five things that the old model mixed:

| Concern | Modeled as | Example |
|---|---|---|
| Entity identity | the IRI (opaque, stable, never reused) | `hc:PatientJohn` |
| Display name | `firstName`, `lastName`, `rdfs:label`, `hospitalName` | "John Doe" |
| Business identifier | `Identifier` (system + value + type + assigner) | MRN `MRN-000123` issued by City Hospital |
| Clinical identifier | an `Identifier` with a type | license `DOC1001` |
| External code | `CodeConcept` | ICD-10 `I10` |

`Identifier` has `identifierSystem` (`xsd:anyURI`), `identifierValue`, `identifierType`, `identifierAssigner`. An identifier value is only unique **within its system**, which is why the system is part of it. Local record numbers scoped to their own record (`appointmentId`, `prescriptionNumber`, …) stay simple strings.

**URI strategy.** Current namespace: `http://example.org/healthcare-hospital.owl#`. It is kept unchanged so existing shapes, queries and fixtures keep working. For a real deployment: separate schema and data namespaces (for example `https://example.org/hc/ontology/` and `https://example.org/hc/id/`), use slash IRIs, make instance IRIs opaque (`…/id/patient/7f3a…`, never derived from a name), and version the ontology with `owl:versionIRI`. The sample individuals keep readable local names (`PatientJohn`) for teaching; the book should say so explicitly. This version is recorded as `owl:versionInfo 2.0.0`.

## 7. Controlled vocabularies (SKOS)

SKOS is used where the concept is **a list of allowed values**, and not elsewhere.

| Vocabulary | Why SKOS | Scheme |
|---|---|---|
| Specialty | open, extensible list; may get broader/narrower | `SpecialtyScheme` |
| Administrative gender | small fixed list used for record keeping (male, female, other, unknown) | `AdministrativeGenderScheme` |
| Encounter type | setting codes (AMB, IMP, EMER, VR) | `EncounterTypeScheme` |
| Medication category | a drug may have several (aspirin: analgesic and antiplatelet) | `MedicationCategoryScheme` |

Each concept has `rdfs:label`, `skos:prefLabel`, `skos:inScheme`, and (where a standard code exists) `skos:notation`. Only the SKOS terms used are referenced; SKOS is not copied into the file.

Deliberately **not** SKOS: `appointmentStatus`, `treatmentStatus`, `clinicalStatus`, `bloodGroup`, `paymentStatus` remain strings checked by SHACL `sh:in`/`sh:pattern`. Converting every enumeration to SKOS would add ceremony without teaching more. Condition category and other administrative classifications are listed as extensions.

## 8. Healthcare codes: a safe binding pattern

No terminology is embedded. A `CodeConcept` points at one:

```turtle
hc:Icd10_I10 a hc:CodeConcept ;
    hc:codeSystem  "http://hl7.org/fhir/sid/icd-10"^^xsd:anyURI ;
    hc:codeValue   "I10" ;
    hc:codeDisplay "Essential (primary) hypertension" .

hc:DiagnosisHypertension a hc:Diagnosis ;
    hc:hasCode hc:Icd10_I10, hc:Snomed_38341003 .   # several codings are allowed
```

`hasCode` applies to `Condition`, `Observation`, `Medication`, `Procedure`, `DiagnosticTest`. Systems used in the samples: ICD-10 (diagnoses), LOINC (observations and tests), RxNorm (medications), SNOMED CT (a few identifiers). The sample contains only identifiers and short display text for a dozen codes; **licensed terminologies (SNOMED CT, parts of LOINC and RxNorm distribution terms) must be obtained from their owners**. To integrate one: load it as its own graph/SKOS scheme, then replace or complement `CodeConcept` individuals with links (`skos:exactMatch`) to the external concept IRIs; no change to the core classes is needed. A query can then ask "patients with any ICD-10 E11 diagnosis" by system and code (see `tests/test_ontology.py`).

## 9. Temporal modeling

| Datatype | Used for | Why |
|---|---|---|
| `xsd:date` | `dateOfBirth`, `onsetDate`, `abatementDate`, `diagnosisDate`, `prescriptionDate`, `testDate`, `invoiceDate`, `recordCreatedDate` | A calendar date; no time of day; **no time zone** (a birthday is not an instant) |
| `xsd:dateTime` **with offset** | `encounterStart/End`, `scheduledStart`, `effectiveDateTime`, `performedDateTime` | These are instants; without an offset they are ambiguous |
| `xsd:gYear` | evaluated, not used | No current property needs "year only"; add one (for example a qualification year) when needed |
| `xsd:time` | evaluated, not used | A time of day without a date or zone is rarely useful (`appointmentTime` was replaced by `scheduledStart`) |

Time zones are enforced by SHACL (`sh:pattern` on the lexical form) because OWL cannot require an offset. **Known OWL 2 limitation:** `xsd:date` is *not* in the OWL 2 datatype map, so OWL 2 reasoners such as HermiT refuse files that use it. The ontology keeps `xsd:date` because it is the correct type for RDF, SHACL and SPARQL; the reasoner tests therefore run on a *reasoner view* with date literals and `xsd:date` ranges removed. If your pipeline must classify directly with a DL reasoner, either use `xsd:dateTime` for those fields or strip dates for reasoning, as the tests do. `xsd:dateTimeStamp` (offset required, inside the OWL 2 map) is an alternative for instants; it was not used because rdflib/SPARQL tooling treats it less uniformly.

## 10. OWL vs SHACL responsibilities

| Concern | Tool | Example here |
|---|---|---|
| Class hierarchy, classification | OWL | `Diagnosis ⊑ Condition`; `AntidiabeticMedication` defined by category |
| Inverse, transitive, sub-property, functional | OWL | `hasEncounter ⇄ encounterForPatient`; `partOfLocation` transitive; `hasDiagnosis ⊑ hasCondition` |
| Disjoint categories | OWL | `Encounter ⊥ Appointment` |
| Required fields, cardinality of *data* | SHACL | patient must have `dateOfBirth` |
| Datatype, pattern, value lists, time-zone presence, ordering | SHACL | `encounterStart ≤ encounterEnd`; blood group pattern |
| Cross-entity business rules | SHACL (`sh:sparql`) | no prescription of an allergen; numeric observation needs a unit |
| "Belongs to exactly one" | SHACL on inverse path | a `Condition` has at most one patient |

Why the old min-cardinality restrictions were removed: under the open-world assumption, `Patient ⊑ ≥1 hasMedicalRecord` does not flag a patient without a record; it makes a reasoner *assume* one exists. It validated nothing and misled readers. Functional properties (`dateOfBirth`, `encounterType`, `encounterForPatient`, …) remain, because "at most one" is real meaning: if two values are asserted a reasoner concludes they denote the same thing.

**Shape changes.** `PersonShape` now holds only datatype / max-count / class rules; role shapes own the `minCount` rules, so a path is no longer required at two severities. New shapes: Condition, Encounter, Observation, CodeConcept, Identifier (`shapes/clinical_shapes.ttl`, `shapes/diagnosis_shapes.ttl`). Gotcha: the OWL file written by Owlready2 types every string literal (`"x"^^xsd:string`), and rdflib does not treat `"x"` and `"x"^^xsd:string` as equal, so `sh:in`/`sh:hasValue` lists use the typed form.

**PatientJohn.** He failed `PatientShape` because the *data* was incomplete (no date of birth, gender). The ontology does not require a birth date and the shape rightly does (age drives dosing and identity matching), so the fix was in the sample data. The vacuous test (`total_violations >= 0`) was replaced by one that requires zero violations, plus a mutation test that removes a field and must fail.

## 11. Medication model and the seed-data defect

The error "Metformin and insulin are `Analgesic`" had a structural cause: the model forced the person writing seed code to choose a *class* for every drug, no antidiabetic class existed, and nothing checked the choice. Similar defects found by the same review:

* A single `DiagnosisDiabetes` individual attached to two patients.
* `dosage` modeled on `Medication` (a dose belongs to the order, now `Prescription.dosageInstruction`).
* `MRI`, `CTScan`, `XRay`, `Ultrasound` as subclasses of `LaboratoryTest`; results typed `LabResult`.
* A hypertension prescription containing only aspirin (now amlodipine, with aspirin on a separate order).
* `Surgery` declared disjoint from `Procedure`.

Fix: category is data (`medicationCategory`), drugs are plain `Medication` individuals, `AntidiabeticMedication` is inferred, and `services/seed_demo_data.py` no longer creates ontology individuals or rewrites the OWL file. Regression tests: `test_metformin_and_insulin_are_antidiabetics_not_analgesics`, `test_every_medication_has_a_category_and_no_therapeutic_class`, `test_a_diagnosis_record_belongs_to_exactly_one_patient`, `test_reasoner_classifies_antidiabetic_medication`.

## 12. Scope and extensibility

In scope: people and roles, organizations and locations, encounters, conditions, observations, procedures, treatments, medication and allergy, diagnostic tests, identifiers, code binding, and a thin administrative layer.

Out of scope (extension points, each additive): participant roles in encounters; medication administration and dispensing; drug-class allergy (needs a drug-class hierarchy); clinical care teams and referral; specimens; consent and provenance (PROV-O on imported facts); full terminology import; FHIR mapping (a documented mapping, not an import); multilingual labels.

How to extend: add the class or property to the generator with a label and comment, add a shape for its required data, add a fixture pair (valid, invalid), add tests, regenerate. Vocabulary values are added as data with no schema change.

## 13. Working with the ontology

```bash
python scripts/generate_hc_ontology.py                     # rewrite ontology/healthcare_schema.ttl
python scripts/generate_sample_data.py                      # rewrite data/sample_data.ttl (needs the schema)
python scripts/generate_hc_ontology.py --output out.ttl     # write elsewhere
pytest tests/test_ontology.py tests/test_clinical_shapes.py
```

The reasoner tests need Java and are skipped without it. Interactively, open the OWL file in Protégé; to run HermiT there, first remove `xsd:date` literals (section 9).

## 14. Known limitations

* Reasoning needs the date-stripped view (section 9).
* Inverse properties are declared, but data asserts one direction (Owlready2 stores a single triple); the other is inferred. Non-reasoning consumers (plain SPARQL over the file) see only the asserted direction. Owlready2 exposes the inferred direction in Python, and the Neo4j exporter writes both.
* Owlready2's `FunctionalProperty` returns scalars, not lists; service code uses `_as_list`.
* SHACL RDFS inference needs the schema triples in the data graph; `validate_ontology()` has them, uploaded instance-only files do not (see the header of `invalid_shared_diagnosis.ttl`).
* The Neo4j export keeps one type label per node (`Diagnosis`, not `Condition`) and does not export the class hierarchy.
* Sample code identifiers are illustrative; verify against the terminology owner before reuse.

## 15. Why this is now an ontology rather than a database schema

A database schema lists tables and columns and trusts the application to enforce meaning. This ontology states meaning in a form software can *use*:

* **It infers.** A reasoner classifies `Metformin` and `InsulinGlargine` as `AntidiabeticMedication`, `Encounter006` as an `InpatientEncounter`, derives `Encounter001`'s patient from `hasEncounter`, and places `Bed1` in `WardA` by transitivity. Nobody asserted those facts.
* **It separates identity from description.** IRIs identify; labels, identifiers and codes describe, and codes point to shared external meaning rather than local strings.
* **It models kinds correctly.** Specialty, category and setting are values, not tables; true is-a relationships (`Diagnosis ⊑ Condition`, `Surgery ⊑ Procedure`) are classes.
* **It is open-world and explicit about it.** "Required" rules moved to SHACL, where they validate; OWL keeps statements that remain true when information is missing.
* **It is checkable.** Consistency is verified by a reasoner and by tests that fail when a known modeling error returns.
* **It integrates.** Reused SKOS vocabularies and standard code systems let the same data join other graphs without a custom ETL step for each meaning.


## 16. Inverse properties: a decision for every object property

The audit counted object properties without a declared inverse and asked whether that is a defect. It is not, by itself. An inverse is a modelling commitment: it makes the reasoner (and the Neo4j projection) add an edge in the other direction for every asserted edge. That is valuable when someone really navigates from the other end, and noise when nobody does. So each of the 86 object properties was classified, and the decision recorded in [`ontology/inverse_decisions.csv`](../ontology/inverse_decisions.csv) (a test keeps it in step with the schema, and with the table below).

| Class | Meaning | What we did |
|---|---|---|
| **A** | Inverse strongly useful: a real question is asked from either end, or the reverse is needed for safety, provenance or organisation | Declared both directions. Data asserts only the forward one; the reasoner and the projection infer the other |
| **B** | Inverse potentially useful | Not declared. Reachable today with a SPARQL inverse path (`^hc:property`); promote to A when a competency question needs the reverse as a named term |
| **C** | Inverse unnecessary | Not declared: the reverse is never asked, or another property already carries it |
| **D** | Inverse semantically inappropriate | Not declared: the value is controlled-vocabulary or reference data, and an inverse would fan out from every concept to every record that uses it |

**Result.** 27 inverse pairs (54 properties): the 16 that existed, plus 11 added in this review: `hasAllergy`/`allergyForPatient`, `receivesTreatment`/`treatmentForPatient`, `underwentTest`/`testForPatient`, `diagnosedBy`/`madeDiagnosis`, `prescribedBy`/`issuedPrescription`, `containsMedication`/`containedInPrescription`, `orderedTest`/`orderedBy`, `containsWard`/`wardOfDepartment`, `worksInDepartment`/`hasStaffMember`, `reportsTo`/`supervises`, `managesDepartment`/`managedBy`. The other 32 properties keep no inverse, each with a recorded reason (14 B, 13 C, 5 D).

**Why those eleven.** Four make the patient-centred family consistent: a Patient already reaches encounters, observations, diagnoses, prescriptions and appointments *and* each of those reaches the Patient; allergies, treatments and tests did not, which is the navigation a safety review needs ("whose allergy is this?"). Four make provenance navigable from both ends: who made a diagnosis, who issued a prescription, who ordered a test, and which prescriptions contain a drug (the recall question). Three complete the staff organisation: who works in, who manages, and who supervises.

**Functional inverses.** The inverse is declared functional where the sample's meaning requires exactly one owner (a treatment, a test, an allergy has one patient; a ward belongs to one department; a test has one orderer). The reasoner confirms the sample data is still consistent under those constraints.

**What it costs.** The projection gains 35 inferred edges (441 to 476) and a new fingerprint; they are marked as inferred and never asserted in the data. The sample data and the shapes did not change.

| Property | Decision | Inverse | Why |
|---|---|---|---|
| `administeredBy` | B | none | Possible, not added: the reverse is reachable with a SPARQL inverse path (^hc:administeredBy); add it when a competency question needs the reverse as a named term. |
| `administrativeGender` | D | none | Inappropriate: the value is controlled-vocabulary or reference data. An inverse would give every concept an edge to every record that uses it (a fan-out), and the reverse is a SPARQL ^hc:administrativeGender away. |
| `allergyForPatient` | A | `hasAllergy` | Inverse strongly useful: navigation from either end is a real question (allergyForPatient <-> hasAllergy). Declared; the reasoner and the projection infer the other direction. |
| `allergyToMedication` | C | none | Unnecessary: the question 'who is allergic to X' is answered through the allergy node (^hc:allergyToMedication / ^hc:hasAllergy) and the safety rule already runs in that direction. |
| `appointmentAtHospital` | C | none | Unnecessary: one hospital in scope, and nothing navigates from the hospital back to its appointments. |
| `appointmentForPatient` | A | `hasAppointment` | Inverse strongly useful: navigation from either end is a real question (appointmentForPatient <-> hasAppointment). Declared; the reasoner and the projection infer the other direction. |
| `appointmentWithDoctor` | B | none | Possible, not added: the reverse is reachable with a SPARQL inverse path (^hc:appointmentWithDoctor); add it when a competency question needs the reverse as a named term. |
| `authoredBy` | B | none | Possible, not added: the reverse is reachable with a SPARQL inverse path (^hc:authoredBy); add it when a competency question needs the reverse as a named term. |
| `belongsToHospital` | A | `hasDepartment` | Inverse strongly useful: navigation from either end is a real question (belongsToHospital <-> hasDepartment). Declared; the reasoner and the projection infer the other direction. |
| `claimAgainstPolicy` | C | none | Unnecessary: administrative chain (billing, claim, policy) is read forward only. |
| `conditionSubject` | A | `hasCondition` | Inverse strongly useful: navigation from either end is a real question (conditionSubject <-> hasCondition). Declared; the reasoner and the projection infer the other direction. |
| `containedInPrescription` | A | `containsMedication` | Inverse strongly useful: navigation from either end is a real question (containedInPrescription <-> containsMedication). Declared; the reasoner and the projection infer the other direction. |
| `containsBed` | A | `locatedInRoom` | Inverse strongly useful: navigation from either end is a real question (containsBed <-> locatedInRoom). Declared; the reasoner and the projection infer the other direction. |
| `containsMedication` | A | `containedInPrescription` | Inverse strongly useful: navigation from either end is a real question (containsMedication <-> containedInPrescription). Declared; the reasoner and the projection infer the other direction. |
| `containsRoom` | A | `locatedInWard` | Inverse strongly useful: navigation from either end is a real question (containsRoom <-> locatedInWard). Declared; the reasoner and the projection infer the other direction. |
| `containsWard` | A | `wardOfDepartment` | Inverse strongly useful: navigation from either end is a real question (containsWard <-> wardOfDepartment). Declared; the reasoner and the projection infer the other direction. |
| `coveredByInsurance` | B | none | Possible, not added: the reverse is reachable with a SPARQL inverse path (^hc:coveredByInsurance); add it when a competency question needs the reverse as a named term. |
| `createdByDoctor` | B | none | Possible, not added: the reverse is reachable with a SPARQL inverse path (^hc:createdByDoctor); add it when a competency question needs the reverse as a named term. |
| `diagnosedBy` | A | `madeDiagnosis` | Inverse strongly useful: navigation from either end is a real question (diagnosedBy <-> madeDiagnosis). Declared; the reasoner and the projection infer the other direction. |
| `diagnosedIn` | A | `diagnoses` | Inverse strongly useful: navigation from either end is a real question (diagnosedIn <-> diagnoses). Declared; the reasoner and the projection infer the other direction. |
| `diagnoses` | A | `diagnosedIn` | Inverse strongly useful: navigation from either end is a real question (diagnoses <-> diagnosedIn). Declared; the reasoner and the projection infer the other direction. |
| `diagnosisForPatient` | A | `hasDiagnosis` | Inverse strongly useful: navigation from either end is a real question (diagnosisForPatient <-> hasDiagnosis). Declared; the reasoner and the projection infer the other direction. |
| `encounterForPatient` | A | `hasEncounter` | Inverse strongly useful: navigation from either end is a real question (encounterForPatient <-> hasEncounter). Declared; the reasoner and the projection infer the other direction. |
| `encounterLocation` | B | none | Possible, not added: the reverse is reachable with a SPARQL inverse path (^hc:encounterLocation); add it when a competency question needs the reverse as a named term. |
| `encounterType` | D | none | Inappropriate: the value is controlled-vocabulary or reference data. An inverse would give every concept an edge to every record that uses it (a fan-out), and the reverse is a SPARQL ^hc:encounterType away. |
| `followsCarePlan` | B | none | Possible, not added: the reverse is reachable with a SPARQL inverse path (^hc:followsCarePlan); add it when a competency question needs the reverse as a named term. |
| `fulfilledBy` | A | `fulfillsAppointment` | Inverse strongly useful: navigation from either end is a real question (fulfilledBy <-> fulfillsAppointment). Declared; the reasoner and the projection infer the other direction. |
| `fulfillsAppointment` | A | `fulfilledBy` | Inverse strongly useful: navigation from either end is a real question (fulfillsAppointment <-> fulfilledBy). Declared; the reasoner and the projection infer the other direction. |
| `generatesInvoice` | C | none | Unnecessary: administrative chain is read forward only. |
| `hasAllergy` | A | `allergyForPatient` | Inverse strongly useful: navigation from either end is a real question (hasAllergy <-> allergyForPatient). Declared; the reasoner and the projection infer the other direction. |
| `hasAppointment` | A | `appointmentForPatient` | Inverse strongly useful: navigation from either end is a real question (hasAppointment <-> appointmentForPatient). Declared; the reasoner and the projection infer the other direction. |
| `hasBilling` | B | none | Possible, not added: the reverse is reachable with a SPARQL inverse path (^hc:hasBilling); add it when a competency question needs the reverse as a named term. |
| `hasClinicalNote` | C | none | Unnecessary: a note is always reached through its record. |
| `hasCode` | D | none | Inappropriate: the value is an external-terminology concept. An inverse would connect every code to every diagnosis, observation and medication that uses it; reach the reverse with ^hc:hasCode. |
| `hasCondition` | A | `conditionSubject` | Inverse strongly useful: navigation from either end is a real question (hasCondition <-> conditionSubject). Declared; the reasoner and the projection infer the other direction. |
| `hasDepartment` | A | `belongsToHospital` | Inverse strongly useful: navigation from either end is a real question (hasDepartment <-> belongsToHospital). Declared; the reasoner and the projection infer the other direction. |
| `hasDiagnosis` | A | `diagnosisForPatient` | Inverse strongly useful: navigation from either end is a real question (hasDiagnosis <-> diagnosisForPatient). Declared; the reasoner and the projection infer the other direction. |
| `hasEncounter` | A | `encounterForPatient` | Inverse strongly useful: navigation from either end is a real question (hasEncounter <-> encounterForPatient). Declared; the reasoner and the projection infer the other direction. |
| `hasIdentifier` | C | none | Unnecessary: identifiers are looked up by system and value, not by walking back to a person. |
| `hasMedicalRecord` | B | none | Possible, not added: the reverse is reachable with a SPARQL inverse path (^hc:hasMedicalRecord); add it when a competency question needs the reverse as a named term. |
| `hasObservation` | A | `observationForPatient` | Inverse strongly useful: navigation from either end is a real question (hasObservation <-> observationForPatient). Declared; the reasoner and the projection infer the other direction. |
| `hasParticipant` | A | `participatesIn` | Inverse strongly useful: navigation from either end is a real question (hasParticipant <-> participatesIn). Declared; the reasoner and the projection infer the other direction. |
| `hasPrescription` | A | `prescribedFor` | Inverse strongly useful: navigation from either end is a real question (hasPrescription <-> prescribedFor). Declared; the reasoner and the projection infer the other direction. |
| `hasSpecialty` | D | none | Inappropriate: the value is controlled-vocabulary or reference data. An inverse would give every concept an edge to every record that uses it (a fan-out), and the reverse is a SPARQL ^hc:hasSpecialty away. |
| `hasStaffMember` | A | `worksInDepartment` | Inverse strongly useful: navigation from either end is a real question (hasStaffMember <-> worksInDepartment). Declared; the reasoner and the projection infer the other direction. |
| `hasVaccination` | B | none | Possible, not added: the reverse is reachable with a SPARQL inverse path (^hc:hasVaccination); add it when a competency question needs the reverse as a named term. |
| `identifierAssigner` | C | none | Unnecessary: nothing asks which identifiers an organization issued. |
| `includesObservation` | A | `observedDuring` | Inverse strongly useful: navigation from either end is a real question (includesObservation <-> observedDuring). Declared; the reasoner and the projection infer the other direction. |
| `includesProcedure` | B | none | Possible, not added: the reverse is reachable with a SPARQL inverse path (^hc:includesProcedure); add it when a competency question needs the reverse as a named term. |
| `involvesProcedure` | A | `performedDuring` | Inverse strongly useful: navigation from either end is a real question (involvesProcedure <-> performedDuring). Declared; the reasoner and the projection infer the other direction. |
| `involvesSurgery` | C | none | Unnecessary: a sub-property of includesProcedure; its reverse adds nothing the parent's would not. |
| `issuedPrescription` | A | `prescribedBy` | Inverse strongly useful: navigation from either end is a real question (issuedPrescription <-> prescribedBy). Declared; the reasoner and the projection infer the other direction. |
| `locatedInRoom` | A | `containsBed` | Inverse strongly useful: navigation from either end is a real question (locatedInRoom <-> containsBed). Declared; the reasoner and the projection infer the other direction. |
| `locatedInWard` | A | `containsRoom` | Inverse strongly useful: navigation from either end is a real question (locatedInWard <-> containsRoom). Declared; the reasoner and the projection infer the other direction. |
| `madeDiagnosis` | A | `diagnosedBy` | Inverse strongly useful: navigation from either end is a real question (madeDiagnosis <-> diagnosedBy). Declared; the reasoner and the projection infer the other direction. |
| `managedBy` | A | `managesDepartment` | Inverse strongly useful: navigation from either end is a real question (managedBy <-> managesDepartment). Declared; the reasoner and the projection infer the other direction. |
| `managesDepartment` | A | `managedBy` | Inverse strongly useful: navigation from either end is a real question (managesDepartment <-> managedBy). Declared; the reasoner and the projection infer the other direction. |
| `medicationCategory` | D | none | Inappropriate: the value is controlled-vocabulary or reference data. An inverse would give every concept an edge to every record that uses it (a fan-out), and the reverse is a SPARQL ^hc:medicationCategory away. |
| `observationForPatient` | A | `hasObservation` | Inverse strongly useful: navigation from either end is a real question (observationForPatient <-> hasObservation). Declared; the reasoner and the projection infer the other direction. |
| `observedDuring` | A | `includesObservation` | Inverse strongly useful: navigation from either end is a real question (observedDuring <-> includesObservation). Declared; the reasoner and the projection infer the other direction. |
| `orderedBy` | A | `orderedTest` | Inverse strongly useful: navigation from either end is a real question (orderedBy <-> orderedTest). Declared; the reasoner and the projection infer the other direction. |
| `orderedTest` | A | `orderedBy` | Inverse strongly useful: navigation from either end is a real question (orderedTest <-> orderedBy). Declared; the reasoner and the projection infer the other direction. |
| `partOfLocation` | C | none | Unnecessary: the specific containment pairs (containsRoom/locatedInWard, containsBed/locatedInRoom) carry the navigation; a general transitive inverse would only duplicate them. |
| `participatesIn` | A | `hasParticipant` | Inverse strongly useful: navigation from either end is a real question (participatesIn <-> hasParticipant). Declared; the reasoner and the projection infer the other direction. |
| `performedByDoctor` | B | none | Possible, not added: the reverse is reachable with a SPARQL inverse path (^hc:performedByDoctor); add it when a competency question needs the reverse as a named term. |
| `performedDuring` | A | `involvesProcedure` | Inverse strongly useful: navigation from either end is a real question (performedDuring <-> involvesProcedure). Declared; the reasoner and the projection infer the other direction. |
| `prescribedBy` | A | `issuedPrescription` | Inverse strongly useful: navigation from either end is a real question (prescribedBy <-> issuedPrescription). Declared; the reasoner and the projection infer the other direction. |
| `prescribedFor` | A | `hasPrescription` | Inverse strongly useful: navigation from either end is a real question (prescribedFor <-> hasPrescription). Declared; the reasoner and the projection infer the other direction. |
| `producesResult` | A | `resultOfTest` | Inverse strongly useful: navigation from either end is a real question (producesResult <-> resultOfTest). Declared; the reasoner and the projection infer the other direction. |
| `receivesTreatment` | A | `treatmentForPatient` | Inverse strongly useful: navigation from either end is a real question (receivesTreatment <-> treatmentForPatient). Declared; the reasoner and the projection infer the other direction. |
| `recordedBy` | B | none | Possible, not added: the reverse is reachable with a SPARQL inverse path (^hc:recordedBy); add it when a competency question needs the reverse as a named term. |
| `reportsTo` | A | `supervises` | Inverse strongly useful: navigation from either end is a real question (reportsTo <-> supervises). Declared; the reasoner and the projection infer the other direction. |
| `requiresTreatment` | A | `treatsDiagnosis` | Inverse strongly useful: navigation from either end is a real question (requiresTreatment <-> treatsDiagnosis). Declared; the reasoner and the projection infer the other direction. |
| `resultOfTest` | A | `producesResult` | Inverse strongly useful: navigation from either end is a real question (resultOfTest <-> producesResult). Declared; the reasoner and the projection infer the other direction. |
| `reviewedByDoctor` | B | none | Possible, not added: the reverse is reachable with a SPARQL inverse path (^hc:reviewedByDoctor); add it when a competency question needs the reverse as a named term. |
| `serviceProvider` | C | none | Unnecessary: one hospital in scope, and nothing navigates from the hospital back to its encounters. |
| `submitsClaim` | C | none | Unnecessary: administrative chain is read forward only. |
| `supervises` | A | `reportsTo` | Inverse strongly useful: navigation from either end is a real question (supervises <-> reportsTo). Declared; the reasoner and the projection infer the other direction. |
| `testForPatient` | A | `underwentTest` | Inverse strongly useful: navigation from either end is a real question (testForPatient <-> underwentTest). Declared; the reasoner and the projection infer the other direction. |
| `transportedBy` | C | none | Unnecessary: a single ambulance in the sample; no navigation from the vehicle. |
| `treatmentForPatient` | A | `receivesTreatment` | Inverse strongly useful: navigation from either end is a real question (treatmentForPatient <-> receivesTreatment). Declared; the reasoner and the projection infer the other direction. |
| `treatsDiagnosis` | A | `requiresTreatment` | Inverse strongly useful: navigation from either end is a real question (treatsDiagnosis <-> requiresTreatment). Declared; the reasoner and the projection infer the other direction. |
| `underwentTest` | A | `testForPatient` | Inverse strongly useful: navigation from either end is a real question (underwentTest <-> testForPatient). Declared; the reasoner and the projection infer the other direction. |
| `usesMedicalDevice` | C | none | Unnecessary: device use is read from the treatment. |
| `wardOfDepartment` | A | `containsWard` | Inverse strongly useful: navigation from either end is a real question (wardOfDepartment <-> containsWard). Declared; the reasoner and the projection infer the other direction. |
| `worksInDepartment` | A | `hasStaffMember` | Inverse strongly useful: navigation from either end is a real question (worksInDepartment <-> hasStaffMember). Declared; the reasoner and the projection infer the other direction. |

## 17. People and roles: Person, Practitioner, Patient

**The question.** `Patient`, `Doctor` and `Nurse` are subclasses of `Person`. Is "being a patient" a *kind* of person, which is what a subclass says, or a *role* a person plays?

**The model, as it stands.**

```text
Person
 +-- Patient                    a person receiving (or registered to receive) care
 +-- Practitioner               a person delivering care or clinical support
      +-- Doctor, Nurse, Pharmacist, Technician
```

`Patient` and `Practitioner` are **not disjoint**, and neither is a subclass of the other. In OWL a class is a set and an individual can belong to several, so one `Person` can be a `Doctor` and a `Patient` at once, with one IRI, one name and one birth date. Only the genuinely exclusive categories are declared disjoint: a person is not an organization, a location, an encounter or a medication.

**Is that defensible?** Yes, with one stated limit. Treating roles as overlapping types is a standard, honest simplification: it says what is true *now* without inventing structure. A role class per role-and-context (FHIR's `PractitionerRole`: this practitioner, at this organization, in this specialty, during this period) is a good model when the same practitioner holds different roles at different organizations or times. This project has one hospital, `hasSpecialty` and `worksInDepartment` sit directly on the practitioner, and no competency question needs an attribute that belongs to the *role* rather than the person. So `PractitionerRole` was **not** added: it would be a class with no data of its own and no question to answer.

| | Person with role types (this project) | Person plus `PractitionerRole` |
|---|---|---|
| A nurse who is also a patient | one individual, two types | one person, a patient record, a role record |
| Specialty at two hospitals | not expressible | natural |
| Licence valid 2020 to 2024 only | not expressible | natural |
| Cost | none | an extra class, links and shapes |

**Tested.** `tests/test_semantic_review.py` makes Dr Kumar (a doctor in the sample data) also a patient: SHACL still passes, the OWL reasoner still finds the ontology consistent, and the individual keeps one identity. When you need time-bounded or organisation-specific roles, add `PractitionerRole` then; nothing in the current model has to be undone to do so.

## 18. Where each rule lives: OWL, SHACL, and the data contract

The worked example is *an encounter must not end before it starts*.

| Layer | Responsibility | For this rule |
|---|---|---|
| **OWL** (the schema) | What things *mean* and what follows from them | Nothing. OWL cannot compare two datatype values of one individual, and under the open-world assumption a missing end is simply unknown. The schema declares `encounterStart` and `encounterEnd` as `xsd:dateTime` and says nothing about their order |
| **SHACL** (the shapes) | Whether *RDF* data is valid, whatever produced it | **Enforces it.** `EncounterShape` has `sh:lessThanOrEquals hc:encounterEnd` on `encounterStart`. It applies only when both values exist, allows a zero-length encounter, compares instants (so `10:00+02:00` equals `08:00Z`), and flags a value with no time zone separately |
| **Data contract** (`services/sample_data.py`) | Whether the *source rows* are sane, before any RDF is built | Reports `INVALID_DATE: end is before start` with the file and row, so the person fixing a CSV sees *where* |

The data-contract check and the SHACL rule look like duplication but answer different questions. The contract protects the CSV path and gives a row-level message; SHACL protects every RDF input, including data that never saw a CSV (an upload, a different generator, a hand edit). `test_the_same_defect_is_stopped_by_each_layer_for_its_own_input` shows each layer catching the defect on its own, with the other absent.

The audit's note that ordering was "enforced only by the data contract" was **wrong**: the SHACL rule already existed (it uses `sh:lessThanOrEquals`, which an earlier count of `sh:lessThan` missed). What this review added is the evidence: valid and invalid intervals, across time zones and midnight, and a mutation of the real sample data.

Not enforced anywhere yet, by choice: `onsetDate <= abatementDate`, an observation inside its encounter's interval, and a birth date before the first encounter. They would follow the same pattern; no competency question depends on them.

## 19. Open and closed shapes

A **closed** shape (`sh:closed true`) rejects any property it does not list. That catches typos and stray attributes, and it forbids extension. An **open** shape checks what it names and ignores the rest.

**Decision.** Close only fixed *value objects*; keep entity shapes open.

| Shape | Closed? | Why |
|---|---|---|
| `CodeConceptShape` | **Yes** | The pattern is exactly system + code + display. Nothing should extend it, and a misspelt `codeValu` would otherwise be silently ignored |
| `IdentifierShape` | **Yes** | The pattern is exactly system + value + type (+ assigner). `identifierAssigner` was added to the shape so the closed shape accepts what the sample data already carries |
| `PatientShape`, `DoctorShape`, `EncounterShape`, `MedicationShape`, `DiagnosisShape`, the administrative shapes | **No** | Entities are the extension points: a site profile adds attributes, other systems contribute properties, and the projection and reasoner add inferred edges. Closing them would turn every extension into a violation |

`rdf:type` is always ignored (`sh:ignoredProperties`), so `owl:NamedIndividual` and additional types are not flagged. A test asserts that exactly these two shapes are closed, so closing another is a deliberate, reviewed change, and that an extension property on a patient is tolerated.
