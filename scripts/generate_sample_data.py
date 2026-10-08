"""
Healthcare SAMPLE DATA generator
================================

Builds ``data/sample_data.ttl``: the synthetic INSTANCE data (patients, practitioners, organization, encounters,
diagnoses, observations, medications, prescriptions, allergies, ...). It never touches the schema.

    python scripts/generate_sample_data.py

Responsibilities, as distinct from ``scripts/generate_hc_ontology.py`` (which builds the schema only):

  1. read data/source/*.csv and check the DATA CONTRACT (services/sample_data.py)        -> fail early
  2. build individuals in a SEPARATE ontology whose individuals live in the schema's namespace, so existing
     IRIs such as ``...#PatientJohn`` are unchanged and the schema file stays free of instances
  3. merge with the schema and SHACL-validate the COMBINED graph                          -> fail before writing
  4. write Turtle atomically

The classes and properties it uses come from the schema module, imported in-process; the schema FILE is read
only for the combined validation.
"""
import datetime
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for entry in (ROOT, os.path.join(ROOT, "scripts")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from owlready2 import FunctionalProperty, get_ontology  # noqa: E402

import generate_hc_ontology as schema  # noqa: E402  (the TBox objects: classes, properties, vocabularies)
from core.dataset import DATA_IRI, DATA_RELATIVE, HC, SCHEMA_IRI, SCHEMA_RELATIVE  # noqa: E402
from services.reference_vocab import CODE_SYSTEMS  # noqa: E402

C, P, SPEC, GEN, ENC, CAT = schema.C, schema.P, schema.SPEC, schema.GEN, schema.ENC, schema.CAT
AnyURI, UTC = schema.AnyURI, schema.UTC

DATA_VERSION = "1.0.0"


def build_sample_data(data):
    """Create the individuals. Returns the data ontology that holds them (and nothing else)."""
    data_onto = get_ontology(DATA_IRI)
    namespace = data_onto.get_namespace(HC)  # new individuals get schema-namespace IRIs but are stored here
    with namespace:
        _build_sample_data(data)
    return data_onto


def _build_sample_data(data):
    def put(ind, **values):
        for key, val in values.items():
            prop = P[key]
            if FunctionalProperty in prop.is_a or any(
                FunctionalProperty in getattr(b, "is_a", []) for b in prop.is_a
            ):
                setattr(ind, key, val[0] if isinstance(val, list) else val)
            else:
                setattr(ind, key, val if isinstance(val, list) else [val])
        return ind

    def date(text):
        return datetime.date.fromisoformat(text)

    def dt(text):
        return datetime.datetime.fromisoformat(text)

    def split(text):
        return [v for v in text.split("|") if v]

    # ---- codes (CodeConcept: system + code + display) -----------------------------------------
    CODE = {}
    for r in data["codes"]:
        CODE[r["id"]] = put(C["CodeConcept"](r["id"]), codeSystem=AnyURI(CODE_SYSTEMS[r["system"]][0]),
                            codeValue=r["code"], codeDisplay=r["display"])

    # ---- organization and locations (scaffolding) -------------------------------------------------
    city = put(C["Hospital"]("CityHospital"), hospitalId="HOSP001", hospitalName="City General Hospital",
               hospitalLocation="New York", totalBeds=500)
    DEPT = {}

    def dept(name, dname, code, specialty=None):
        d = put(C["Department"](name), departmentName=dname, departmentCode=code)
        if specialty:
            d.hasSpecialty = [SPEC[specialty]]
        city.hasDepartment.append(d)
        DEPT[name] = d
        return d

    d_card = dept("CardiologyDept", "Cardiology", "CARD", "Cardiology")
    d_neuro = dept("NeurologyDept", "Neurology", "NEUR", "Neurology")
    dept("EmergencyDept", "Emergency", "ER", "EmergencyMedicine")
    dept("RadiologyDept", "Radiology", "RAD", "Radiology")
    dept("PharmacyDept", "Pharmacy", "PHAR")
    dept("LaboratoryDept", "Laboratory", "LAB", "LaboratoryMedicine")
    d_icu = dept("ICUDept", "Intensive Care", "ICU", "CriticalCare")

    ward_a, ward_b, ward_icu = C["Ward"]("WardA"), C["Ward"]("WardB"), C["Ward"]("WardICU")
    room_101, room_102, room_201, room_icu1 = (C["Room"](n) for n in ("Room101", "Room102", "Room201", "RoomICU1"))
    bed_1, bed_2, bed_3, bed_4 = (C["Bed"](n) for n in ("Bed1", "Bed2", "Bed3", "Bed4"))
    LOC = {"WardA": ward_a, "WardB": ward_b, "WardICU": ward_icu, "Room101": room_101, "Room102": room_102,
           "Room201": room_201, "RoomICU1": room_icu1, "Bed1": bed_1, "Bed2": bed_2, "Bed3": bed_3, "Bed4": bed_4}
    d_card.containsWard.append(ward_a)
    d_neuro.containsWard.append(ward_b)
    d_icu.containsWard.append(ward_icu)
    ward_a.containsRoom.extend([room_101, room_102])
    ward_b.containsRoom.append(room_201)
    ward_icu.containsRoom.append(room_icu1)
    room_101.containsBed.extend([bed_1, bed_2])
    room_201.containsBed.append(bed_3)
    room_icu1.containsBed.append(bed_4)
    ambulances = {"Ambulance001": C["Ambulance"]("Ambulance001")}

    # ---- practitioners ------------------------------------------------------------------------------
    PERSON = {}
    for r in data["practitioners"]:
        extra = {"yearsOfExperience": int(r["years_of_experience"])} if r["years_of_experience"] else {}
        who = put(C[r["kind"]](r["id"]), firstName=r["first_name"], lastName=r["last_name"],
                  administrativeGender=GEN[r["gender"]], dateOfBirth=date(r["date_of_birth"]), **extra)
        if r["specialty"]:
            who.hasSpecialty = [SPEC[r["specialty"]]]
        if r["license"]:
            ident = put(C["Identifier"]("IdLicense" + r["id"][2:]),
                        identifierSystem=AnyURI("https://medical-council.example.org/license"),
                        identifierValue=r["license"], identifierType="license")
            who.hasIdentifier.append(ident)
        who.worksInDepartment.append(DEPT[r["department"]])
        PERSON[r["id"]] = who

    # ---- patients --------------------------------------------------------------------------------------------
    for r in data["patients"]:
        who = put(C["Patient"](r["id"]), firstName=r["first_name"], lastName=r["last_name"],
                  administrativeGender=GEN[r["gender"]], dateOfBirth=date(r["date_of_birth"]),
                  bloodGroup=r["blood_group"])
        if r["mrn"]:
            mrn = put(C["Identifier"]("IdMrn" + r["id"][len("Patient"):]),
                      identifierSystem=AnyURI("https://cityhospital.example.org/mrn"),
                      identifierValue=r["mrn"], identifierType="MRN")
            mrn.identifierAssigner = city
            who.hasIdentifier.append(mrn)
        PERSON[r["id"]] = who

    # ---- medications (concepts); the category is a SKOS concept, never a subclass -----------------------------
    MED = {}
    for r in data["medications"]:
        m = put(C["Medication"](r["id"]), medicationName=r["name"])
        m.medicationCategory = [CAT[c] for c in split(r["categories"])]
        if r["code_id"]:
            m.hasCode = [CODE[r["code_id"]]]
        MED[r["id"]] = m

    # ---- encounters ----------------------------------------------------------------------------------------------
    ENCOUNTER = {}
    for r in data["encounters"]:
        e = put(C["Encounter"](r["id"]), encounterType=ENC[r["type"]], encounterStart=dt(r["start"]),
                encounterReason=r["reason"])
        if r["end"]:
            e.encounterEnd = dt(r["end"])
        e.encounterLocation = [LOC[r["location"]]] if r["location"] else []
        e.serviceProvider = [city]
        if r["transport"]:
            e.transportedBy = [ambulances[r["transport"]]]
        PERSON[r["patient_id"]].hasEncounter.append(e)
        for pid in split(r["participants"]):
            PERSON[pid].participatesIn.append(e)
        ENCOUNTER[r["id"]] = e

    # ---- diagnoses: one record PER patient; the kind of disease is the code, not the individual --------------------
    DX = {}
    for r in data["diagnoses"]:
        d = put(C["Diagnosis"](r["id"]), diagnosisName=r["name"], clinicalStatus=r["status"],
                onsetDate=date(r["onset_date"]), diagnosisDate=date(r["onset_date"]))
        d.hasCode = [CODE[c] for c in split(r["code_ids"])]
        d.diagnosedBy = [PERSON[r["doctor_id"]]]
        PERSON[r["patient_id"]].hasDiagnosis.append(d)
        ENCOUNTER[r["encounter_id"]].diagnoses.append(d)
        DX[r["id"]] = d

    # ---- observations ----------------------------------------------------------------------------------------------
    for r in data["observations"]:
        o = put(C[r["class"]](r["id"]), observationValue=float(r["value"]), observationUnit=r["unit"],
                effectiveDateTime=dt(r["effective"]))
        o.hasCode = [CODE[r["code_id"]]]
        if r["recorded_by"]:
            o.recordedBy = [PERSON[r["recorded_by"]]]
        PERSON[r["patient_id"]].hasObservation.append(o)
        if r["encounter_id"]:
            ENCOUNTER[r["encounter_id"]].includesObservation.append(o)

    # ---- prescriptions (dose belongs to the order, not to the drug) and allergies -----------------------------------
    for r in data["prescriptions"]:
        rx = put(C["Prescription"](r["id"]), prescriptionNumber=r["number"], prescriptionDate=date(r["date"]),
                 dosageInstruction=r["dose"])
        rx.prescribedFor = PERSON[r["patient_id"]]
        rx.prescribedBy = [PERSON[r["doctor_id"]]]
        rx.containsMedication = [MED[m] for m in split(r["medication_ids"])]
    for r in data["allergies"]:
        allergy = C["Allergy"](r["id"])
        allergy.allergyToMedication = [MED[r["medication_id"]]]
        PERSON[r["patient_id"]].hasAllergy.append(allergy)

    # ---- scaffolding that stays in code: procedure, appointments, treatments, tests, records, billing --------------
    patient_john, patient_emma, patient_david = PERSON["PatientJohn"], PERSON["PatientEmma"], PERSON["PatientDavid"]
    patient_alice = PERSON["PatientAlice"]
    dr_smith, dr_john, dr_kumar = PERSON["DrSmith"], PERSON["DrJohn"], PERSON["DrKumar"]
    enc_john = ENCOUNTER["Encounter001"]

    ecg = put(C["Procedure"]("Procedure001"), procedureName="Electrocardiogram",
              performedDateTime=datetime.datetime(2026, 3, 1, 9, 50, tzinfo=UTC))
    enc_john.involvesProcedure.append(ecg)

    appt_001 = put(C["Appointment"]("Appointment001"), appointmentId="APT001", appointmentStatus="Completed",
                   scheduledStart=datetime.datetime(2026, 3, 1, 9, 30, tzinfo=UTC), appointmentReason="Routine check")
    appt_001.appointmentWithDoctor = [dr_smith]
    appt_001.appointmentAtHospital = [city]
    appt_001.fulfilledBy = enc_john
    patient_john.hasAppointment.append(appt_001)
    appt_002 = put(C["Appointment"]("Appointment002"), appointmentId="APT002", appointmentStatus="Scheduled",
                   scheduledStart=datetime.datetime(2026, 11, 3, 13, 0, tzinfo=UTC), appointmentReason="Neurology follow-up")
    appt_002.appointmentWithDoctor = [dr_john]
    patient_emma.hasAppointment.append(appt_002)

    def treatment(cls, name, tname, status, doctor, patient, dx):
        t = put(C[cls](name), treatmentName=tname, treatmentStatus=status)
        t.performedByDoctor = [doctor]
        patient.receivesTreatment.append(t)
        dx.requiresTreatment.append(t)
        return t

    treatment("MedicationTreatment", "TreatmentBP", "Blood pressure management", "Active", dr_smith, patient_john, DX["DiagnosisHypertension"])
    treatment("MedicationTreatment", "TreatmentFlu", "Influenza symptom relief", "Completed", dr_kumar, patient_emma, DX["DiagnosisFlu"])
    treatment("PhysicalTherapy", "TreatmentNeuro", "Neurological rehabilitation", "Planned", dr_john, patient_david, DX["DiagnosisMigraine"])

    def test_with_result(tcls, tname, rname, patient, doctor, test_name, reviewer, **result_values):
        t = put(C[tcls](tname), testName=test_name, testDate=datetime.date(2026, 3, 1))
        res = put(C["DiagnosticResult"](rname), resultStatus="Final", **result_values)
        res.reviewedByDoctor = [reviewer]
        t.producesResult = [res]
        doctor.orderedTest.append(t)
        patient.underwentTest.append(t)
        patient.hasObservation.append(res)
        return t, res

    test_with_result("LaboratoryTest", "BloodTest001", "BloodResult001", patient_john, dr_smith,
                     "Complete blood count", dr_smith, observationValueText="Within reference ranges",
                     effectiveDateTime=datetime.datetime(2026, 3, 1, 12, 0, tzinfo=UTC))
    test_with_result("ImagingStudy", "MRI001", "MRIResult001", patient_david, dr_john,
                     "MRI brain", dr_john, observationValueText="No acute abnormality",
                     effectiveDateTime=datetime.datetime(2026, 3, 10, 0, 30, tzinfo=UTC))
    _t, _r = test_with_result("LaboratoryTest", "BloodTestAlice001", "ResultAlice001", patient_alice, dr_kumar,
                              "Hemoglobin A1c", dr_kumar, observationValue=7.2, observationUnit="%",
                              effectiveDateTime=datetime.datetime(2026, 3, 12, 11, 15, tzinfo=UTC))
    _t.hasCode = [CODE["Loinc_4548_4"]]
    _r.hasCode = [CODE["Loinc_4548_4"]]

    for r in data["patients"]:
        suffix = r["id"][len("Patient"):]
        PERSON[r["id"]].hasMedicalRecord.append(
            put(C["MedicalRecord"]("MR" + suffix), recordNumber="REC-" + suffix.upper(),
                recordCreatedDate=datetime.date(2026, 3, 1)))
    careplan = C["CarePlan"]("CarePlan001")
    careplan.createdByDoctor = [dr_smith]
    patient_john.followsCarePlan.append(careplan)
    policy = put(C["InsurancePolicy"]("PolicyA"), policyNumber="POL-A-1", insuranceProvider="Example Health Insurance")
    claim = C["InsuranceClaim"]("ClaimA")
    claim.claimAgainstPolicy = [policy]
    patient_john.coveredByInsurance.append(policy)
    billing = put(C["Billing"]("Billing001"), billingNumber="BILL-001", paymentStatus="Pending")
    billing.generatesInvoice = [put(C["Invoice"]("Invoice001"), invoiceNumber="INV-001",
                                    invoiceDate=datetime.date(2026, 3, 2))]
    billing.submitsClaim = [claim]
    patient_john.hasBilling.append(billing)


def generate(output_path, source_dir=None, schema_path=None, validate_output=True):
    """Source CSVs -> contract check -> individuals -> merge with the schema -> SHACL gate -> Turtle."""
    import tempfile
    from pathlib import Path

    from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef

    from core.dataset import parse_into, write_turtle
    from services import sample_data

    src = source_dir or sample_data.SOURCE_DIR
    rows = sample_data.load_dataset(src)
    sample_data.require_valid(rows, sample_data.load_drug_reference(), source_dir=src)  # fail early, before any RDF
    data_onto = build_sample_data(rows)

    fd, tmp = tempfile.mkstemp(suffix=".owl")
    os.close(fd)
    try:
        data_onto.save(file=tmp, format="rdfxml")
        graph = Graph().parse(tmp, format="xml")
    finally:
        os.unlink(tmp)

    header = URIRef(DATA_IRI)
    graph.add((header, RDF.type, OWL.Ontology))
    graph.add((header, OWL.imports, URIRef(SCHEMA_IRI)))
    graph.add((header, RDFS.label, Literal("Healthcare sample data (synthetic)")))
    graph.add((header, RDFS.comment, Literal(
        "Synthetic instance data for the healthcare ontology: no real persons. Generated by scripts/generate_sample_data.py "
        "from data/source/*.csv. The schema is ontology/healthcare_schema.ttl.")))
    graph.add((header, OWL.versionInfo, Literal(DATA_VERSION)))

    if validate_output:
        from core.shacl_validator import ShaclValidator

        combined = Graph()
        parse_into(combined, Path(schema_path or os.path.join(ROOT, SCHEMA_RELATIVE)))
        combined += graph
        result = ShaclValidator().validate_graph(combined, data_source="schema + generated sample data")
        if not result.summary.conforms:
            lines = [f"  {v.focus_node.split('#')[-1]}: {v.message}" for v in result.violations if v.severity != "Info"]
            raise SystemExit("schema + sample data fails SHACL; nothing was written:\n" + "\n".join(lines[:25]))

    comment = ("# Healthcare SAMPLE DATA (ABox): synthetic patients, encounters, medications, ... No real persons.\n"
               "# GENERATED by scripts/generate_sample_data.py from data/source/*.csv. Do not edit by hand.\n"
               "# The schema these instances are described by is ontology/healthcare_schema.ttl.\n")
    write_turtle(graph, output_path, {
        "hc": HC, "owl": "http://www.w3.org/2002/07/owl#", "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "xsd": "http://www.w3.org/2001/XMLSchema#",
    }, comment)
    return output_path


if __name__ == "__main__":
    import argparse

    from services.sample_data import DataContractError

    parser = argparse.ArgumentParser(description="Generate the synthetic sample data (data/sample_data.ttl)")
    parser.add_argument("--output", help=f"Output path (default: <project root>/{DATA_RELATIVE})")
    parser.add_argument("--source-dir", help="Directory of sample-data CSVs (default: data/source)")
    parser.add_argument("--schema", help=f"Schema file to validate against (default: {SCHEMA_RELATIVE})")
    parser.add_argument("--skip-shacl", action="store_true", help="Do not SHACL-validate schema + data (debugging only)")
    args = parser.parse_args()
    output_path = args.output or os.path.join(ROOT, DATA_RELATIVE)
    try:
        generate(output_path, args.source_dir, args.schema, validate_output=not args.skip_shacl)
    except DataContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
    print(f"Wrote {output_path} ({os.path.getsize(output_path) / 1024:.1f} KB)")
    print(f"individuals={len(list(get_ontology(DATA_IRI).individuals()))}")
