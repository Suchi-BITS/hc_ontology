"""Controlled vocabularies and reference entities: ONE definition, used by the generator, the data
contract checker and the tests. Pure data; no third-party imports.

If a value is not listed here, sample data may not use it. Adding a specialty or a medication category is a
change to this file (and therefore to the ontology), not to a CSV row.
"""

from __future__ import annotations

import re

# key -> label.  The key is what appears in the CSV and in the individual's name (SpecialtyCardiology).
SPECIALTIES = {
    "Cardiology": "Cardiology", "Neurology": "Neurology", "Surgery": "Surgery",
    "EmergencyMedicine": "Emergency medicine", "Radiology": "Radiology", "Pediatrics": "Pediatrics",
    "Oncology": "Oncology", "Orthopedics": "Orthopedics", "CriticalCare": "Critical care",
    "InternalMedicine": "Internal medicine", "LaboratoryMedicine": "Laboratory medicine",
}
GENDERS = ("Male", "Female", "Other", "Unknown")
# key -> (label, notation)
ENCOUNTER_TYPES = {
    "Ambulatory": ("Ambulatory", "AMB"), "Inpatient": ("Inpatient", "IMP"),
    "Emergency": ("Emergency", "EMER"), "Virtual": ("Virtual", "VR"),
}
MEDICATION_CATEGORIES = {
    "Analgesic": "Analgesic", "Antibiotic": "Antibiotic", "Antiviral": "Antiviral",
    "Antidiabetic": "Antidiabetic", "Antihypertensive": "Antihypertensive",
    "Antiplatelet": "Antiplatelet", "Vaccine": "Vaccine",
}

PRACTITIONER_KINDS = ("Doctor", "Nurse")
TREATMENT_CLASSES = ("MedicationTreatment", "PhysicalTherapy", "RadiationTherapy", "Chemotherapy", "SurgicalTreatment")
TEST_CLASSES = ("LaboratoryTest", "ImagingStudy")
OBSERVATION_CLASSES = ("VitalSign", "Observation")
CLINICAL_STATUSES = ("active", "recurrence", "remission", "resolved")
BLOOD_GROUP = re.compile(r"^(A|B|AB|O)[+-]$")

# short key used in codes.csv -> (system IRI, code pattern, short description)
CODE_SYSTEMS = {
    "icd10": ("http://hl7.org/fhir/sid/icd-10", re.compile(r"^[A-TV-Z][0-9][0-9AB](\.[0-9A-TV-Z]{1,4})?$"), "ICD-10"),
    "snomed": ("http://snomed.info/sct", re.compile(r"^[1-9][0-9]{5,17}$"), "SNOMED CT"),
    "loinc": ("http://loinc.org", re.compile(r"^[0-9]{1,5}-[0-9]$"), "LOINC"),
    "rxnorm": ("http://www.nlm.nih.gov/research/umls/rxnorm", re.compile(r"^[0-9]{1,8}$"), "RxNorm"),
}

# Entities created by the generator itself (organization structure). Source rows may refer to them by id.
REFERENCE_ENTITIES = {
    "CityHospital": "Hospital",
    "CardiologyDept": "Department", "NeurologyDept": "Department", "EmergencyDept": "Department",
    "RadiologyDept": "Department", "PharmacyDept": "Department", "LaboratoryDept": "Department", "ICUDept": "Department",
    "WardA": "Ward", "WardB": "Ward", "WardICU": "Ward",
    "Room101": "Room", "Room102": "Room", "Room201": "Room", "RoomICU1": "Room",
    "Bed1": "Bed", "Bed2": "Bed", "Bed3": "Bed", "Bed4": "Bed",
    "Ambulance001": "Ambulance",
}
LOCATION_KINDS = ("Ward", "Room", "Bed")


# ---- identifier check digits (a genuinely different kind of validity than "matches a pattern") -----------

_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 2, 3, 4, 0, 6, 7, 8, 9, 5), (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7), (4, 0, 1, 2, 3, 9, 5, 6, 7, 8), (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2), (7, 6, 5, 9, 8, 2, 1, 0, 4, 3), (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 5, 7, 6, 2, 8, 3, 0, 9, 4), (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7), (9, 4, 5, 3, 1, 2, 6, 8, 7, 0), (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5), (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def snomed_check_digit_ok(identifier: str) -> bool:
    """SNOMED CT identifiers end in a Verhoeff check digit."""
    c = 0
    for i, ch in enumerate(reversed(identifier)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


def loinc_check_digit_ok(code: str) -> bool:
    """LOINC codes end in a mod-10 (Luhn-style) check digit after the hyphen."""
    body, _, check = code.partition("-")
    if not body.isdigit() or not check.isdigit():
        return False
    digits = [int(d) for d in body][::-1]
    total = 0
    for i, d in enumerate(digits):
        if i % 2 == 0:
            d *= 2
            d = d - 9 if d > 9 else d
        total += d
    return (10 - total % 10) % 10 == int(check)
