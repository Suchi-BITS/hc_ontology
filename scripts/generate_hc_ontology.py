"""
Healthcare Hospital Ontology generator (v2)
===========================================

Single source of truth for ``ontology/healthcare_schema.ttl``: the SCHEMA only (TBox plus controlled
vocabularies). Synthetic instance data is a separate artifact, built by ``scripts/generate_sample_data.py``.

    python scripts/generate_hc_ontology.py

The design rationale is in ``docs/ontology-engineering.md``. In short:

* OWL carries *meaning* (class hierarchy, property characteristics, inverses,
  disjointness, a few defined classes).  It does NOT carry "required field"
  rules - under the open-world assumption a cardinality restriction does not
  validate anything.  Those rules live in ``shapes/*.ttl`` (SHACL).
* Controlled vocabularies (specialty, administrative gender, encounter type,
  medication category) are SKOS concepts, typed by a small OWL class so that
  domains/ranges stay precise.
* External terminologies are never copied in.  A ``CodeConcept``
  (codeSystem + codeValue + codeDisplay) is the binding pattern.
* Asserted relationship direction: inverse properties are declared, but the
  sample data asserts one canonical direction only (Owlready2 stores a single
  triple); the other direction is inferred by a reasoner.
"""
import datetime
import os
import re
import sys
import types

from owlready2 import (
    AllDisjoint,
    AnnotationProperty,
    DataProperty,
    FunctionalProperty,
    ObjectProperty,
    Or,
    Thing,
    TransitiveProperty,
    declare_datatype,
    get_ontology,
    locstr,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.reference_vocab import (  # noqa: E402  (vocabularies are defined once, shared with the data contract)
    ENCOUNTER_TYPES, GENDERS, MEDICATION_CATEGORIES, SPECIALTIES,
)

ONTOLOGY_IRI = "http://example.org/healthcare-hospital.owl"
ONTOLOGY_VERSION = "2.0.0"
UTC = datetime.timezone.utc


class AnyURI(str):
    """Python carrier for xsd:anyURI (Owlready2 has no built-in mapping)."""


declare_datatype(AnyURI, "http://www.w3.org/2001/XMLSchema#anyURI", AnyURI, str)

onto = get_ontology(ONTOLOGY_IRI + "#")
skos = get_ontology("http://www.w3.org/2004/02/skos/core#")

with skos:
    # Only the SKOS terms we use. They are referenced by IRI; SKOS is not copied
    # into our file.
    class Concept(Thing):
        pass

    class ConceptScheme(Thing):
        pass

    class inScheme(ObjectProperty):
        pass

    class prefLabel(AnnotationProperty):
        pass

    class notation(AnnotationProperty):
        pass


def _auto_label(name):
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return words if name[0].isupper() else words.lower()


with onto:
    # ========================================================================
    # CLASSES   (name, parent, comment)   - label is derived from the name
    # ========================================================================
    CLASSES = [
        # --- people -------------------------------------------------------
        ("Person", Thing, "A human being. Roles (patient, practitioner) are classes here for simplicity; a person who is both is typed with both."),
        ("Patient", "Person", "A person who receives, or is registered to receive, healthcare services."),
        ("Practitioner", "Person", "A person who delivers clinical care or clinical support in a healthcare setting."),
        ("Doctor", "Practitioner", "A licensed medical practitioner. Clinical specialty is NOT a subclass: see hasSpecialty."),
        ("Nurse", "Practitioner", "A practitioner providing nursing care."),
        ("Pharmacist", "Practitioner", "A practitioner who dispenses and advises on medication."),
        ("Technician", "Practitioner", "A practitioner who performs technical or diagnostic support work."),
        ("Administrator", "Person", "A non-clinical staff member who manages organizational units."),
        ("Receptionist", "Person", "A non-clinical staff member handling front-desk administration."),
        ("InsuranceAgent", "Person", "A person acting for an insurer in coverage or claim matters."),
        # --- organizations and places ------------------------------------
        ("Organization", Thing, "A formally or informally recognized group of people that provides or administers healthcare."),
        ("Hospital", "Organization", "An organization providing inpatient and outpatient medical services."),
        ("Department", "Organization", "An organizational unit of a hospital, optionally focused on a clinical specialty."),
        ("Location", Thing, "A physical place where care can be delivered or a patient can be placed."),
        ("Ward", "Location", "A group of rooms within a hospital operated for a category of care."),
        ("Room", "Location", "A room within a ward, used to place beds and patients."),
        ("Bed", "Location", "A single bed within a room; the smallest placement unit."),
        ("Ambulance", Thing, "A vehicle used to transport patients to or between care locations."),
        ("MedicalDevice", Thing, "A device used in diagnosis or treatment."),
        # --- clinical events and facts -----------------------------------
        ("Encounter", Thing, "An interaction between a patient and healthcare practitioners during which care is delivered. It occurred (or is occurring); a future booking is an Appointment."),
        ("Appointment", Thing, "A planned booking of a patient with a practitioner. It may be fulfilled by an Encounter."),
        ("Condition", Thing, "A clinical problem, disease, or health state of a patient, recorded for one patient at a point in time."),
        ("Diagnosis", "Condition", "A Condition established by a clinician's judgement."),
        ("Observation", Thing, "A measurement or assertion about a patient made at a point in time, such as a vital sign or a result."),
        ("VitalSign", "Observation", "An Observation of a basic physiological measure such as blood pressure."),
        ("DiagnosticResult", "Observation", "An Observation that is the outcome of a diagnostic test."),
        ("Procedure", Thing, "An action performed on or for a patient, such as a surgery or an electrocardiogram."),
        ("Surgery", "Procedure", "A Procedure that involves cutting or other operative intervention."),
        ("Treatment", Thing, "A planned therapeutic intervention intended to address a condition."),
        ("MedicationTreatment", "Treatment", "A Treatment delivered primarily through medication."),
        ("PhysicalTherapy", "Treatment", "A Treatment delivered through physical rehabilitation."),
        ("RadiationTherapy", "Treatment", "A Treatment delivered through ionizing radiation."),
        ("Chemotherapy", "Treatment", "A Treatment delivered through cytotoxic drugs."),
        ("SurgicalTreatment", "Treatment", "A Treatment that centres on a Surgery."),
        ("DiagnosticTest", Thing, "An examination ordered to obtain diagnostic information."),
        ("LaboratoryTest", "DiagnosticTest", "A DiagnosticTest performed on a specimen in a laboratory."),
        ("ImagingStudy", "DiagnosticTest", "A DiagnosticTest that produces images, for example MRI or X-ray. Not a laboratory test."),
        ("CarePlan", Thing, "A plan of care created by a practitioner for a patient."),
        ("MedicalRecord", Thing, "The container for a patient's clinical documentation."),
        ("ClinicalNote", Thing, "A free-text clinical document authored by a practitioner."),
        # --- medication ---------------------------------------------------
        ("Medication", Thing, "A drug as a concept (for example metformin), not a dispensed package or a patient's dose."),
        ("Prescription", Thing, "An order by a practitioner to supply medication to a patient (equivalent to a FHIR MedicationRequest)."),
        ("Allergy", Thing, "A patient's recorded adverse reaction to a substance (equivalent to a FHIR AllergyIntolerance)."),
        ("Vaccination", Thing, "An administration of a vaccine to a patient."),
        # --- administrative / financial ----------------------------------
        ("InsurancePolicy", Thing, "A health insurance coverage agreement."),
        ("InsuranceClaim", Thing, "A request to an insurer for payment of services."),
        ("Billing", Thing, "A billing account entry for services provided to a patient."),
        ("Invoice", Thing, "A request for payment issued from a Billing entry."),
        # --- identification and terminology -------------------------------
        ("Identifier", Thing, "A business identifier assigned by an issuing system, for example a medical record number or a license number."),
        ("CodeConcept", Thing, "A reference to a concept in an external code system (codeSystem + codeValue + codeDisplay). The terminology itself is not stored."),
        # --- controlled vocabularies (SKOS concepts) ----------------------
        ("Specialty", skos.Concept, "A clinical specialty such as cardiology. A SKOS concept, not a class hierarchy of practitioners."),
        ("AdministrativeGender", skos.Concept, "The administrative gender used for record keeping (male, female, other, unknown)."),
        ("EncounterType", skos.Concept, "The setting of an Encounter: ambulatory, inpatient, emergency, or virtual."),
        ("MedicationCategory", skos.Concept, "A therapeutic category of a Medication, such as analgesic or antidiabetic."),
    ]

    C = {}
    for _name, _parent, _comment in CLASSES:
        _base = _parent if not isinstance(_parent, str) else C[_parent]
        C[_name] = types.new_class(_name, (_base,))
        C[_name].label = [_auto_label(_name)]
        C[_name].comment = [_comment]

    # ========================================================================
    # PROPERTIES
    # ========================================================================
    P = {}
    _INVERSES = []

    def _classes(spec):
        if spec is None:
            return None
        if isinstance(spec, (list, tuple)):
            return [Or([C[s] for s in spec])] if len(spec) > 1 else [C[spec[0]]]
        return [C[spec]]

    def obj(name, domain, range_, comment, inverse=None, parent=None,
            functional=False, transitive=False):
        bases = [P[parent]] if parent else [ObjectProperty]
        if functional:
            bases.append(FunctionalProperty)
        if transitive:
            bases.append(TransitiveProperty)
        prop = types.new_class(name, tuple(bases))
        if domain is not None:
            prop.domain = _classes(domain)
        if range_ is not None:
            prop.range = _classes(range_)
        prop.label = [_auto_label(name)]
        prop.comment = [comment]
        P[name] = prop
        if inverse:
            _INVERSES.append((name, inverse))
        return prop

    # Single-valued attributes are FUNCTIONAL by default: "at most one value" is meaning
    # the Neo4j projection relies on to store a scalar instead of a list. Genuinely
    # multi-valued attributes opt out with functional=False.
    def data(name, domain, range_, comment, functional=True):
        bases = [DataProperty] + ([FunctionalProperty] if functional else [])
        prop = types.new_class(name, tuple(bases))
        prop.domain = _classes(domain)
        prop.range = [range_]  # note: xsd:date is outside the OWL 2 datatype map (see docs)
        prop.label = [_auto_label(name)]
        prop.comment = [comment]
        P[name] = prop
        return prop

    # ---- organization, location ------------------------------------------
    obj("hasDepartment", "Hospital", "Department", "A hospital has this department.", inverse="belongsToHospital")
    obj("belongsToHospital", "Department", "Hospital", "The hospital that this department is part of. Inferred as the inverse of hasDepartment.")
    obj("containsWard", "Department", "Ward", "A department operates this ward.", inverse="wardOfDepartment")
    obj("wardOfDepartment", "Ward", "Department", "The department that operates this ward. Inferred as the inverse of containsWard.", functional=True)
    obj("partOfLocation", "Location", "Location", "Transitive physical containment: a bed is part of its room, ward and so on.", transitive=True)
    obj("locatedInWard", "Room", "Ward", "The ward containing this room. Inverse of containsRoom.", parent="partOfLocation")
    obj("locatedInRoom", "Bed", "Room", "The room containing this bed. Inverse of containsBed.", parent="partOfLocation")
    obj("containsRoom", "Ward", "Room", "A ward contains this room.", inverse="locatedInWard")
    obj("containsBed", "Room", "Bed", "A room contains this bed.", inverse="locatedInRoom")
    obj("worksInDepartment", "Person", "Department", "A person works in this department.", inverse="hasStaffMember")
    obj("hasStaffMember", "Department", "Person", "A person who works in this department. Inferred as the inverse of worksInDepartment.")
    obj("reportsTo", "Person", "Person", "A person reports to another person in the staff hierarchy.", inverse="supervises")
    obj("supervises", "Person", "Person", "A person who reports to this person in the staff hierarchy. Inferred as the inverse of reportsTo.")
    obj("managesDepartment", "Administrator", "Department", "An administrator manages this department.", inverse="managedBy")
    obj("managedBy", "Department", "Administrator", "An administrator who manages this department. Inferred as the inverse of managesDepartment.")

    # ---- encounter ---------------------------------------------------------
    obj("hasEncounter", "Patient", "Encounter", "A patient took part in this encounter.", inverse="encounterForPatient")
    obj("encounterForPatient", "Encounter", "Patient", "The patient who is the subject of this encounter. Inferred as the inverse of hasEncounter.", functional=True)
    obj("participatesIn", "Practitioner", "Encounter", "A practitioner took part in this encounter.", inverse="hasParticipant")
    obj("hasParticipant", "Encounter", "Practitioner", "A practitioner who took part in this encounter. Inferred as the inverse of participatesIn.")
    obj("diagnoses", "Encounter", "Condition", "A condition identified or confirmed during this encounter.", inverse="diagnosedIn")
    obj("diagnosedIn", "Condition", "Encounter", "The encounter during which this condition was identified. Inferred as the inverse of diagnoses.")
    obj("includesObservation", "Encounter", "Observation", "An observation made during this encounter.", inverse="observedDuring")
    obj("observedDuring", "Observation", "Encounter", "The encounter during which this observation was made. Inferred as the inverse of includesObservation.")
    obj("involvesProcedure", "Encounter", "Procedure", "A procedure performed during this encounter.", inverse="performedDuring")
    obj("performedDuring", "Procedure", "Encounter", "The encounter during which this procedure was performed. Inferred as the inverse of involvesProcedure.")
    obj("encounterType", "Encounter", "EncounterType", "The care setting of this encounter.", functional=True)
    obj("encounterLocation", "Encounter", "Location", "Where the encounter took place.")
    obj("serviceProvider", "Encounter", "Organization", "The organization responsible for the encounter.")
    obj("transportedBy", "Encounter", "Ambulance", "The ambulance that brought the patient to this encounter.")
    obj("fulfilledBy", "Appointment", "Encounter", "The encounter that fulfilled this appointment.", inverse="fulfillsAppointment", functional=True)
    obj("fulfillsAppointment", "Encounter", "Appointment", "The appointment that this encounter fulfilled. Inferred as the inverse of fulfilledBy.")

    # ---- patient records ---------------------------------------------------
    obj("hasMedicalRecord", "Patient", "MedicalRecord", "The medical record of a patient.")
    obj("coveredByInsurance", "Patient", "InsurancePolicy", "The insurance policy covering a patient.")
    obj("hasAppointment", "Patient", "Appointment", "A patient has this appointment.", inverse="appointmentForPatient")
    obj("appointmentForPatient", "Appointment", "Patient", "The patient an appointment is for. Inferred as the inverse of hasAppointment.", functional=True)
    obj("appointmentWithDoctor", "Appointment", "Doctor", "The doctor an appointment is booked with.")
    obj("appointmentAtHospital", "Appointment", "Hospital", "The hospital where an appointment takes place.")

    # ---- conditions ----------------------------------------------------------
    obj("hasCondition", "Patient", "Condition", "A patient has this condition.", inverse="conditionSubject")
    obj("conditionSubject", "Condition", "Patient", "The patient a condition belongs to. A condition record belongs to exactly one patient.", functional=True)
    obj("hasDiagnosis", "Patient", "Diagnosis", "A patient has this diagnosis.", parent="hasCondition", inverse="diagnosisForPatient")
    obj("diagnosisForPatient", "Diagnosis", "Patient", "The patient a diagnosis belongs to. Inferred as the inverse of hasDiagnosis.", parent="conditionSubject")
    obj("diagnosedBy", "Diagnosis", "Doctor", "The doctor who established this diagnosis.", inverse="madeDiagnosis")
    obj("madeDiagnosis", "Doctor", "Diagnosis", "A diagnosis this doctor established. Inferred as the inverse of diagnosedBy.")
    obj("requiresTreatment", "Diagnosis", "Treatment", "A treatment that this diagnosis calls for.", inverse="treatsDiagnosis")
    obj("treatsDiagnosis", "Treatment", "Diagnosis", "A diagnosis that this treatment addresses. Inferred as the inverse of requiresTreatment.")

    # ---- treatment, procedure ------------------------------------------------
    obj("receivesTreatment", "Patient", "Treatment", "A treatment a patient receives.", inverse="treatmentForPatient")
    obj("treatmentForPatient", "Treatment", "Patient", "The patient who receives this treatment. Inferred as the inverse of receivesTreatment.", functional=True)
    obj("performedByDoctor", "Treatment", "Doctor", "The doctor responsible for a treatment.")
    obj("includesProcedure", "Treatment", "Procedure", "A procedure that is part of a treatment.")
    obj("involvesSurgery", "Treatment", "Surgery", "A surgery that is part of a treatment.", parent="includesProcedure")
    obj("usesMedicalDevice", "Treatment", "MedicalDevice", "A device used in a treatment.")

    # ---- medication, allergy, vaccination -----------------------------------
    obj("prescribedFor", "Prescription", "Patient", "The patient a prescription is for.", inverse="hasPrescription", functional=True)
    obj("hasPrescription", "Patient", "Prescription", "A prescription issued for a patient. Inferred as the inverse of prescribedFor.")
    obj("prescribedBy", "Prescription", "Doctor", "The doctor who issued a prescription.", inverse="issuedPrescription")
    obj("issuedPrescription", "Doctor", "Prescription", "A prescription this doctor issued. Inferred as the inverse of prescribedBy.")
    obj("containsMedication", "Prescription", "Medication", "A medication listed on a prescription.", inverse="containedInPrescription")
    obj("containedInPrescription", "Medication", "Prescription", "A prescription that lists this medication. Inferred as the inverse of containsMedication.")
    obj("medicationCategory", "Medication", "MedicationCategory", "A therapeutic category of a medication. A medication may have several.")
    obj("hasAllergy", "Patient", "Allergy", "An allergy recorded for a patient.", inverse="allergyForPatient")
    obj("allergyForPatient", "Allergy", "Patient", "The patient this allergy is recorded for. Inferred as the inverse of hasAllergy.", functional=True)
    obj("allergyToMedication", "Allergy", "Medication", "The medication that a patient is allergic to.")
    obj("hasVaccination", "Patient", "Vaccination", "A vaccination given to a patient.")
    obj("administeredBy", "Vaccination", "Practitioner", "The practitioner who gave a vaccination.")

    # ---- diagnostic tests and observations ----------------------------------
    obj("orderedTest", "Practitioner", "DiagnosticTest", "A diagnostic test ordered by a practitioner.", inverse="orderedBy")
    obj("orderedBy", "DiagnosticTest", "Practitioner", "The practitioner who ordered this test. Inferred as the inverse of orderedTest.", functional=True)
    obj("underwentTest", "Patient", "DiagnosticTest", "A diagnostic test performed on a patient.", inverse="testForPatient")
    obj("testForPatient", "DiagnosticTest", "Patient", "The patient this test was performed on. Inferred as the inverse of underwentTest.", functional=True)
    obj("producesResult", "DiagnosticTest", "DiagnosticResult", "The result produced by a test.", inverse="resultOfTest")
    obj("resultOfTest", "DiagnosticResult", "DiagnosticTest", "The test that produced a result. Inferred as the inverse of producesResult.")
    obj("reviewedByDoctor", "DiagnosticResult", "Doctor", "The doctor who reviewed a result.")
    obj("hasObservation", "Patient", "Observation", "An observation made about a patient.", inverse="observationForPatient")
    obj("observationForPatient", "Observation", "Patient", "The patient an observation is about. Inferred as the inverse of hasObservation.", functional=True)
    obj("recordedBy", "Observation", "Practitioner", "The practitioner who recorded an observation.")

    # ---- care plan, notes, billing ------------------------------------------
    obj("followsCarePlan", "Patient", "CarePlan", "A care plan that a patient follows.")
    obj("createdByDoctor", "CarePlan", "Doctor", "The doctor who created a care plan.")
    obj("hasClinicalNote", "MedicalRecord", "ClinicalNote", "A note filed in a medical record.")
    obj("authoredBy", "ClinicalNote", "Practitioner", "The practitioner who wrote a note.")
    obj("hasBilling", "Patient", "Billing", "A billing entry for a patient.")
    obj("generatesInvoice", "Billing", "Invoice", "An invoice generated from a billing entry.")
    obj("submitsClaim", "Billing", "InsuranceClaim", "A claim submitted from a billing entry.")
    obj("claimAgainstPolicy", "InsuranceClaim", "InsurancePolicy", "The policy a claim is made against.")

    # ---- vocabulary, identification, coding ----------------------------------
    obj("administrativeGender", "Person", "AdministrativeGender", "The administrative gender recorded for a person.", functional=True)
    obj("hasSpecialty", ["Practitioner", "Department"], "Specialty", "A clinical specialty of a practitioner or of a department.")
    obj("hasIdentifier", ["Person", "Organization"], "Identifier", "A business identifier of a person or an organization.")
    obj("identifierAssigner", "Identifier", "Organization", "The organization that issued an identifier.", functional=True)
    obj("hasCode", ["Condition", "Observation", "Medication", "Procedure", "DiagnosticTest"], "CodeConcept", "Binds an entity to a concept in an external code system. An entity may have several codings (for example ICD-10 and SNOMED CT).")

    for _a, _b in _INVERSES:
        P[_a].inverse_property = P[_b]

    # ---- data properties ----------------------------------------------------
    data("firstName", "Person", str, "Given name. A display attribute, never an identity.")
    data("lastName", "Person", str, "Family name. A display attribute, never an identity.")
    data("dateOfBirth", "Person", datetime.date, "Calendar date of birth. xsd:date, no time zone: a birth date is a calendar date, not an instant.", functional=True)
    data("phoneNumber", "Person", str, "Contact telephone number.", functional=False)
    data("emailAddress", "Person", str, "Contact e-mail address.", functional=False)
    data("address", "Person", str, "Postal address as free text.", functional=False)
    data("bloodGroup", "Patient", str, "ABO/Rh blood group, for example O+.")
    data("maritalStatus", "Patient", str, "Marital status as free text.")
    data("emergencyContact", "Patient", str, "Emergency contact as free text.", functional=False)
    data("patientStatus", "Patient", str, "Administrative status of the patient record.")
    data("yearsOfExperience", "Doctor", int, "Years of professional experience.")
    data("consultationFee", "Doctor", float, "Standard consultation fee.")
    data("shiftType", "Nurse", str, "Usual shift pattern.")
    data("hospitalId", "Hospital", str, "Local hospital code.")
    data("hospitalName", "Hospital", str, "Display name of the hospital.")
    data("hospitalLocation", "Hospital", str, "Town or city of the hospital.")
    data("hospitalType", "Hospital", str, "Kind of hospital, for example teaching or community.")
    data("totalBeds", "Hospital", int, "Total number of beds.")
    data("departmentCode", "Department", str, "Local department code.")
    data("departmentName", "Department", str, "Display name of the department.")
    data("roomNumber", "Room", str, "Room number.")
    data("roomType", "Room", str, "Kind of room.")
    data("floorNumber", "Room", int, "Floor on which the room is located.")
    data("bedNumber", "Bed", str, "Bed number.")
    data("bedStatus", "Bed", str, "Occupancy status of the bed.")
    # Encounter / appointment
    data("encounterStart", "Encounter", datetime.datetime, "Instant the encounter began. xsd:dateTime WITH a time zone offset (an instant must be unambiguous).", functional=True)
    data("encounterEnd", "Encounter", datetime.datetime, "Instant the encounter ended. xsd:dateTime with a time zone offset.", functional=True)
    data("encounterReason", "Encounter", str, "Reason for the encounter as free text.")
    data("appointmentId", "Appointment", str, "Local appointment number.")
    data("scheduledStart", "Appointment", datetime.datetime, "Planned start instant. xsd:dateTime with a time zone offset.", functional=True)
    data("appointmentStatus", "Appointment", str, "Booking status (for example Scheduled, Completed).")
    data("appointmentReason", "Appointment", str, "Reason for the appointment.")
    # Records, conditions, observations
    data("recordNumber", "MedicalRecord", str, "Local medical record number.")
    data("recordCreatedDate", "MedicalRecord", datetime.date, "Calendar date the record was opened.", functional=True)
    data("clinicalStatus", "Condition", str, "Clinical status: active, recurrence, remission or resolved.", functional=True)
    data("onsetDate", "Condition", datetime.date, "Date the condition began. xsd:date because onset is rarely known more precisely.", functional=True)
    data("abatementDate", "Condition", datetime.date, "Date the condition resolved.", functional=True)
    data("diagnosisName", "Diagnosis", str, "Human-readable name of the diagnosis.")
    data("diagnosisDescription", "Diagnosis", str, "Free-text description of the diagnosis.")
    data("diagnosisDate", "Diagnosis", datetime.date, "Date the diagnosis was established.", functional=True)
    data("effectiveDateTime", "Observation", datetime.datetime, "Instant the observation applies to. xsd:dateTime with a time zone offset.", functional=True)
    data("observationValue", "Observation", float, "Numeric result. Always accompanied by observationUnit.", functional=True)
    data("observationUnit", "Observation", str, "Unit of observationValue, as a UCUM code.", functional=True)
    data("observationValueText", "Observation", str, "Non-numeric result as text.", functional=False)
    data("resultStatus", "DiagnosticResult", str, "Status of the result (for example Preliminary, Final).")
    # Treatment, procedure
    data("treatmentId", "Treatment", str, "Local treatment number.")
    data("treatmentName", "Treatment", str, "Display name of the treatment.")
    data("treatmentStatus", "Treatment", str, "Planned, Active, Completed or Cancelled.")
    data("treatmentCost", "Treatment", float, "Cost of the treatment.")
    data("procedureName", "Procedure", str, "Display name of the procedure.")
    data("performedDateTime", "Procedure", datetime.datetime, "Instant the procedure was performed. xsd:dateTime with a time zone offset.", functional=True)
    data("surgeryDurationMinutes", "Surgery", int, "Duration of the surgery in minutes.")
    # Tests
    data("testName", "DiagnosticTest", str, "Display name of the test.")
    data("testDate", "DiagnosticTest", datetime.date, "Calendar date the test was performed.", functional=True)
    # Medication
    data("medicationName", "Medication", str, "Display name of the medication.")
    data("manufacturer", "Medication", str, "Manufacturer of a medication product.")
    data("isControlledSubstance", "Medication", bool, "Whether the drug is a controlled substance. A regulatory status, not a therapeutic category.", functional=True)
    data("prescriptionNumber", "Prescription", str, "Local prescription number.")
    data("prescriptionDate", "Prescription", datetime.date, "Calendar date the prescription was issued.", functional=True)
    data("dosageInstruction", "Prescription", str, "Dose and schedule for this patient. A property of the order, not of the drug.")
    # Financial
    data("policyNumber", "InsurancePolicy", str, "Policy number.")
    data("insuranceProvider", "InsurancePolicy", str, "Insurer name.")
    data("coverageAmount", "InsurancePolicy", float, "Coverage limit.")
    data("billingNumber", "Billing", str, "Billing reference.")
    data("billingAmount", "Billing", float, "Billed amount.")
    data("paymentStatus", "Billing", str, "Payment status.")
    data("invoiceNumber", "Invoice", str, "Invoice number.")
    data("invoiceDate", "Invoice", datetime.date, "Calendar date of the invoice.", functional=True)
    # Identification and coding
    data("identifierSystem", "Identifier", AnyURI, "IRI naming the system that issued the identifier.", functional=True)
    data("identifierValue", "Identifier", str, "The identifier value, unique within its system.", functional=True)
    data("identifierType", "Identifier", str, "Kind of identifier, for example MRN or license.", functional=True)
    data("codeSystem", "CodeConcept", AnyURI, "IRI of the external code system (for example http://loinc.org).", functional=True)
    data("codeValue", "CodeConcept", str, "The code within the code system.", functional=True)
    data("codeDisplay", "CodeConcept", str, "Human-readable display text of the code.", functional=True)

    # ========================================================================
    # AXIOMS - only where they carry meaning that a reasoner can use
    # ========================================================================
    # Top-level categories do not overlap. Roles (Patient/Practitioner) are NOT
    # disjoint: a nurse can be a patient.
    AllDisjoint([C[n] for n in (
        "Person", "Organization", "Location", "Encounter", "Appointment", "Condition",
        "Observation", "Procedure", "Treatment", "DiagnosticTest", "Medication",
        "Prescription", "Allergy", "Identifier", "CodeConcept", "CarePlan",
    )])
    AllDisjoint([C[n] for n in ("Specialty", "AdministrativeGender", "EncounterType", "MedicationCategory")])
    AllDisjoint([C["LaboratoryTest"], C["ImagingStudy"]])
    AllDisjoint([C[n] for n in ("Ward", "Room", "Bed")])

    # ========================================================================
    # CONTROLLED VOCABULARIES (SKOS)
    # ========================================================================
    def scheme(name, label):
        s = skos.ConceptScheme(name)
        s.label = [label]
        s.prefLabel = [locstr(label, "en")]
        return s

    def concept(cls, name, label, scheme_ind, code=None):
        ind = cls(name)
        ind.label = [label]
        ind.prefLabel = [locstr(label, "en")]
        ind.inScheme = [scheme_ind]
        if code:
            ind.notation = [code]
        return ind

    s_spec = scheme("SpecialtyScheme", "Clinical specialties (illustrative subset)")
    SPEC = {n: concept(C["Specialty"], "Specialty" + n, lbl, s_spec) for n, lbl in SPECIALTIES.items()}

    s_gen = scheme("AdministrativeGenderScheme", "Administrative gender")
    GEN = {n: concept(C["AdministrativeGender"], "Gender" + n, n, s_gen, code=n.lower()) for n in GENDERS}

    s_enc = scheme("EncounterTypeScheme", "Encounter type")
    ENC = {n: concept(C["EncounterType"], "EncounterType" + n, lbl, s_enc, code=code)
           for n, (lbl, code) in ENCOUNTER_TYPES.items()}

    s_cat = scheme("MedicationCategoryScheme", "Medication category")
    CAT = {n: concept(C["MedicationCategory"], "MedCategory" + n, lbl, s_cat) for n, lbl in MEDICATION_CATEGORIES.items()}

    # Defined classes: membership is INFERRED from category/type, replacing the old
    # hand-assigned subclasses (the source of "metformin is an Analgesic").
    class AntidiabeticMedication(C["Medication"]):
        equivalent_to = [C["Medication"] & P["medicationCategory"].value(CAT["Antidiabetic"])]
    AntidiabeticMedication.label = ["antidiabetic medication"]
    AntidiabeticMedication.comment = ["A Medication categorized as antidiabetic. Defined, not asserted: a reasoner classifies medications into it."]
    C["AntidiabeticMedication"] = AntidiabeticMedication

    class InpatientEncounter(C["Encounter"]):
        equivalent_to = [C["Encounter"] & P["encounterType"].value(ENC["Inpatient"])]
    InpatientEncounter.label = ["inpatient encounter"]
    InpatientEncounter.comment = ["An Encounter whose encounterType is Inpatient. Defined, not asserted."]
    C["InpatientEncounter"] = InpatientEncounter

    # ---- ontology header ----------------------------------------------------------------------------
    onto.metadata.label.append("Healthcare Hospital Ontology")
    onto.metadata.comment.append(
        "A small, bounded teaching ontology for hospital care: people, organizations, encounters, "
        "conditions, observations, medication and terminology binding. Not a clinical system. "
        "See docs/ontology-engineering.md."
    )
    onto.metadata.versionInfo.append(ONTOLOGY_VERSION)


VOCABULARY_CLASSES = {"Specialty", "AdministrativeGender", "EncounterType", "MedicationCategory", "ConceptScheme"}


def schema_problems(graph):
    """Reasons this graph is not a pure schema. Individuals are allowed ONLY if they are controlled-vocabulary
    concepts or schemes (SKOS): those are part of the ontology's vocabulary, not synthetic data."""
    from rdflib import OWL, RDF

    problems = []
    for ind in graph.subjects(RDF.type, OWL.NamedIndividual):
        types = {str(t).split("#")[-1] for t in graph.objects(ind, RDF.type) if t != OWL.NamedIndividual}
        if not types & VOCABULARY_CLASSES:
            problems.append(f"{str(ind).split('#')[-1]} (a {', '.join(sorted(types)) or 'thing'}) is an individual, not schema")
    return problems


def generate(output_path, validate_output=True):
    """Build the schema (TBox + controlled vocabularies) and write it as Turtle, atomically.

    This script generates the SCHEMA ONLY. Synthetic patients, encounters, medications and the rest are
    generated by scripts/generate_sample_data.py into data/sample_data.ttl. Nothing is written if the result
    contains an individual that is not a vocabulary concept.
    """
    import tempfile

    from rdflib import Graph

    from core.dataset import HC, write_turtle

    fd, tmp = tempfile.mkstemp(suffix=".owl")
    os.close(fd)
    try:
        onto.save(file=tmp, format="rdfxml")
        graph = Graph().parse(tmp, format="xml")
    finally:
        os.unlink(tmp)
    problems = schema_problems(graph)
    if problems:
        raise SystemExit("the schema contains instance data; nothing was written:\n  " + "\n  ".join(problems[:20]))
    if validate_output:
        from core.shacl_validator import ShaclValidator

        result = ShaclValidator().validate_graph(graph, data_source="schema")
        if not result.summary.conforms:
            lines = [f"  {v.focus_node.split('#')[-1]}: {v.message}" for v in result.violations if v.severity != "Info"]
            raise SystemExit("the schema fails SHACL; nothing was written:\n" + "\n".join(lines[:25]))
    header = ("# Healthcare ontology SCHEMA (TBox + controlled vocabularies). GENERATED by scripts/generate_hc_ontology.py.\n"
              "# Do not edit by hand. Synthetic instance data lives in data/sample_data.ttl.\n")
    write_turtle(graph, output_path, {
        "hc": HC, "owl": "http://www.w3.org/2002/07/owl#", "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "xsd": "http://www.w3.org/2001/XMLSchema#",
        "skos": "http://www.w3.org/2004/02/skos/core#",
    }, header)
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate the healthcare ontology SCHEMA (ontology/healthcare_schema.ttl)")
    parser.add_argument("--output", help="Output path (default: <project root>/ontology/healthcare_schema.ttl)")
    parser.add_argument("--skip-shacl", action="store_true", help="Do not SHACL-validate the generated schema (debugging only)")
    args = parser.parse_args()
    output_path = args.output or os.path.join(ROOT, "ontology", "healthcare_schema.ttl")
    generate(output_path, validate_output=not args.skip_shacl)
    print(f"Wrote {output_path} ({os.path.getsize(output_path) / 1024:.1f} KB)")
    print(f"classes={len(list(onto.classes()))} object_properties={len(list(onto.object_properties()))} "
          f"data_properties={len(list(onto.data_properties()))} vocabulary_individuals={len(list(onto.individuals()))}")
