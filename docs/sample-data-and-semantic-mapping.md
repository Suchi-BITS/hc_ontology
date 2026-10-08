# Sample data and semantic mapping

*A hands-on chapter. By the end you will have traced one patient from a row in a CSV file to a node in the graph, broken the data on purpose in five different ways, and seen which layer catches each break.*

Everything below runs without Neo4j, Docker or an API key.

## 1. The idea in one picture

```text
data/source/*.csv                    what a clinic (or an import job) hands you
      │  load_dataset()
      ▼
DATA CONTRACT   services/sample_data.py        ← fails early: references, duplicates, dates,
      │                                           codes, classifications. Reports every problem.
      │  build_sample_data()  (scripts/generate_sample_data.py)
      ▼
RDF / OWL       the ontology + individuals
      │  SHACL gate (core/shacl_validator.py)  ← fails before the file is written
      ▼
data/sample_data.ttl  +  ontology/healthcare_schema.ttl   ← the authority (two files, one dataset); replaced atomically or not at all
      │  services/graph_projection.py + SHACL gate again in the exporter
      ▼
Neo4j           a derived, rebuildable projection
```

Each arrow is a gate. Data that fails a gate does not reach the next layer, and nothing is "loaded and hoped for". The rule from [semantic-authority-and-graph-projection.md](semantic-authority-and-graph-projection.md) still holds: meaning lives in RDF; Neo4j only mirrors it.

## 2. The data contract

A contract is a sentence you can test. Ours: **every entity in the sample data must be expressible in the ontology, must satisfy the SHACL shapes, and must be consistent with the other rows and with an independent reference.** The first two are enforced by the ontology and the shapes. The third is what `services/sample_data.py` adds, because SHACL looks at one graph and cannot, for example, compare a drug to a pharmacology reference.

| Concern | Check (problem code) | Why it is not left to SHACL |
|---|---|---|
| Structure | `MISSING_FILE`, `MISSING_COLUMN`, `UNKNOWN_COLUMN` | A header typo (`date_of_brith`) would otherwise become a silent null |
| Required fields | `MISSING_REQUIRED` | Caught on the row, with the file and line, not as a node in a graph |
| Identifiers | `INVALID_IDENTIFIER`, `DUPLICATE_ID` | The id becomes part of an IRI; two rows with one id *merge* into one node in RDF instead of failing |
| Duplicate entities | `DUPLICATE_ENTITY` (same person under two ids, shared MRN, license, prescription number, code, drug name) | Different IRIs make them valid RDF; only a human sees they are the same thing |
| References | `UNKNOWN_REFERENCE` | A dangling foreign key becomes an untyped IRI in RDF |
| Relationships | `INVALID_RELATIONSHIP` (nurse diagnoses, encounter of another patient, drug the patient is allergic to) | Needs a join across tables |
| Dates | `INVALID_DATE` (not ISO, impossible, future birth, no time zone, end before start, before birth) | |
| Codes | `INVALID_CODE`, `WRONG_CODE_SYSTEM` (pattern, SNOMED Verhoeff and LOINC mod-10 check digits, ICD-10 on a drug) | SHACL can match a pattern; it cannot compute a check digit |
| Classifications | `INVALID_CLASSIFICATION` (unknown specialty, status, encounter type, medication category, category that disagrees with `data/reference/drug_classification.csv`) | See section 4 |
| Values | `INVALID_VALUE` | |

`check_dataset()` returns every problem it finds, as a list of `Problem(code, file, row, entity, message)`. `require_valid()` raises `DataContractError` carrying all of them, because fixing data one error at a time is miserable.

The shared vocabularies (specialties, genders, encounter types, medication categories, code systems) live once, in `services/reference_vocab.py`. The generator builds the SKOS concepts from the same tables the checker validates against, so the two cannot drift.

## 3. Walk one patient through

Open `data/source/patients.csv`:

```csv
id,first_name,last_name,gender,date_of_birth,blood_group,mrn
PatientJohn,John,Doe,Male,1985-03-14,O+,MRN-000123
```

The mapping, in `build_sample_data()`:

| CSV | RDF | Note |
|---|---|---|
| `id` | the individual's IRI `…#PatientJohn`, class `hc:Patient` | identity is the id, never the name |
| `first_name`, `last_name` | `hc:firstName`, `hc:lastName` (`xsd:string`) | |
| `gender` | `hc:administrativeGender` → the SKOS concept `hc:GenderMale` | a controlled value, not a string |
| `date_of_birth` | `hc:dateOfBirth` (`xsd:date`) | parsed, so `1985-13-40` cannot get this far |
| `blood_group` | `hc:bloodGroup` | |
| `mrn` | a separate `hc:Identifier` (system, value, type `MRN`) linked by `hc:hasIdentifier` | a business identifier is a thing with a system, not a bare string |

Run the pipeline and look at the result:

```bash
python scripts/generate_sample_data.py --output /tmp/check.ttl
python scripts/validate.py
```

`validate.py` step 0 checks the CSVs; step 2 proves the committed schema and sample data are exactly what their generators produce; step 3 runs SHACL; step 4 plans the Neo4j projection.

## 4. Why `Metformin → Analgesic` happened, and why it cannot again

The audit found Metformin and Insulin classified as Analgesic. Patching two values would have fixed the symptom. The causes were three:

1. **The model let a human assign the class by hand.** Medications were created as subclasses of category classes. Since P2 a category is a SKOS concept (`hc:medicationCategory`), and `AntidiabeticMedication` is a *defined* class that a reasoner derives. There is no `Analgesic` class to put a drug into by accident (`test_no_medication_is_asserted_as_a_category_subclass`).
2. **Nothing compared the data to an independent source of truth.** `data/reference/drug_classification.csv` (with the ATC code it was taken from) is that source. The contract requires every medication to appear in it and its categories to match exactly. A drug missing from the reference is also an error: a classification nobody can verify is not accepted.
3. **A related error class was invisible.** The checker also rejects a drug bound to the wrong RxNorm concept (Aspirin carrying Metformin's code) and to a code from the wrong system (a drug with an ICD-10 code).

To see it work, run the fixture:

```bash
mkdir /tmp/bad && cp -r data/source/. /tmp/bad && cp data/invalid_source/metformin_analgesic/medications.csv /tmp/bad/
python scripts/generate_sample_data.py --source-dir /tmp/bad --output /tmp/bad.ttl
```

```text
error: sample data violates the data contract (1 problem(s)):
  [INVALID_CLASSIFICATION] medications.csv:4 Metformin: categories ['Analgesic'] disagree with the reference ['Antidiabetic'] for 'Metformin'
```

Exit code 2, and `/tmp/bad.owl` does not exist.

## 5. Why PatientJohn was fixed where it was

`PatientShape` requires a birth date, a gender and so on. The audit reported John violating it. There were two bad ways to make that go away: weaken the shape, or drop John. Both hide the fact that a record was incomplete.

The right layer is the data. The source row carries every attribute the shape asks for, and the contract refuses a patient row without one (`patient_missing_dob`). The shape is unchanged, and a test pins that (`test_patient_shape_was_not_weakened_for_the_sample_data`). If the shape ever *should* change, that is an ontology decision, made in `shapes/` with its own review, not a side effect of getting sample data to pass.

## 6. The fixtures: valid and deliberately invalid

| Location | Purpose |
|---|---|
| `data/source/` | The valid dataset. The contract, SHACL and the projection must all accept it. |
| `data/reference/drug_classification.csv` | The independent classification reference. |
| `data/invalid_source/<case>/` | Fifty tables, each broken in exactly one way. Every case has the one changed table and an `EXPECT` file: line 1 is the problem code the contract must report, line 2 says what is wrong. |
| `data/sample_instances/*.ttl` | RDF-level fixtures (valid and invalid) for SHACL itself. They test the shapes; the CSV fixtures test the data layer. |

A case is a single-table overlay on the valid source, which keeps each failure legible: you can `diff` a case against `data/source/` and see the one change. Adding a case means creating a directory, copying one table, breaking it, and writing `EXPECT`. The test picks it up automatically, and `test_every_problem_code_is_demonstrated_by_a_fixture` fails if you add a check that no fixture exercises. A check you have never seen fail is a check you do not know works.

## 7. Defence in depth, demonstrated

The contract and SHACL overlap on purpose. `test_shacl_gate_catches_what_the_contract_missed` switches the contract off, feeds a diagnosis with no code through the mapper, and shows that SHACL refuses to let the file be written. Conversely, the contract catches things SHACL would let through (a duplicated person, a drug classification that is wrong but well-formed).

Writing is atomic: the graph is saved to a temporary file, validated, and only then moved over `data/sample_data.ttl`. A failed run leaves the previous good file untouched (`test_a_failed_run_leaves_an_existing_ontology_untouched`).

## 8. Seeding Neo4j

`scripts/seed_neo4j_demo.py` is a development helper. It now checks the CSV contract, then loads the RDF through the exporter's SHACL gate. It has no flag to skip either step.

## 9. What is and is not in the CSVs

In CSV: codes, practitioners, patients, medications, encounters, diagnoses, observations, prescriptions, allergies. Still in the generator as demo scaffolding: the hospital, departments, wards, rooms and beds; appointments; treatments; the lab and imaging tests and their results; medical records, care plan, insurance and billing. Moving them is mechanical, but the clinical facts are where a wrong value does harm, so they went first. Rows may *refer* to the scaffolding (a department, a bed); the contract knows its ids from `REFERENCE_ENTITIES` in `reference_vocab.py`.

## 10. Limits

- The check digits catch typos in identifiers; they do not prove a code exists in the terminology. The sample uses a handful of real codes; production would check against a licensed terminology server.
- The drug reference is small and hand-maintained. It demonstrates the pattern (an independent source, compared by the machine); it is not a drug database.
- The Neo4j load itself is not exercised in this environment (no Docker or Neo4j here); the projection is tested against a recording fake and an in-memory oracle.

## Exercises

1. Copy `data/source` to a scratch directory, change PatientEmma's `date_of_birth` to `1992-02-30`, and run the contract. Which code do you get?
2. Add a new drug (`Ibuprofen`) to `medications.csv` without touching the reference. What happens? Add the reference row, with the ATC source, and run again.
3. Add a fixture for a failure the checker does not yet detect (an encounter whose participant list has the same doctor twice, for instance). Write the `EXPECT` first, watch the test fail, then add the check.
