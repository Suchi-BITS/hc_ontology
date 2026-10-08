# Competency questions: the questions the ontology must answer

*Ontology engineering should start with questions the system must answer.*

Most ontology projects begin with classes: Patient, Encounter, Medication. That feels like progress, but a class list cannot be wrong, because nothing asks it anything. A **competency question** is a question the finished system must be able to answer. It makes the model falsifiable: if a question cannot be answered from the data, the model, the data or the question is wrong, and you find out in a test instead of in front of a user.

This project follows one chain for every question:

```text
BUSINESS / DOMAIN QUESTION     "Which medication/allergy combinations require attention?"
        |
COMPETENCY QUESTION            the same question, made precise enough to be answered from the model
        |
ONTOLOGY MODEL                 the classes and properties that must exist (shapes/ and the generator)
        |
RDF DATA                       data/source/*.csv -> data/sample_data.ttl (schema: ontology/healthcare_schema.ttl)
        |
SPARQL QUERY                   sparql/cqNN_*.rq
        |
EXPECTED RESULT                written by hand from the sample data, before running the query
        |
TEST                           tests/test_sparql_competency.py
```

Two rules keep the chain honest. **Expected results are written by hand**, not pasted from the engine's output, otherwise the test only proves the query agrees with itself. And **a question that returns nothing must be shown capable of returning something**: CQ10 and CQ19 return nothing on clean data, so a test inserts a real conflict and watches them find it.

Only questions the ontology supports are asked. Where a natural question is *not* supported (section "What the questions taught us") the project says so instead of faking an answer.

## The 21 questions at a glance

| ID | Domain Question | Ontology Concepts | Properties | SPARQL Query | Expected Result | Test |
|---|---|---|---|---|---|---|
| CQ01 | Who are our patients? | `Patient` | — | [SELECT](../sparql/cq01_patients.rq) | 5 patients: Alice, Bob, David, Emma, John. | `test_competency_question_returns_the_expected_answer`; `test_api_executes_competency_questions` |
| CQ02 | What encounters does each patient have, and in what care setting? | `Encounter` | `hasEncounter`, `encounterType` | [SELECT](../sparql/cq02_patient_encounters.rq) | 6 encounters; David has two (Emergency 003, then Inpatient 006), everyone else one Ambulatory. | `test_competency_question_returns_the_expected_answer` |
| CQ03 | What is each patient diagnosed with? | `Diagnosis` | `hasDiagnosis`, `diagnosisName` | [SELECT](../sparql/cq03_patient_conditions.rq) | Alice and Bob: Diabetes; David: Migraine; Emma: Influenza; John: Hypertension. | `test_competency_question_returns_the_expected_answer` |
| CQ04 | Which patients have a given condition? | `Diagnosis`, `CodeConcept` | `hasDiagnosis`, `hasCode`, `codeSystem`, `codeValue` | [SELECT](../sparql/cq04_patients_by_condition_code.rq) | ICD-10 E11 gives Alice and Bob; I10 gives John; Z99 gives nobody; SNOMED 44054006 gives Alice and Bob. | `test_competency_question_returns_the_expected_answer`; `test_code_query_is_driven_by_its_parameters` |
| CQ05 | What medications do we know about, and what kind of drug is each? | `Medication` | `medicationCategory` | [SELECT](../sparql/cq05_medications_and_categories.rq) | Aspirin has two categories (Analgesic, Antiplatelet); Metformin and Insulin glargine are Antidiabetic; only Aspirin and Paracetamol are Analgesic. | `test_competency_question_returns_the_expected_answer` |
| CQ06 | Which measurements have been recorded, for whom, and in what unit? | `Observation` | `hasObservation`, `observationValue`, `observationUnit`, `hasCode`, `codeDisplay` | [SELECT](../sparql/cq06_numeric_observations.rq) | Alice: HbA1c 7.2 %; John: systolic blood pressure 152.0 mm[Hg]. | `test_competency_question_returns_the_expected_answer` |
| CQ07 | Which practitioners took part in which encounter? | — | `participatesIn` | [SELECT](../sparql/cq07_encounter_providers.rq) | 9 pairs; Encounter001 has a doctor and a nurse, Encounter003 two doctors. | `test_competency_question_returns_the_expected_answer` |
| CQ08 | Which doctor has which specialty? | `Doctor` | `hasSpecialty` | [SELECT](../sparql/cq08_doctors_by_specialty.rq) | Smith: Cardiology; John: Neurology; Williams: Surgery; Kumar: Internal medicine. | `test_competency_question_returns_the_expected_answer` |
| CQ09 | Which patients have allergies, and to what? | — | `hasAllergy`, `allergyToMedication` | [SELECT](../sparql/cq09_allergies.rq) | Bob is allergic to Amoxicillin; nobody else. | `test_competency_question_returns_the_expected_answer` |
| CQ10 | Which medication/allergy combinations require attention? | — | `prescribedFor`, `containsMedication`, `hasAllergy`, `allergyToMedication` | [SELECT](../sparql/cq10_medication_allergy_conflicts.rq) | No rows on the sample data. After adding Amoxicillin to Bob's insulin prescription, exactly that prescription is returned. | `test_competency_question_returns_the_expected_answer`; `test_conflict_query_finds_a_real_conflict` |
| CQ11 | Which patients are on diabetes medication? | `MedCategoryAntidiabetic` | `prescribedFor`, `containsMedication`, `medicationCategory` | [SELECT](../sparql/cq11_patients_on_antidiabetics.rq) | Alice (Metformin) and Bob (Insulin glargine). | `test_competency_question_returns_the_expected_answer`; `test_removed_modeling_would_break_the_antidiabetic_query` |
| CQ12 | Which beds belong to which department? | — | `containsWard`, `containsRoom`, `containsBed` | [SELECT](../sparql/cq12_beds_per_department.rq) | Cardiology: Bed1, Bed2; Neurology: Bed3; ICU: Bed4. | `test_competency_question_returns_the_expected_answer` |
| CQ13 | How many diagnoses has each doctor made? | `Diagnosis` | `diagnosedBy` | [SELECT](../sparql/cq13_diagnoses_per_doctor.rq) | Kumar 3, John 1, Smith 1. | `test_competency_question_returns_the_expected_answer`; `test_api_executes_competency_questions` |
| CQ14 | Who are all the people in the system, whatever their role? | `Person` | — | [SELECT](../sparql/cq14_all_persons.rq) | 11 people: 4 doctors, 2 nurses, 5 patients. | `test_competency_question_returns_the_expected_answer`; `test_subclass_path_finds_persons_that_a_plain_type_match_misses`; `test_api_accepts_a_valid_property_path_query` |
| CQ15 | Which appointments have not happened yet? | `Appointment` | `fulfilledBy` | [SELECT](../sparql/cq15_unfulfilled_appointments.rq) | Appointment002 (Emma's neurology follow-up). | `test_competency_question_returns_the_expected_answer` |
| CQ16 | Which observations belong to a given encounter? | — | `includesObservation`, `hasCode`, `codeDisplay`, `observationValue`, `observationUnit` | [SELECT](../sparql/cq16_encounter_observations.rq) | Encounter001 includes Observation001 (systolic blood pressure, 152.0 mm[Hg]). No other encounter has observations. | `test_competency_question_returns_the_expected_answer`; `test_encounter_observations_answer_follows_the_link_not_the_patient` |
| CQ17 | Which medications are associated with each patient, and who prescribed them? | — | `prescribedFor`, `prescribedBy`, `containsMedication` | [SELECT](../sparql/cq17_patient_medications.rq) | 6 rows: Alice (Metformin), Bob (Insulin glargine), Emma (Amoxicillin, Paracetamol), John (Amlodipine, Aspirin); every row names the prescribing doctor. | `test_competency_question_returns_the_expected_answer`; `test_patient_medications_are_driven_by_prescriptions` |
| CQ18 | Which observations relate to a particular condition? | `Encounter`, `Diagnosis` | `diagnoses`, `includesObservation`, `hasEncounter`, `diagnosisName`, `hasCode`, `codeDisplay`, `observationValue` | [SELECT](../sparql/cq18_findings_in_diagnosing_encounter.rq) | John, Hypertension, Systolic blood pressure, 152.0. Nothing else. | `test_competency_question_returns_the_expected_answer`; `test_findings_query_requires_the_shared_encounter` |
| CQ19 | Is there any prescription we should stop right now because of an allergy? | — | `prescribedFor`, `containsMedication`, `hasAllergy`, `allergyToMedication` | [ASK](../sparql/cq19_ask_allergy_conflict.rq) | false on the sample data; true after the conflict is introduced. | `test_ask_query_flips_when_a_conflict_exists` |
| CQ20 | Give me everything clinically relevant about this patient as a small graph I can hand to another system. | — | `hasDiagnosis`, `diagnosisName`, `prescribedFor`, `containsMedication` | [CONSTRUCT](../sparql/cq20_construct_patient_summary.rq) | For PatientJohn: his diagnosis and its name, and two prescriptions with their medications. | `test_construct_returns_a_bounded_patient_subgraph` |
| CQ21 | Which patients have a medical condition of any kind? | `Condition` | `hasDiagnosis` | [SELECT](../sparql/cq21_patients_with_a_condition.rq) | On the asserted graph: no rows. With the class hierarchy applied (Diagnosis is a Condition): all 5 patients. | `test_condition_query_needs_the_class_hierarchy` |

All tests are in [tests/test_sparql_competency.py](../tests/test_sparql_competency.py). Each query has the same prefix block; `hc:` is `http://example.org/healthcare-hospital.owl#`.

## Each question in detail

### CQ01. Who are our patients?

**Purpose.** The simplest question a patient registry must answer; it checks that the Patient class is populated and typed.

**Form.** SELECT

```sparql
# CQ01: Which patients exist?
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?patient WHERE { ?patient a hc:Patient }
ORDER BY ?patient
```

**Expected result.** 5 patients: Alice, Bob, David, Emma, John.

**Why it works.** A plain type match. It works because every patient is asserted as a Patient; nobody is a bare Person (see CQ14).

**Tests.** `test_competency_question_returns_the_expected_answer`; `test_api_executes_competency_questions`

### CQ02. What encounters does each patient have, and in what care setting?

**Purpose.** Shows how a patient's care history hangs off Encounter, and that the setting is a controlled concept, not a string.

**Form.** SELECT

```sparql
# CQ02: Which encounters did each patient have, and in which care setting?
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?patient ?encounter ?setting WHERE {
  ?patient hc:hasEncounter ?encounter .
  ?encounter hc:encounterType ?type .
  ?type rdfs:label ?setting .
}
ORDER BY ?patient ?encounter
```

**Expected result.** 6 encounters; David has two (Emergency 003, then Inpatient 006), everyone else one Ambulatory.

**Why it works.** The setting is read through the SKOS label of the EncounterType concept, so renaming a label changes the answer without touching data.

**Tests.** `test_competency_question_returns_the_expected_answer`

### CQ03. What is each patient diagnosed with?

**Purpose.** The core clinical question; it also confirms the one-diagnosis-record-per-patient rule (nobody shares a Diagnosis individual).

**Form.** SELECT

```sparql
# CQ03: Which diagnoses does each patient have?
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?patient ?diagnosis WHERE {
  ?patient hc:hasDiagnosis ?dx .
  ?dx hc:diagnosisName ?diagnosis .
}
ORDER BY ?patient
```

**Expected result.** Alice and Bob: Diabetes; David: Migraine; Emma: Influenza; John: Hypertension.

**Why it works.** Alice and Bob both show 'Diabetes' but through two separate Diagnosis records; the shared meaning is the code (CQ04), not a shared node.

**Tests.** `test_competency_question_returns_the_expected_answer`

### CQ04. Which patients have a given condition?

**Purpose.** Identify a cohort by a standard code instead of a free-text name; the parameterised version of CQ03.

**Form.** SELECT

```sparql
# CQ04: Which patients have a diagnosis with a given code? (?system and ?code are bound by the caller)
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT DISTINCT ?patient WHERE {
  ?patient hc:hasDiagnosis ?dx .
  ?dx hc:hasCode ?c .
  ?c hc:codeSystem ?system ;
     hc:codeValue  ?code .
}
ORDER BY ?patient
```

**Expected result.** ICD-10 E11 gives Alice and Bob; I10 gives John; Z99 gives nobody; SNOMED 44054006 gives Alice and Bob.

**Why it works.** ?system and ?code are bound by the caller. The same cohort is reachable through ICD-10 or SNOMED because a Diagnosis can carry several codes.

**Tests.** `test_competency_question_returns_the_expected_answer`; `test_code_query_is_driven_by_its_parameters`

### CQ05. What medications do we know about, and what kind of drug is each?

**Purpose.** Checks the medication model that the audit found wrong (Metformin and Insulin as analgesics).

**Form.** SELECT

```sparql
# CQ05: Which medications exist and what therapeutic categories do they have?
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?medication ?category WHERE {
  ?medication a hc:Medication ;
              hc:medicationCategory ?c .
  ?c rdfs:label ?category .
}
ORDER BY ?medication ?category
```

**Expected result.** Aspirin has two categories (Analgesic, Antiplatelet); Metformin and Insulin glargine are Antidiabetic; only Aspirin and Paracetamol are Analgesic.

**Why it works.** Category is data (a SKOS concept) rather than a subclass, so a drug can have several and the answer is verified against data/reference/drug_classification.csv elsewhere. (tests/test_sample_data.py checks the same categories against the reference.)

**Tests.** `test_competency_question_returns_the_expected_answer`

### CQ06. Which measurements have been recorded, for whom, and in what unit?

**Purpose.** Shows that an Observation is coded (LOINC) and carries a value with a unit.

**Form.** SELECT

```sparql
# CQ06: Which numeric observations exist, for whom, what do they measure, and in which unit?
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?patient ?measure ?value ?unit WHERE {
  ?patient hc:hasObservation ?obs .
  ?obs hc:observationValue ?value ;
       hc:observationUnit  ?unit ;
       hc:hasCode ?code .
  ?code hc:codeDisplay ?measure .
}
ORDER BY ?patient
```

**Expected result.** Alice: HbA1c 7.2 %; John: systolic blood pressure 152.0 mm[Hg].

**Why it works.** Lab results with only text (the CBC and MRI) have no numeric value and are correctly absent.

**Tests.** `test_competency_question_returns_the_expected_answer`

### CQ07. Which practitioners took part in which encounter?

**Purpose.** Care-team membership per encounter, for doctors and nurses alike.

**Form.** SELECT

```sparql
# CQ07: Which practitioners took part in which encounter?
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?encounter ?practitioner WHERE {
  ?practitioner hc:participatesIn ?encounter .
}
ORDER BY ?encounter ?practitioner
```

**Expected result.** 9 pairs; Encounter001 has a doctor and a nurse, Encounter003 two doctors.

**Why it works.** Only the participatesIn direction is asserted. It is the canonical direction; the inverse is left to a reasoner.

**Tests.** `test_competency_question_returns_the_expected_answer`

### CQ08. Which doctor has which specialty?

**Purpose.** Lookup used to route a patient to the right doctor.

**Form.** SELECT

```sparql
# CQ08: Which doctor has which specialty?
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?doctor ?specialty WHERE {
  ?doctor a hc:Doctor ;
          hc:hasSpecialty ?s .
  ?s rdfs:label ?specialty .
}
ORDER BY ?doctor
```

**Expected result.** Smith: Cardiology; John: Neurology; Williams: Surgery; Kumar: Internal medicine.

**Why it works.** Nurses have no specialty and are correctly absent: the query is typed to Doctor.

**Tests.** `test_competency_question_returns_the_expected_answer`

### CQ09. Which patients have allergies, and to what?

**Purpose.** The safety-critical input to CQ10 and CQ19.

**Form.** SELECT

```sparql
# CQ09: Which patients are allergic to which medication?
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?patient ?medication WHERE {
  ?patient hc:hasAllergy ?allergy .
  ?allergy hc:allergyToMedication ?medication .
}
```

**Expected result.** Bob is allergic to Amoxicillin; nobody else.

**Why it works.** An Allergy is its own node pointing at a Medication, so a medication allergy can be compared with a prescription by identity.

**Tests.** `test_competency_question_returns_the_expected_answer`

### CQ10. Which medication/allergy combinations require attention?

**Purpose.** The clinical safety rule written as a plain query, the same rule the SHACL shape enforces.

**Form.** SELECT

```sparql
# CQ10: Which prescriptions contain a medication the patient is allergic to? (the SHACL safety rule as a query)
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?prescription ?patient ?medication WHERE {
  ?prescription hc:prescribedFor ?patient ;
                hc:containsMedication ?medication .
  ?patient hc:hasAllergy ?allergy .
  ?allergy hc:allergyToMedication ?medication .
}
```

**Expected result.** No rows on the sample data. After adding Amoxicillin to Bob's insulin prescription, exactly that prescription is returned.

**Why it works.** An empty answer is only meaningful if the query can be non-empty, so a mutation test inserts a real conflict and watches the query find it.

**Tests.** `test_competency_question_returns_the_expected_answer`; `test_conflict_query_finds_a_real_conflict`

### CQ11. Which patients are on diabetes medication?

**Purpose.** A cohort defined by drug category, the kind of question that previously went wrong when categories were classes.

**Form.** SELECT

```sparql
# CQ11: Which patients are prescribed an antidiabetic medication? (category is data, not a class)
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT DISTINCT ?patient WHERE {
  ?rx hc:prescribedFor ?patient ;
      hc:containsMedication ?m .
  ?m hc:medicationCategory hc:MedCategoryAntidiabetic .
}
ORDER BY ?patient
```

**Expected result.** Alice (Metformin) and Bob (Insulin glargine).

**Why it works.** Removing Metformin's category from the graph drops Alice from the answer, proving the answer depends on the modelled fact.

**Tests.** `test_competency_question_returns_the_expected_answer`; `test_removed_modeling_would_break_the_antidiabetic_query`

### CQ12. Which beds belong to which department?

**Purpose.** Capacity questions need the containment chain department, ward, room, bed.

**Form.** SELECT

```sparql
# CQ12: Which beds belong to which department? (property path over the containment chain)
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?department ?bed WHERE {
  ?department hc:containsWard/hc:containsRoom/hc:containsBed ?bed .
}
ORDER BY ?department ?bed
```

**Expected result.** Cardiology: Bed1, Bed2; Neurology: Bed3; ICU: Bed4.

**Why it works.** A SPARQL property path (a/b/c) walks three links in one expression.

**Tests.** `test_competency_question_returns_the_expected_answer`

### CQ13. How many diagnoses has each doctor made?

**Purpose.** Workload reporting; the aggregate-query example.

**Form.** SELECT

```sparql
# CQ13: How many diagnoses has each doctor made? (aggregation)
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?doctor (COUNT(?dx) AS ?diagnoses) WHERE {
  ?dx a hc:Diagnosis ;
      hc:diagnosedBy ?doctor .
}
GROUP BY ?doctor
ORDER BY DESC(?diagnoses) ?doctor
```

**Expected result.** Kumar 3, John 1, Smith 1.

**Why it works.** GROUP BY with COUNT, ordered by count descending.

**Tests.** `test_competency_question_returns_the_expected_answer`; `test_api_executes_competency_questions`

### CQ14. Who are all the people in the system, whatever their role?

**Purpose.** Shows why the class hierarchy matters: nobody is asserted as Person, yet everybody is one.

**Form.** SELECT

```sparql
# CQ14: Who is a Person? Patients and practitioners are Persons by subclass, found with a property path (no reasoner needed).
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?person WHERE {
  ?person a/rdfs:subClassOf* hc:Person .
}
ORDER BY ?person
```

**Expected result.** 11 people: 4 doctors, 2 nurses, 5 patients.

**Why it works.** The query follows rdfs:subClassOf with a property path. A plain type match returns nothing, which a test demonstrates.

**Tests.** `test_competency_question_returns_the_expected_answer`; `test_subclass_path_finds_persons_that_a_plain_type_match_misses`; `test_api_accepts_a_valid_property_path_query`

### CQ15. Which appointments have not happened yet?

**Purpose.** Scheduling follow-up; the negation example.

**Form.** SELECT

```sparql
# CQ15: Which appointments have no encounter yet? (negation)
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?appointment WHERE {
  ?appointment a hc:Appointment .
  FILTER NOT EXISTS { ?appointment hc:fulfilledBy ?encounter }
}
```

**Expected result.** Appointment002 (Emma's neurology follow-up).

**Why it works.** FILTER NOT EXISTS: absence of a fulfilling encounter is the information. This is open-world, so it means 'no encounter is recorded', not 'none exists'.

**Tests.** `test_competency_question_returns_the_expected_answer`

### CQ16. Which observations belong to a given encounter?

**Purpose.** Ties measurements to the visit in which they were taken.

**Form.** SELECT

```sparql
# CQ16: Which observations were made during a given encounter?
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?encounter ?observation ?measure ?value ?unit WHERE {
  ?encounter hc:includesObservation ?observation .
  ?observation hc:hasCode/hc:codeDisplay ?measure .
  OPTIONAL { ?observation hc:observationValue ?value ; hc:observationUnit ?unit }
}
ORDER BY ?encounter ?observation
```

**Expected result.** Encounter001 includes Observation001 (systolic blood pressure, 152.0 mm[Hg]). No other encounter has observations.

**Why it works.** The HbA1c result belongs to Alice but is not linked to Encounter004, so it is correctly absent: the data does not say it was taken there.

**Tests.** `test_competency_question_returns_the_expected_answer`; `test_encounter_observations_answer_follows_the_link_not_the_patient`

### CQ17. Which medications are associated with each patient, and who prescribed them?

**Purpose.** A medication list per patient; the join goes through Prescription because a patient is not directly linked to a drug.

**Form.** SELECT

```sparql
# CQ17: Which medications has each patient been prescribed, and by whom?
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?patient ?medication ?doctor WHERE {
  ?rx hc:prescribedFor ?patient ;
      hc:prescribedBy ?doctor ;
      hc:containsMedication ?medication .
}
ORDER BY ?patient ?medication
```

**Expected result.** 6 rows: Alice (Metformin), Bob (Insulin glargine), Emma (Amoxicillin, Paracetamol), John (Amlodipine, Aspirin); every row names the prescribing doctor.

**Why it works.** Dose is a property of the order, not of the drug, so it is not selected here (see dosageInstruction on Prescription).

**Tests.** `test_competency_question_returns_the_expected_answer`; `test_patient_medications_are_driven_by_prescriptions`

### CQ18. Which observations relate to a particular condition?

**Purpose.** The ontology has no 'indicates' relation, so this asks the supportable question: which measurements were taken in the encounter where the condition was diagnosed.

**Form.** SELECT

```sparql
# CQ18: Which measurements were taken in the same encounter in which a condition was diagnosed? (co-occurrence, not causation)
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT ?patient ?condition ?measure ?value WHERE {
  ?encounter hc:diagnoses ?dx ;
             hc:includesObservation ?obs .
  ?patient hc:hasEncounter ?encounter .
  ?dx hc:diagnosisName ?condition .
  ?obs hc:hasCode/hc:codeDisplay ?measure ;
       hc:observationValue ?value .
}
ORDER BY ?patient ?measure
```

**Expected result.** John, Hypertension, Systolic blood pressure, 152.0. Nothing else.

**Why it works.** Co-occurrence is not causation. A clinical 'this observation indicates that condition' would need a new, evidence-bearing relation; the competency question deliberately stops at what the model can support.

**Tests.** `test_competency_question_returns_the_expected_answer`; `test_findings_query_requires_the_shared_encounter`

### CQ19. Is there any prescription we should stop right now because of an allergy?

**Purpose.** A yes/no safety check suitable for a dashboard badge or a pre-release gate.

**Form.** ASK

```sparql
# CQ19: Does any prescription contain a medication its patient is allergic to? (yes/no)
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

ASK {
  ?rx hc:prescribedFor ?patient ;
      hc:containsMedication ?medication .
  ?patient hc:hasAllergy/hc:allergyToMedication ?medication .
}
```

**Expected result.** false on the sample data; true after the conflict is introduced.

**Why it works.** ASK returns a boolean. It is the cheapest form of CQ10 when you only need to know whether to look.

**Tests.** `test_ask_query_flips_when_a_conflict_exists`

### CQ20. Give me everything clinically relevant about this patient as a small graph I can hand to another system.

**Purpose.** Shows CONSTRUCT as an export: the answer is RDF, not a table.

**Form.** CONSTRUCT

```sparql
# CQ20: What is the clinical summary subgraph of a given patient? (?patient is bound by the caller)
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

CONSTRUCT {
  ?patient hc:hasDiagnosis ?dx .
  ?dx hc:diagnosisName ?name .
  ?rx hc:prescribedFor ?patient ;
      hc:containsMedication ?medication .
} WHERE {
  ?patient hc:hasDiagnosis ?dx .
  ?dx hc:diagnosisName ?name .
  OPTIONAL { ?rx hc:prescribedFor ?patient ; hc:containsMedication ?medication }
}
```

**Expected result.** For PatientJohn: his diagnosis and its name, and two prescriptions with their medications.

**Why it works.** Only the shape in the CONSTRUCT template is returned, so the consumer receives a bounded subgraph rather than the whole graph.

**Tests.** `test_construct_returns_a_bounded_patient_subgraph`

### CQ21. Which patients have a medical condition of any kind?

**Purpose.** Demonstrates reasoning: the data says Diagnosis, the question says Condition.

**Form.** SELECT; needs the class hierarchy applied before querying

```sparql
# CQ21: Which patients have a condition of any kind? (needs the class hierarchy: diagnoses are asserted as Diagnosis, the question asks for Condition)
PREFIX hc:   <http://example.org/healthcare-hospital.owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

SELECT DISTINCT ?patient WHERE {
  ?patient hc:hasDiagnosis ?x .
  ?x a hc:Condition .
}
ORDER BY ?patient
```

**Expected result.** On the asserted graph: no rows. With the class hierarchy applied (Diagnosis is a Condition): all 5 patients.

**Why it works.** RDF stores what was asserted. The generalisation Diagnosis-is-a-Condition is an ontology fact that must be applied (here the subclass closure; a full reasoner gives the same answer) before the query can see it.

**Tests.** `test_condition_query_needs_the_class_hierarchy`

## What the questions taught us

Writing the questions first exposed decisions that a class diagram hides.

- **"Which observations indicate a condition?" cannot be answered, and should not be.** The ontology has no `indicates` relation, and adding one would assert clinical causation the data does not carry. CQ18 asks the supportable question (what was measured in the encounter where the condition was diagnosed) and the catalog says plainly that this is co-occurrence.
- **Link, don't assume.** Alice's HbA1c result belongs to her but is not linked to her encounter, so CQ16 correctly does not return it. A test links it and shows the answer change. If you want it in the answer, the fix is a data link, not a cleverer query.
- **Diagnosis versus Condition (CQ21).** The data says `Diagnosis`; the question says `Condition`. On the asserted graph the answer is empty. Applying the class hierarchy (the subclass closure here; a full reasoner gives the same answer) returns all five patients. This is the smallest honest demonstration of why RDF needs reasoning.
- **Empty answers need proof (CQ10, CQ19).** Absence of a conflict means something only if the query can find a conflict. Mutation tests supply one.
- **Open world.** CQ15 ("appointments with no encounter") means *no encounter is recorded*, not *none exists*.

## How to add a competency question

1. Write the domain question and the purpose in plain language in `sparql/catalog.json`.
2. Write the expected result by hand from the sample data **before** running anything.
3. Add `sparql/cq<NN>_name.rq`. The first line is `# CQNN: <the question>?`.
4. Add the expected rows to `CASES` in `tests/test_sparql_competency.py` (or a dedicated test for `ASK`/`CONSTRUCT`), and a mutation test showing the answer depends on the modelled fact.
5. List the concepts, properties and tests in the catalog, then run `python scripts/build_cq_doc.py`.

The suite fails if a query has no catalog entry, if the catalog names a term the query does not use or the ontology does not define, if a cited test does not exist, or if this document is stale.

## Limits

- The queries run against the RDF graph with no reasoner, except CQ21, which applies the subclass closure. A full OWL reasoner (HermiT, needs Java) is exercised separately in `tests/test_ontology.py`.
- Answers are checked against the sample data (47 CSV rows). They show that the model can answer the questions, not that it scales.
- The Cypher equivalents over the Neo4j projection are not part of this chain; the projection is a derived view and is tested against the RDF separately.
