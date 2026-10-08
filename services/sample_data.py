"""Sample-data contract: load the source CSVs and check them BEFORE any RDF is built.

Pipeline position (see docs/sample-data-and-semantic-mapping.md):

    data/source/*.csv --load--> rows --check_dataset--> [Problem] --(empty)--> generator builds RDF
                                                                      --> SHACL gate --> .owl --> Neo4j

This module checks what SHACL cannot or should not: cross-file references, duplicates, check digits,
and agreement with an independent drug-classification reference. Everything it finds is a `Problem`
with a stable `code`, so tests and operators can name the failure.
"""

from __future__ import annotations

import csv
import datetime
from dataclasses import dataclass
from pathlib import Path

from services import reference_vocab as V

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "data" / "source"
REFERENCE_DIR = ROOT / "data" / "reference"

# file -> (required columns, optional columns).  Unknown columns are an error: a typo must not vanish silently.
SCHEMA: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "codes": (("id", "system", "code", "display"), ()),
    "practitioners": (("id", "kind", "first_name", "last_name", "gender", "date_of_birth", "department"),
                      ("specialty", "license", "years_of_experience")),
    "patients": (("id", "first_name", "last_name", "gender", "date_of_birth", "blood_group"), ("mrn",)),
    "medications": (("id", "name", "categories"), ("code_id",)),
    "encounters": (("id", "patient_id", "type", "start", "reason", "participants"), ("end", "location", "transport")),
    "diagnoses": (("id", "patient_id", "encounter_id", "name", "code_ids", "doctor_id", "onset_date", "status"), ()),
    "observations": (("id", "class", "patient_id", "code_id", "value", "unit", "effective"), ("encounter_id", "recorded_by")),
    "prescriptions": (("id", "number", "patient_id", "doctor_id", "medication_ids", "dose", "date"), ()),
    "allergies": (("id", "patient_id", "medication_id"), ()),
}

Dataset = dict[str, list[dict[str, str]]]


@dataclass(frozen=True)
class Problem:
    code: str        # stable machine name, e.g. UNKNOWN_REFERENCE
    file: str
    row: int         # 1-based data row; 0 when the problem is about the file
    entity: str
    message: str

    def __str__(self) -> str:
        where = f"{self.file}.csv" + (f":{self.row}" if self.row else "")
        return f"[{self.code}] {where} {self.entity}: {self.message}"


class DataContractError(Exception):
    """Raised when the sample data breaks the contract. Carries every problem, not just the first."""

    def __init__(self, problems: list[Problem]):
        self.problems = problems
        head = "\n".join(f"  {p}" for p in problems[:25])
        more = f"\n  ... and {len(problems) - 25} more" if len(problems) > 25 else ""
        super().__init__(f"sample data violates the data contract ({len(problems)} problem(s)):\n{head}{more}")


def split(value: str) -> list[str]:
    return [v for v in (value or "").split("|") if v]


# ---- loading -----------------------------------------------------------------------------------

def load_dataset(source_dir: Path | str = SOURCE_DIR) -> Dataset:
    """Read every CSV in SCHEMA. A missing file is an empty table (reported by the checker as a problem)."""
    source_dir = Path(source_dir)
    data: Dataset = {}
    for name in SCHEMA:
        path = source_dir / f"{name}.csv"
        if not path.is_file():
            data[name] = []
            continue
        with path.open(encoding="utf-8", newline="") as fh:
            data[name] = [{k: (v or "").strip() for k, v in row.items() if k is not None} for row in csv.DictReader(fh)]
    return data


def load_drug_reference(path: Path | str = REFERENCE_DIR / "drug_classification.csv") -> dict[str, set[str]]:
    with Path(path).open(encoding="utf-8", newline="") as fh:
        return {r["name"].strip().lower(): set(split(r["categories"].strip())) for r in csv.DictReader(fh)}


def read_header(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as fh:
        return next(csv.reader(fh), [])


# ---- value parsers -------------------------------------------------------------------------------

def parse_date(text: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(text) if len(text) == 10 else None
    except ValueError:
        return None


def parse_datetime(text: str) -> datetime.datetime | None:
    """ISO-8601 WITH an explicit zone offset, the same requirement the SHACL shapes enforce."""
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None


# ---- the checks --------------------------------------------------------------------------------

def check_dataset(data: Dataset, drug_reference: dict[str, set[str]] | None = None,
                  source_dir: Path | str | None = None) -> list[Problem]:
    problems: list[Problem] = []

    def add(code, file, row, entity, message):
        problems.append(Problem(code, file, row, entity or "?", message))

    # -- 1. structure: headers, required fields ----------------------------------------------------
    if source_dir is not None:
        for name, (required, optional) in SCHEMA.items():
            path = Path(source_dir) / f"{name}.csv"
            if not path.is_file():
                add("MISSING_FILE", name, 0, name, "source file is missing")
                continue
            header = read_header(path)
            for col in required:
                if col not in header:
                    add("MISSING_COLUMN", name, 0, col, "required column is absent")
            for col in header:
                if col not in required and col not in optional:
                    add("UNKNOWN_COLUMN", name, 0, col, "column is not part of the contract (typo?)")
    for name, (required, _opt) in SCHEMA.items():
        for i, row in enumerate(data.get(name, []), start=1):
            for col in required:
                if col in row and not row[col]:
                    add("MISSING_REQUIRED", name, i, row.get("id"), f"required field '{col}' is empty")
    if any(p.code in ("MISSING_FILE", "MISSING_COLUMN") for p in problems) or any(
            col not in row for name, (req, _o) in SCHEMA.items() for row in data.get(name, []) for col in req):
        return problems  # the later checks read these columns; report the structural fault by itself

    # -- 2. identifiers: unique across the whole IRI namespace -----------------------------------------
    seen: dict[str, str] = {k: "generator reference entity" for k in V.REFERENCE_ENTITIES}
    for name in SCHEMA:
        for i, row in enumerate(data.get(name, []), start=1):
            ident = row.get("id", "")
            if not ident:
                continue
            if not ident.isidentifier():
                add("INVALID_IDENTIFIER", name, i, ident, "id must be letters, digits and underscore (it becomes part of an IRI)")
            if ident in seen:
                add("DUPLICATE_ID", name, i, ident, f"id already used by {seen[ident]}")
            else:
                seen[ident] = f"{name}.csv:{i}"

    ids = {name: {r.get("id", "") for r in data.get(name, [])} for name in SCHEMA}
    by_id = {name: {r.get("id", ""): r for r in data.get(name, [])} for name in SCHEMA}

    def ref(file, i, entity, column, value, target, kinds=None):
        """A foreign key must exist in `target` (a SCHEMA table or 'reference')."""
        if not value:
            return None
        if target == "reference":
            kind = V.REFERENCE_ENTITIES.get(value)
            if kind is None or (kinds and kind not in kinds):
                add("UNKNOWN_REFERENCE", file, i, entity, f"{column}='{value}' is not a known {'/'.join(kinds) if kinds else 'reference entity'}")
            return kind
        if value not in ids[target]:
            add("UNKNOWN_REFERENCE", file, i, entity, f"{column}='{value}' does not exist in {target}.csv")
            return None
        return by_id[target][value]

    # -- 3. codes ---------------------------------------------------------------------------------------
    seen_codes: dict[tuple[str, str], str] = {}
    for i, r in enumerate(data["codes"], start=1):
        system = V.CODE_SYSTEMS.get(r["system"])
        if system is None:
            add("INVALID_CODE", "codes", i, r["id"], f"unknown code system '{r['system']}' (known: {', '.join(V.CODE_SYSTEMS)})")
            continue
        _iri, pattern, label = system
        code = r["code"]
        if not pattern.match(code):
            add("INVALID_CODE", "codes", i, r["id"], f"'{code}' is not a well-formed {label} code")
        elif r["system"] == "snomed" and not V.snomed_check_digit_ok(code):
            add("INVALID_CODE", "codes", i, r["id"], f"'{code}' fails the SNOMED CT Verhoeff check digit")
        elif r["system"] == "loinc" and not V.loinc_check_digit_ok(code):
            add("INVALID_CODE", "codes", i, r["id"], f"'{code}' fails the LOINC mod-10 check digit")
        key = (r["system"], code)
        if key in seen_codes:
            add("DUPLICATE_ENTITY", "codes", i, r["id"], f"same {label} code as {seen_codes[key]}; one concept per code")
        else:
            seen_codes[key] = r["id"]

    def code_system_ok(file, i, entity, code_id, allowed):
        row = ref(file, i, entity, "code", code_id, "codes")
        if row and row["system"] not in allowed:
            add("WRONG_CODE_SYSTEM", file, i, entity, f"code {code_id} is {row['system']}; expected one of {'/'.join(allowed)}")

    # -- 4. people ---------------------------------------------------------------------------------------
    today = datetime.date.today()
    people: dict[tuple[str, str, str], str] = {}
    for file in ("practitioners", "patients"):
        for i, r in enumerate(data[file], start=1):
            if r["gender"] and r["gender"] not in V.GENDERS:
                add("INVALID_VALUE", file, i, r["id"], f"gender '{r['gender']}' not in {V.GENDERS}")
            dob = parse_date(r["date_of_birth"]) if r["date_of_birth"] else None
            if r["date_of_birth"] and dob is None:
                add("INVALID_DATE", file, i, r["id"], f"date_of_birth '{r['date_of_birth']}' is not an ISO date (YYYY-MM-DD)")
            elif dob and dob > today:
                add("INVALID_DATE", file, i, r["id"], f"date_of_birth {dob} is in the future")
            key = (r["first_name"].lower(), r["last_name"].lower(), r["date_of_birth"])
            if all(key):
                if key in people:
                    add("DUPLICATE_ENTITY", file, i, r["id"], f"same name and birth date as {people[key]}")
                else:
                    people[key] = r["id"]
    seen_lic: dict[str, str] = {}
    for i, r in enumerate(data["practitioners"], start=1):
        if r["kind"] not in V.PRACTITIONER_KINDS:
            add("INVALID_VALUE", "practitioners", i, r["id"], f"kind '{r['kind']}' not in {V.PRACTITIONER_KINDS}")
        if r["specialty"] and r["specialty"] not in V.SPECIALTIES:
            add("INVALID_CLASSIFICATION", "practitioners", i, r["id"], f"specialty '{r['specialty']}' is not a known Specialty")
        if r["kind"] == "Doctor" and not r.get("license"):
            add("MISSING_REQUIRED", "practitioners", i, r["id"], "a Doctor needs a license number (DoctorShape)")
        if r.get("license"):
            if r["license"] in seen_lic:
                add("DUPLICATE_ENTITY", "practitioners", i, r["id"], f"license {r['license']} already held by {seen_lic[r['license']]}")
            seen_lic.setdefault(r["license"], r["id"])
        ref("practitioners", i, r["id"], "department", r["department"], "reference", ("Department",))
        if r.get("years_of_experience") and not r["years_of_experience"].isdigit():
            add("INVALID_VALUE", "practitioners", i, r["id"], "years_of_experience must be a whole number")
    seen_mrn: dict[str, str] = {}
    for i, r in enumerate(data["patients"], start=1):
        if r["blood_group"] and not V.BLOOD_GROUP.match(r["blood_group"]):
            add("INVALID_VALUE", "patients", i, r["id"], f"blood_group '{r['blood_group']}' is not ABO/Rh (e.g. O+)")
        if r.get("mrn"):
            if r["mrn"] in seen_mrn:
                add("DUPLICATE_ENTITY", "patients", i, r["id"], f"MRN {r['mrn']} already belongs to {seen_mrn[r['mrn']]}")
            seen_mrn.setdefault(r["mrn"], r["id"])

    # -- 5. medications and their classification ------------------------------------------------------------
    drug_reference = drug_reference or {}
    seen_names: dict[str, str] = {}
    for i, r in enumerate(data["medications"], start=1):
        cats = split(r["categories"])
        for c in cats:
            if c not in V.MEDICATION_CATEGORIES:
                add("INVALID_CLASSIFICATION", "medications", i, r["id"], f"category '{c}' is not a known MedicationCategory")
        expected = drug_reference.get(r["name"].lower())
        if expected is None:
            if drug_reference:
                add("INVALID_CLASSIFICATION", "medications", i, r["id"], f"'{r['name']}' has no entry in data/reference/drug_classification.csv; cannot verify its category")
        elif set(cats) != expected:
            add("INVALID_CLASSIFICATION", "medications", i, r["id"],
                f"categories {sorted(cats)} disagree with the reference {sorted(expected)} for '{r['name']}'")
        if r.get("code_id"):
            code_system_ok("medications", i, r["id"], r["code_id"], ("rxnorm",))
            code_row = by_id["codes"].get(r["code_id"])
            if code_row and code_row["display"].lower() != r["name"].lower() and r["name"].lower() not in code_row["display"].lower():
                # Acetaminophen/Paracetamol is the one legitimate synonym pair in the sample; flag anything else.
                if {code_row["display"].lower(), r["name"].lower()} != {"acetaminophen", "paracetamol"}:
                    add("INVALID_CLASSIFICATION", "medications", i, r["id"],
                        f"medication '{r['name']}' is bound to code '{code_row['display']}'")
        if r["name"].lower() in seen_names:
            add("DUPLICATE_ENTITY", "medications", i, r["id"], f"same medication name as {seen_names[r['name'].lower()]}")
        seen_names.setdefault(r["name"].lower(), r["id"])

    # -- 6. encounters --------------------------------------------------------------------------------------------
    for i, r in enumerate(data["encounters"], start=1):
        e = r["id"]
        patient = ref("encounters", i, e, "patient_id", r["patient_id"], "patients")
        if r["type"] not in V.ENCOUNTER_TYPES:
            add("INVALID_CLASSIFICATION", "encounters", i, e, f"type '{r['type']}' not in {sorted(V.ENCOUNTER_TYPES)}")
        start = parse_datetime(r["start"]) if r["start"] else None
        end = parse_datetime(r["end"]) if r.get("end") else None
        if r["start"] and start is None:
            add("INVALID_DATE", "encounters", i, e, f"start '{r['start']}' needs full ISO-8601 with a time zone")
        if r.get("end") and end is None:
            add("INVALID_DATE", "encounters", i, e, f"end '{r['end']}' needs full ISO-8601 with a time zone")
        if start and end and end < start:
            add("INVALID_DATE", "encounters", i, e, "end is before start")
        if patient and start and (dob := parse_date(patient["date_of_birth"])) and start.date() < dob:
            add("INVALID_DATE", "encounters", i, e, "encounter starts before the patient was born")
        for pid in split(r["participants"]):
            if pid not in ids["practitioners"]:
                add("UNKNOWN_REFERENCE", "encounters", i, e, f"participant '{pid}' does not exist in practitioners.csv")
        if r.get("location"):
            ref("encounters", i, e, "location", r["location"], "reference", V.LOCATION_KINDS)
        if r.get("transport"):
            ref("encounters", i, e, "transport", r["transport"], "reference", ("Ambulance",))

    # -- 7. diagnoses -----------------------------------------------------------------------------------------------------
    for i, r in enumerate(data["diagnoses"], start=1):
        d = r["id"]
        patient = ref("diagnoses", i, d, "patient_id", r["patient_id"], "patients")
        enc = ref("diagnoses", i, d, "encounter_id", r["encounter_id"], "encounters")
        if enc and r["patient_id"] and enc["patient_id"] != r["patient_id"]:
            add("INVALID_RELATIONSHIP", "diagnoses", i, d, f"encounter {enc['id']} belongs to {enc['patient_id']}, not {r['patient_id']}")
        doc = ref("diagnoses", i, d, "doctor_id", r["doctor_id"], "practitioners")
        if doc and doc["kind"] != "Doctor":
            add("INVALID_RELATIONSHIP", "diagnoses", i, d, f"diagnosedBy must be a Doctor, but {doc['id']} is a {doc['kind']}")
        codes = split(r["code_ids"])
        if not codes:
            add("MISSING_REQUIRED", "diagnoses", i, d, "a Diagnosis needs at least one code")
        for c in codes:
            code_system_ok("diagnoses", i, d, c, ("icd10", "snomed"))
        if r["status"] and r["status"] not in V.CLINICAL_STATUSES:
            add("INVALID_CLASSIFICATION", "diagnoses", i, d, f"status '{r['status']}' not in {V.CLINICAL_STATUSES}")
        onset = parse_date(r["onset_date"]) if r["onset_date"] else None
        if r["onset_date"] and onset is None:
            add("INVALID_DATE", "diagnoses", i, d, f"onset_date '{r['onset_date']}' is not an ISO date")
        elif onset and patient and (dob := parse_date(patient["date_of_birth"])) and onset < dob:
            add("INVALID_DATE", "diagnoses", i, d, "onset precedes the patient's birth")

    # -- 8. observations -----------------------------------------------------------------------------------------------------------
    for i, r in enumerate(data["observations"], start=1):
        o = r["id"]
        ref("observations", i, o, "patient_id", r["patient_id"], "patients")
        if r.get("encounter_id"):
            enc = ref("observations", i, o, "encounter_id", r["encounter_id"], "encounters")
            if enc and enc["patient_id"] != r["patient_id"]:
                add("INVALID_RELATIONSHIP", "observations", i, o, f"encounter {enc['id']} belongs to {enc['patient_id']}, not {r['patient_id']}")
        if r["class"] not in V.OBSERVATION_CLASSES:
            add("INVALID_CLASSIFICATION", "observations", i, o, f"class '{r['class']}' not in {V.OBSERVATION_CLASSES}")
        code_system_ok("observations", i, o, r["code_id"], ("loinc",))
        try:
            float(r["value"])
        except ValueError:
            add("INVALID_VALUE", "observations", i, o, f"value '{r['value']}' is not numeric")
        if r["effective"] and parse_datetime(r["effective"]) is None:
            add("INVALID_DATE", "observations", i, o, f"effective '{r['effective']}' needs full ISO-8601 with a time zone")
        if r.get("recorded_by"):
            ref("observations", i, o, "recorded_by", r["recorded_by"], "practitioners")

    # -- 9. prescriptions and allergies ------------------------------------------------------------------------------------------------
    seen_rx: dict[str, str] = {}
    for i, r in enumerate(data["prescriptions"], start=1):
        p = r["id"]
        ref("prescriptions", i, p, "patient_id", r["patient_id"], "patients")
        doc = ref("prescriptions", i, p, "doctor_id", r["doctor_id"], "practitioners")
        if doc and doc["kind"] != "Doctor":
            add("INVALID_RELATIONSHIP", "prescriptions", i, p, f"prescribedBy must be a Doctor, but {doc['id']} is a {doc['kind']}")
        meds = split(r["medication_ids"])
        if not meds:
            add("MISSING_REQUIRED", "prescriptions", i, p, "a Prescription must contain at least one medication")
        for m in meds:
            ref("prescriptions", i, p, "medication_ids", m, "medications")
        if r["date"] and parse_date(r["date"]) is None:
            add("INVALID_DATE", "prescriptions", i, p, f"date '{r['date']}' is not an ISO date")
        if r["number"] in seen_rx:
            add("DUPLICATE_ENTITY", "prescriptions", i, p, f"prescription number {r['number']} already used by {seen_rx[r['number']]}")
        seen_rx.setdefault(r["number"], p)
    allergic = {(r["patient_id"], r["medication_id"]) for r in data["allergies"]}
    for i, r in enumerate(data["allergies"], start=1):
        ref("allergies", i, r["id"], "patient_id", r["patient_id"], "patients")
        ref("allergies", i, r["id"], "medication_id", r["medication_id"], "medications")
    # A prescription for a drug the patient is allergic to is a data error, not just a SHACL error.
    for i, r in enumerate(data["prescriptions"], start=1):
        for m in split(r["medication_ids"]):
            if (r["patient_id"], m) in allergic:
                add("INVALID_RELATIONSHIP", "prescriptions", i, r["id"], f"{r['patient_id']} is allergic to {m}")

    return problems


def require_valid(data: Dataset, drug_reference: dict[str, set[str]] | None = None,
                  source_dir: Path | str | None = None) -> Dataset:
    problems = check_dataset(data, drug_reference, source_dir)
    if problems:
        raise DataContractError(problems)
    return data
