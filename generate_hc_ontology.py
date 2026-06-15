"""
Healthcare Hospital Ontology Generator
======================================

Generates:
    healthcare_hospital_ontology.owl

Install:
    pip install owlready2

Run:
    python healthcare_hospital_ontology.py

Import output OWL into Protege.
"""
from owlready2 import (
    get_ontology,
    Thing,
    ObjectProperty,
    DataProperty,
    FunctionalProperty,
    SymmetricProperty,
    TransitiveProperty,
    InverseFunctionalProperty,
    AllDisjoint,
    sync_reasoner_pellet
)

import os

onto = get_ontology(
    "http://example.org/healthcare-hospital.owl#"
)

with onto:

    # ============================================================
    # TOP LEVEL CLASSES
    # ============================================================

    class Person(Thing):
        pass

    class Hospital(Thing):
        pass

    class Department(Thing):
        pass

    class Ward(Thing):
        pass

    class Room(Thing):
        pass

    class Bed(Thing):
        pass

    class Appointment(Thing):
        pass

    class Admission(Thing):
        pass

    class Discharge(Thing):
        pass

    class MedicalRecord(Thing):
        pass

    class Diagnosis(Thing):
        pass

    class Treatment(Thing):
        pass

    class Procedure(Thing):
        pass

    class Surgery(Thing):
        pass

    class Prescription(Thing):
        pass

    class Medication(Thing):
        pass

    class LaboratoryTest(Thing):
        pass

    class LabResult(Thing):
        pass

    class Allergy(Thing):
        pass

    class Vaccination(Thing):
        pass

    class InsurancePolicy(Thing):
        pass

    class InsuranceClaim(Thing):
        pass

    class Billing(Thing):
        pass

    class Invoice(Thing):
        pass

    class EmergencyCase(Thing):
        pass

    class MedicalDevice(Thing):
        pass

    class ClinicalNote(Thing):
        pass

    class Observation(Thing):
        pass

    class VitalSign(Thing):
        pass

    class CarePlan(Thing):
        pass

    class BloodBank(Thing):
        pass

    class Ambulance(Thing):
        pass

    # ============================================================
    # PERSON HIERARCHY
    # ============================================================

    class Patient(Person):
        pass

    class Doctor(Person):
        pass

    class Nurse(Person):
        pass

    class Technician(Person):
        pass

    class Pharmacist(Person):
        pass

    class Surgeon(Doctor):
        pass

    class Physician(Doctor):
        pass

    class Cardiologist(Doctor):
        pass

    class Neurologist(Doctor):
        pass

    class Radiologist(Doctor):
        pass

    class Pediatrician(Doctor):
        pass

    class Receptionist(Person):
        pass

    class Administrator(Person):
        pass

    class InsuranceAgent(Person):
        pass

    # ============================================================
    # DEPARTMENT HIERARCHY
    # ============================================================

    class EmergencyDepartment(Department):
        pass

    class CardiologyDepartment(Department):
        pass

    class NeurologyDepartment(Department):
        pass

    class OrthopedicDepartment(Department):
        pass

    class PediatricsDepartment(Department):
        pass

    class OncologyDepartment(Department):
        pass

    class RadiologyDepartment(Department):
        pass

    class PharmacyDepartment(Department):
        pass

    class LaboratoryDepartment(Department):
        pass

    class ICUDepartment(Department):
        pass

    # ============================================================
    # MEDICAL RECORD HIERARCHY
    # ============================================================

    class InpatientRecord(MedicalRecord):
        pass

    class OutpatientRecord(MedicalRecord):
        pass

    class EmergencyRecord(MedicalRecord):
        pass

    # ============================================================
    # TREATMENT HIERARCHY
    # ============================================================

    class MedicationTreatment(Treatment):
        pass

    class PhysicalTherapy(Treatment):
        pass

    class RadiationTherapy(Treatment):
        pass

    class Chemotherapy(Treatment):
        pass

    class SurgicalTreatment(Treatment):
        pass

    # ============================================================
    # LAB TEST HIERARCHY
    # ============================================================

    class BloodTest(LaboratoryTest):
        pass

    class UrineTest(LaboratoryTest):
        pass

    class CTScan(LaboratoryTest):
        pass

    class MRI(LaboratoryTest):
        pass

    class XRay(LaboratoryTest):
        pass

    class Ultrasound(LaboratoryTest):
        pass

    # ============================================================
    # MEDICATION HIERARCHY
    # ============================================================

    class Antibiotic(Medication):
        pass

    class Analgesic(Medication):
        pass

    class Antiviral(Medication):
        pass

    class Vaccine(Medication):
        pass

    class ControlledDrug(Medication):
        pass

    # ============================================================
    # OBJECT PROPERTIES
    # ============================================================

    # ------------------------------------------------------------
    # HOSPITAL STRUCTURE
    # ------------------------------------------------------------

    class hasDepartment(ObjectProperty):
        domain = [Hospital]
        range = [Department]

    class belongsToHospital(ObjectProperty):
        domain = [Department]
        range = [Hospital]

    class containsWard(ObjectProperty):
        domain = [Department]
        range = [Ward]

    class containsRoom(ObjectProperty):
        domain = [Ward]
        range = [Room]

    class containsBed(ObjectProperty):
        domain = [Room]
        range = [Bed]

    # ------------------------------------------------------------
    # STAFF RELATIONSHIPS
    # ------------------------------------------------------------

    class worksInDepartment(ObjectProperty):
        domain = [Person]
        range = [Department]

    class reportsTo(ObjectProperty):
        domain = [Person]
        range = [Person]

    class managesDepartment(ObjectProperty):
        domain = [Administrator]
        range = [Department]

    # ------------------------------------------------------------
    # PATIENT RELATIONSHIPS
    # ------------------------------------------------------------

    class hasMedicalRecord(ObjectProperty):
        domain = [Patient]
        range = [MedicalRecord]

    class admittedTo(ObjectProperty):
        domain = [Patient]
        range = [Admission]

    class dischargedFrom(ObjectProperty):
        domain = [Patient]
        range = [Discharge]

    class assignedBed(ObjectProperty):
        domain = [Patient]
        range = [Bed]

    class coveredByInsurance(ObjectProperty):
        domain = [Patient]
        range = [InsurancePolicy]

    # ------------------------------------------------------------
    # APPOINTMENTS
    # ------------------------------------------------------------

    class hasAppointment(ObjectProperty):
        domain = [Patient]
        range = [Appointment]

    class appointmentForPatient(ObjectProperty):
        domain = [Appointment]
        range = [Patient]

    class appointmentWithDoctor(ObjectProperty):
        domain = [Appointment]
        range = [Doctor]

    class appointmentAtHospital(ObjectProperty):
        domain = [Appointment]
        range = [Hospital]

    # ------------------------------------------------------------
    # DIAGNOSIS
    # ------------------------------------------------------------

    class hasDiagnosis(ObjectProperty):
        domain = [Patient]
        range = [Diagnosis]

    class diagnosedBy(ObjectProperty):
        domain = [Diagnosis]
        range = [Doctor]

    class diagnosisForPatient(ObjectProperty):
        domain = [Diagnosis]
        range = [Patient]

    class requiresTreatment(ObjectProperty):
        domain = [Diagnosis]
        range = [Treatment]

    # ------------------------------------------------------------
    # TREATMENT
    # ------------------------------------------------------------

    class receivesTreatment(ObjectProperty):
        domain = [Patient]
        range = [Treatment]

    class performedByDoctor(ObjectProperty):
        domain = [Treatment]
        range = [Doctor]

    class includesProcedure(ObjectProperty):
        domain = [Treatment]
        range = [Procedure]

    class involvesSurgery(ObjectProperty):
        domain = [Treatment]
        range = [Surgery]

    # ------------------------------------------------------------
    # PRESCRIPTION
    # ------------------------------------------------------------

    class hasPrescription(ObjectProperty):
        domain = [Patient]
        range = [Prescription]

    class prescribedBy(ObjectProperty):
        domain = [Prescription]
        range = [Doctor]

    class prescribedFor(ObjectProperty):
        domain = [Prescription]
        range = [Patient]

    class containsMedication(ObjectProperty):
        domain = [Prescription]
        range = [Medication]

    # ------------------------------------------------------------
    # LABORATORY
    # ------------------------------------------------------------

    class orderedLabTest(ObjectProperty):
        domain = [Doctor]
        range = [LaboratoryTest]

    class underwentLabTest(ObjectProperty):
        domain = [Patient]
        range = [LaboratoryTest]

    class producesResult(ObjectProperty):
        domain = [LaboratoryTest]
        range = [LabResult]

    class reviewedByDoctor(ObjectProperty):
        domain = [LabResult]
        range = [Doctor]

    # ------------------------------------------------------------
    # ALLERGIES
    # ------------------------------------------------------------

    class hasAllergy(ObjectProperty):
        domain = [Patient]
        range = [Allergy]

    class allergyToMedication(ObjectProperty):
        domain = [Allergy]
        range = [Medication]

    # ------------------------------------------------------------
    # VACCINATIONS
    # ------------------------------------------------------------

    class hasVaccination(ObjectProperty):
        domain = [Patient]
        range = [Vaccination]

    class administeredBy(ObjectProperty):
        domain = [Vaccination]
        range = [Nurse]

    # ------------------------------------------------------------
    # BILLING
    # ------------------------------------------------------------

    class hasBilling(ObjectProperty):
        domain = [Patient]
        range = [Billing]

    class generatesInvoice(ObjectProperty):
        domain = [Billing]
        range = [Invoice]

    class submitsClaim(ObjectProperty):
        domain = [Billing]
        range = [InsuranceClaim]

    class claimAgainstPolicy(ObjectProperty):
        domain = [InsuranceClaim]
        range = [InsurancePolicy]

    # ------------------------------------------------------------
    # EMERGENCY
    # ------------------------------------------------------------

    class emergencyCaseFor(ObjectProperty):
        domain = [EmergencyCase]
        range = [Patient]

    class handledByDoctor(ObjectProperty):
        domain = [EmergencyCase]
        range = [Doctor]

    class transportedBy(ObjectProperty):
        domain = [EmergencyCase]
        range = [Ambulance]

    # ------------------------------------------------------------
    # OBSERVATIONS
    # ------------------------------------------------------------

    class hasObservation(ObjectProperty):
        domain = [Patient]
        range = [Observation]

    class recordsVitalSign(ObjectProperty):
        domain = [Observation]
        range = [VitalSign]

    class enteredByNurse(ObjectProperty):
        domain = [Observation]
        range = [Nurse]

    # ------------------------------------------------------------
    # CARE PLAN
    # ------------------------------------------------------------

    class followsCarePlan(ObjectProperty):
        domain = [Patient]
        range = [CarePlan]

    class createdByDoctor(ObjectProperty):
        domain = [CarePlan]
        range = [Doctor]

    # ------------------------------------------------------------
    # MEDICAL DEVICES
    # ------------------------------------------------------------

    class usesMedicalDevice(ObjectProperty):
        domain = [Treatment]
        range = [MedicalDevice]

    # ------------------------------------------------------------
    # CLINICAL NOTES
    # ------------------------------------------------------------

    class hasClinicalNote(ObjectProperty):
        domain = [MedicalRecord]
        range = [ClinicalNote]

    class authoredBy(ObjectProperty):
        domain = [ClinicalNote]
        range = [Doctor]

        # ============================================================
    # DATA PROPERTIES
    # ============================================================

    # ------------------------------------------------------------
    # PERSON DATA
    # ------------------------------------------------------------

    class personId(DataProperty, FunctionalProperty):
        domain = [Person]
        range = [str]

    class firstName(DataProperty):
        domain = [Person]
        range = [str]

    class lastName(DataProperty):
        domain = [Person]
        range = [str]

    class gender(DataProperty):
        domain = [Person]
        range = [str]

    class dateOfBirth(DataProperty):
        domain = [Person]
        range = [str]

    class phoneNumber(DataProperty):
        domain = [Person]
        range = [str]

    class emailAddress(DataProperty):
        domain = [Person]
        range = [str]

    class address(DataProperty):
        domain = [Person]
        range = [str]

    # ------------------------------------------------------------
    # PATIENT DATA
    # ------------------------------------------------------------

    class patientNumber(DataProperty, FunctionalProperty):
        domain = [Patient]
        range = [str]

    class bloodGroup(DataProperty):
        domain = [Patient]
        range = [str]

    class maritalStatus(DataProperty):
        domain = [Patient]
        range = [str]

    class emergencyContact(DataProperty):
        domain = [Patient]
        range = [str]

    class patientStatus(DataProperty):
        domain = [Patient]
        range = [str]

    # ------------------------------------------------------------
    # DOCTOR DATA
    # ------------------------------------------------------------

    class doctorLicenseNumber(DataProperty):
        domain = [Doctor]
        range = [str]

    class specialization(DataProperty):
        domain = [Doctor]
        range = [str]

    class yearsOfExperience(DataProperty):
        domain = [Doctor]
        range = [int]

    class consultationFee(DataProperty):
        domain = [Doctor]
        range = [float]

    # ------------------------------------------------------------
    # NURSE DATA
    # ------------------------------------------------------------

    class nurseLicenseNumber(DataProperty):
        domain = [Nurse]
        range = [str]

    class shiftType(DataProperty):
        domain = [Nurse]
        range = [str]

    # ------------------------------------------------------------
    # HOSPITAL DATA
    # ------------------------------------------------------------

    class hospitalId(DataProperty):
        domain = [Hospital]
        range = [str]

    class hospitalName(DataProperty):
        domain = [Hospital]
        range = [str]

    class hospitalLocation(DataProperty):
        domain = [Hospital]
        range = [str]

    class hospitalType(DataProperty):
        domain = [Hospital]
        range = [str]

    class totalBeds(DataProperty):
        domain = [Hospital]
        range = [int]

    # ------------------------------------------------------------
    # DEPARTMENT DATA
    # ------------------------------------------------------------

    class departmentCode(DataProperty):
        domain = [Department]
        range = [str]

    class departmentName(DataProperty):
        domain = [Department]
        range = [str]

    # ------------------------------------------------------------
    # ROOM DATA
    # ------------------------------------------------------------

    class roomNumber(DataProperty):
        domain = [Room]
        range = [str]

    class roomType(DataProperty):
        domain = [Room]
        range = [str]

    class floorNumber(DataProperty):
        domain = [Room]
        range = [int]

    # ------------------------------------------------------------
    # BED DATA
    # ------------------------------------------------------------

    class bedNumber(DataProperty):
        domain = [Bed]
        range = [str]

    class bedStatus(DataProperty):
        domain = [Bed]
        range = [str]

    # ------------------------------------------------------------
    # APPOINTMENT DATA
    # ------------------------------------------------------------

    class appointmentId(DataProperty):
        domain = [Appointment]
        range = [str]

    class appointmentDate(DataProperty):
        domain = [Appointment]
        range = [str]

    class appointmentTime(DataProperty):
        domain = [Appointment]
        range = [str]

    class appointmentStatus(DataProperty):
        domain = [Appointment]
        range = [str]

    class appointmentReason(DataProperty):
        domain = [Appointment]
        range = [str]

    # ------------------------------------------------------------
    # ADMISSION DATA
    # ------------------------------------------------------------

    class admissionId(DataProperty):
        domain = [Admission]
        range = [str]

    class admissionDate(DataProperty):
        domain = [Admission]
        range = [str]

    class admissionReason(DataProperty):
        domain = [Admission]
        range = [str]

    # ------------------------------------------------------------
    # DISCHARGE DATA
    # ------------------------------------------------------------

    class dischargeDate(DataProperty):
        domain = [Discharge]
        range = [str]

    class dischargeSummary(DataProperty):
        domain = [Discharge]
        range = [str]

    # ------------------------------------------------------------
    # MEDICAL RECORD DATA
    # ------------------------------------------------------------

    class recordNumber(DataProperty):
        domain = [MedicalRecord]
        range = [str]

    class recordCreatedDate(DataProperty):
        domain = [MedicalRecord]
        range = [str]

    # ------------------------------------------------------------
    # DIAGNOSIS DATA
    # ------------------------------------------------------------

    class diagnosisCode(DataProperty):
        domain = [Diagnosis]
        range = [str]

    class diagnosisName(DataProperty):
        domain = [Diagnosis]
        range = [str]

    class diagnosisDescription(DataProperty):
        domain = [Diagnosis]
        range = [str]

    class diagnosisDate(DataProperty):
        domain = [Diagnosis]
        range = [str]

    # ------------------------------------------------------------
    # TREATMENT DATA
    # ------------------------------------------------------------

    class treatmentId(DataProperty):
        domain = [Treatment]
        range = [str]

    class treatmentName(DataProperty):
        domain = [Treatment]
        range = [str]

    class treatmentStatus(DataProperty):
        domain = [Treatment]
        range = [str]

    class treatmentCost(DataProperty):
        domain = [Treatment]
        range = [float]

    # ------------------------------------------------------------
    # PROCEDURE DATA
    # ------------------------------------------------------------

    class procedureCode(DataProperty):
        domain = [Procedure]
        range = [str]

    class procedureName(DataProperty):
        domain = [Procedure]
        range = [str]

    # ------------------------------------------------------------
    # SURGERY DATA
    # ------------------------------------------------------------

    class surgeryCode(DataProperty):
        domain = [Surgery]
        range = [str]

    class surgeryDate(DataProperty):
        domain = [Surgery]
        range = [str]

    class surgeryDurationMinutes(DataProperty):
        domain = [Surgery]
        range = [int]

    # ------------------------------------------------------------
    # PRESCRIPTION DATA
    # ------------------------------------------------------------

    class prescriptionNumber(DataProperty):
        domain = [Prescription]
        range = [str]

    class prescriptionDate(DataProperty):
        domain = [Prescription]
        range = [str]

    # ------------------------------------------------------------
    # MEDICATION DATA
    # ------------------------------------------------------------

    class medicationCode(DataProperty):
        domain = [Medication]
        range = [str]

    class medicationName(DataProperty):
        domain = [Medication]
        range = [str]

    class dosage(DataProperty):
        domain = [Medication]
        range = [str]

    class manufacturer(DataProperty):
        domain = [Medication]
        range = [str]

    # ------------------------------------------------------------
    # LAB TEST DATA
    # ------------------------------------------------------------

    class testCode(DataProperty):
        domain = [LaboratoryTest]
        range = [str]

    class testName(DataProperty):
        domain = [LaboratoryTest]
        range = [str]

    class testDate(DataProperty):
        domain = [LaboratoryTest]
        range = [str]

    # ------------------------------------------------------------
    # LAB RESULT DATA
    # ------------------------------------------------------------

    class resultValue(DataProperty):
        domain = [LabResult]
        range = [str]

    class resultStatus(DataProperty):
        domain = [LabResult]
        range = [str]

    class resultDate(DataProperty):
        domain = [LabResult]
        range = [str]

    # ------------------------------------------------------------
    # INSURANCE DATA
    # ------------------------------------------------------------

    class policyNumber(DataProperty):
        domain = [InsurancePolicy]
        range = [str]

    class insuranceProvider(DataProperty):
        domain = [InsurancePolicy]
        range = [str]

    class coverageAmount(DataProperty):
        domain = [InsurancePolicy]
        range = [float]

    # ------------------------------------------------------------
    # BILLING DATA
    # ------------------------------------------------------------

    class billingNumber(DataProperty):
        domain = [Billing]
        range = [str]

    class billingAmount(DataProperty):
        domain = [Billing]
        range = [float]

    class paymentStatus(DataProperty):
        domain = [Billing]
        range = [str]

    # ------------------------------------------------------------
    # INVOICE DATA
    # ------------------------------------------------------------

    class invoiceNumber(DataProperty):
        domain = [Invoice]
        range = [str]

    class invoiceDate(DataProperty):
        domain = [Invoice]
        range = [str]

    # ============================================================
    # OWL RESTRICTIONS
    # ============================================================

    Patient.is_a.append(
        hasMedicalRecord.min(1, MedicalRecord)
    )

    Patient.is_a.append(
        hasAppointment.min(1, Appointment)
    )

    Appointment.is_a.append(
        appointmentForPatient.exactly(1, Patient)
    )

    Appointment.is_a.append(
        appointmentWithDoctor.exactly(1, Doctor)
    )

    Diagnosis.is_a.append(
        diagnosedBy.exactly(1, Doctor)
    )

    Diagnosis.is_a.append(
        diagnosisForPatient.exactly(1, Patient)
    )

    Prescription.is_a.append(
        prescribedBy.exactly(1, Doctor)
    )

    Prescription.is_a.append(
        prescribedFor.exactly(1, Patient)
    )

    Prescription.is_a.append(
        containsMedication.min(1, Medication)
    )

    Treatment.is_a.append(
        performedByDoctor.min(1, Doctor)
    )

    LaboratoryTest.is_a.append(
        producesResult.min(1, LabResult)
    )

    Billing.is_a.append(
        generatesInvoice.exactly(1, Invoice)
    )

    CarePlan.is_a.append(
        createdByDoctor.exactly(1, Doctor)
    )

    Vaccination.is_a.append(
        administeredBy.exactly(1, Nurse)
    )

    Hospital.is_a.append(
        hasDepartment.min(1, Department)
    )

    Department.is_a.append(
        containsWard.min(1, Ward)
    )

    Ward.is_a.append(
        containsRoom.min(1, Room)
    )

    Room.is_a.append(
        containsBed.min(1, Bed)
    )

    EmergencyCase.is_a.append(
        handledByDoctor.min(1, Doctor)
    )

    EmergencyCase.is_a.append(
        emergencyCaseFor.exactly(1, Patient)
    )

    # ============================================================
    # DISJOINT CLASSES
    # ============================================================

    AllDisjoint([
        Patient,
        Doctor,
        Nurse,
        Technician,
        Pharmacist,
        Receptionist,
        Administrator
    ])

    AllDisjoint([
        Appointment,
        Admission,
        Discharge
    ])

    AllDisjoint([
        Diagnosis,
        Treatment,
        Procedure,
        Surgery
    ])

    AllDisjoint([
        Prescription,
        Medication
    ])

    AllDisjoint([
        LaboratoryTest,
        LabResult
    ])

    # ============================================================
    # ANNOTATIONS
    # ============================================================

    Hospital.label = ["Hospital"]
    Hospital.comment = [
        "Healthcare organization providing medical services."
    ]

    Patient.label = ["Patient"]
    Patient.comment = [
        "Individual receiving healthcare services."
    ]

    Doctor.label = ["Doctor"]
    Doctor.comment = [
        "Licensed medical practitioner."
    ]

    Nurse.label = ["Nurse"]
    Nurse.comment = [
        "Healthcare professional providing patient care."
    ]

    Appointment.label = ["Appointment"]
    Appointment.comment = [
        "Scheduled meeting between patient and doctor."
    ]

    MedicalRecord.label = ["Medical Record"]
    MedicalRecord.comment = [
        "Complete medical history of a patient."
    ]

    Diagnosis.label = ["Diagnosis"]
    Diagnosis.comment = [
        "Identification of a disease or medical condition."
    ]

    Treatment.label = ["Treatment"]
    Treatment.comment = [
        "Medical intervention provided to a patient."
    ]

    Prescription.label = ["Prescription"]
    Prescription.comment = [
        "Medication instructions issued by a doctor."
    ]

    Medication.label = ["Medication"]
    Medication.comment = [
        "Drug or pharmaceutical product."
    ]

    LaboratoryTest.label = ["Laboratory Test"]
    LaboratoryTest.comment = [
        "Medical test performed to support diagnosis."
    ]

    InsurancePolicy.label = ["Insurance Policy"]
    InsurancePolicy.comment = [
        "Health insurance coverage agreement."
    ]

        # ============================================================
    # INDIVIDUALS
    # ============================================================

    # ------------------------------------------------------------
    # HOSPITAL
    # ------------------------------------------------------------

    city_hospital = Hospital("CityHospital")

    # ------------------------------------------------------------
    # DEPARTMENTS
    # ------------------------------------------------------------

    cardiology = CardiologyDepartment("CardiologyDept")
    neurology = NeurologyDepartment("NeurologyDept")
    emergency = EmergencyDepartment("EmergencyDept")
    radiology = RadiologyDepartment("RadiologyDept")
    pharmacy = PharmacyDepartment("PharmacyDept")
    laboratory = LaboratoryDepartment("LaboratoryDept")
    icu = ICUDepartment("ICUDept")

    # ------------------------------------------------------------
    # WARDS
    # ------------------------------------------------------------

    ward_a = Ward("WardA")
    ward_b = Ward("WardB")
    ward_icu = Ward("WardICU")

    # ------------------------------------------------------------
    # ROOMS
    # ------------------------------------------------------------

    room_101 = Room("Room101")
    room_102 = Room("Room102")
    room_201 = Room("Room201")
    room_icu1 = Room("RoomICU1")

    # ------------------------------------------------------------
    # BEDS
    # ------------------------------------------------------------

    bed_1 = Bed("Bed1")
    bed_2 = Bed("Bed2")
    bed_3 = Bed("Bed3")
    bed_4 = Bed("Bed4")

    # ------------------------------------------------------------
    # DOCTORS
    # ------------------------------------------------------------

    dr_smith = Cardiologist("DrSmith")
    dr_john = Neurologist("DrJohn")
    dr_williams = Surgeon("DrWilliams")
    dr_kumar = Physician("DrKumar")

    # ------------------------------------------------------------
    # NURSES
    # ------------------------------------------------------------

    nurse_mary = Nurse("NurseMary")
    nurse_rita = Nurse("NurseRita")

    # ------------------------------------------------------------
    # PATIENTS
    # ------------------------------------------------------------

    patient_john = Patient("PatientJohn")
    patient_emma = Patient("PatientEmma")
    patient_david = Patient("PatientDavid")

    # ------------------------------------------------------------
    # MEDICAL RECORDS
    # ------------------------------------------------------------

    mr_john = InpatientRecord("MRJohn")
    mr_emma = OutpatientRecord("MREmma")
    mr_david = EmergencyRecord("MRDavid")

    # ------------------------------------------------------------
    # APPOINTMENTS
    # ------------------------------------------------------------

    appt_001 = Appointment("Appointment001")
    appt_002 = Appointment("Appointment002")

    # ------------------------------------------------------------
    # DIAGNOSES
    # ------------------------------------------------------------

    diag_flu = Diagnosis("DiagnosisFlu")
    diag_hypertension = Diagnosis("DiagnosisHypertension")
    diag_migraine = Diagnosis("DiagnosisMigraine")

    # ------------------------------------------------------------
    # TREATMENTS
    # ------------------------------------------------------------

    treatment_flu = MedicationTreatment("TreatmentFlu")
    treatment_bp = MedicationTreatment("TreatmentBP")
    treatment_neuro = PhysicalTherapy("TreatmentNeuro")

    # ------------------------------------------------------------
    # MEDICATIONS
    # ------------------------------------------------------------

    paracetamol = Analgesic("Paracetamol")
    amoxicillin = Antibiotic("Amoxicillin")
    aspirin = Analgesic("Aspirin")

    # ------------------------------------------------------------
    # PRESCRIPTIONS
    # ------------------------------------------------------------

    rx_001 = Prescription("Prescription001")
    rx_002 = Prescription("Prescription002")

    # ------------------------------------------------------------
    # LAB TESTS
    # ------------------------------------------------------------

    blood_test_1 = BloodTest("BloodTest001")
    mri_1 = MRI("MRI001")

    # ------------------------------------------------------------
    # LAB RESULTS
    # ------------------------------------------------------------

    blood_result_1 = LabResult("BloodResult001")
    mri_result_1 = LabResult("MRIResult001")

    # ------------------------------------------------------------
    # INSURANCE
    # ------------------------------------------------------------

    policy_a = InsurancePolicy("PolicyA")
    claim_a = InsuranceClaim("ClaimA")

    # ------------------------------------------------------------
    # BILLING
    # ------------------------------------------------------------

    billing_1 = Billing("Billing001")
    invoice_1 = Invoice("Invoice001")

    # ------------------------------------------------------------
    # CARE PLAN
    # ------------------------------------------------------------

    careplan_1 = CarePlan("CarePlan001")

    # ------------------------------------------------------------
    # OBSERVATION
    # ------------------------------------------------------------

    observation_1 = Observation("Observation001")
    vitals_1 = VitalSign("VitalSigns001")

    # ------------------------------------------------------------
    # EMERGENCY
    # ------------------------------------------------------------

    emergency_case_1 = EmergencyCase("Emergency001")
    ambulance_1 = Ambulance("Ambulance001")

    # ============================================================
    # DATA PROPERTY VALUES
    # ============================================================

    city_hospital.hospitalId = ["HOSP001"]
    city_hospital.hospitalName = ["City General Hospital"]
    city_hospital.hospitalLocation = ["New York"]
    city_hospital.totalBeds = [500]

    dr_smith.firstName = ["Robert"]
    dr_smith.lastName = ["Smith"]
    dr_smith.specialization = ["Cardiology"]
    dr_smith.doctorLicenseNumber = ["DOC1001"]
    dr_smith.yearsOfExperience = [15]

    dr_john.specialization = ["Neurology"]
    dr_williams.specialization = ["Surgery"]

    patient_john.firstName = ["John"]
    patient_john.lastName = ["Doe"]
    patient_john.bloodGroup = ["O+"]

    patient_emma.firstName = ["Emma"]
    patient_emma.lastName = ["Wilson"]
    patient_emma.bloodGroup = ["A+"]

    patient_david.firstName = ["David"]
    patient_david.lastName = ["Brown"]
    patient_david.bloodGroup = ["B+"]

    appt_001.appointmentId = ["APT001"]
    appt_001.appointmentStatus = ["Completed"]

    appt_002.appointmentId = ["APT002"]
    appt_002.appointmentStatus = ["Scheduled"]

    diag_flu.diagnosisCode = ["J10"]
    diag_flu.diagnosisName = ["Influenza"]

    diag_hypertension.diagnosisCode = ["I10"]
    diag_hypertension.diagnosisName = ["Hypertension"]

    diag_migraine.diagnosisCode = ["G43"]
    diag_migraine.diagnosisName = ["Migraine"]

    # ============================================================
    # RELATIONSHIPS
    # ============================================================

    # Hospital Structure

    city_hospital.hasDepartment.extend([
        cardiology,
        neurology,
        emergency,
        radiology,
        pharmacy,
        laboratory,
        icu
    ])

    cardiology.containsWard.append(ward_a)
    neurology.containsWard.append(ward_b)
    icu.containsWard.append(ward_icu)

    ward_a.containsRoom.extend([
        room_101,
        room_102
    ])

    ward_b.containsRoom.append(room_201)

    ward_icu.containsRoom.append(room_icu1)

    room_101.containsBed.append(bed_1)
    room_101.containsBed.append(bed_2)
    room_201.containsBed.append(bed_3)
    room_icu1.containsBed.append(bed_4)

    # Staff

    dr_smith.worksInDepartment.append(cardiology)
    dr_john.worksInDepartment.append(neurology)
    dr_williams.worksInDepartment.append(emergency)

    nurse_mary.worksInDepartment.append(cardiology)
    nurse_rita.worksInDepartment.append(icu)

    # Patient Records

    patient_john.hasMedicalRecord.append(mr_john)
    patient_emma.hasMedicalRecord.append(mr_emma)
    patient_david.hasMedicalRecord.append(mr_david)

    # Appointments

    patient_john.hasAppointment.append(appt_001)

    appt_001.appointmentForPatient.append(patient_john)
    appt_001.appointmentWithDoctor.append(dr_smith)
    appt_001.appointmentAtHospital.append(city_hospital)

    appt_002.appointmentForPatient.append(patient_emma)
    appt_002.appointmentWithDoctor.append(dr_john)

    # Diagnoses

    patient_john.hasDiagnosis.append(diag_hypertension)
    patient_emma.hasDiagnosis.append(diag_flu)
    patient_david.hasDiagnosis.append(diag_migraine)

    diag_hypertension.diagnosedBy.append(dr_smith)
    diag_hypertension.diagnosisForPatient.append(patient_john)

    diag_flu.diagnosedBy.append(dr_kumar)
    diag_flu.diagnosisForPatient.append(patient_emma)

    diag_migraine.diagnosedBy.append(dr_john)
    diag_migraine.diagnosisForPatient.append(patient_david)

    # Treatments

    diag_hypertension.requiresTreatment.append(treatment_bp)
    diag_flu.requiresTreatment.append(treatment_flu)
    diag_migraine.requiresTreatment.append(treatment_neuro)

    treatment_bp.performedByDoctor.append(dr_smith)
    treatment_flu.performedByDoctor.append(dr_kumar)
    treatment_neuro.performedByDoctor.append(dr_john)

    patient_john.receivesTreatment.append(treatment_bp)
    patient_emma.receivesTreatment.append(treatment_flu)
    patient_david.receivesTreatment.append(treatment_neuro)

    # Prescriptions

    rx_001.prescribedBy.append(dr_smith)
    rx_001.prescribedFor.append(patient_john)

    rx_002.prescribedBy.append(dr_kumar)
    rx_002.prescribedFor.append(patient_emma)

    rx_001.containsMedication.extend([
        aspirin
    ])

    rx_002.containsMedication.extend([
        paracetamol,
        amoxicillin
    ])

    # Lab Tests

    dr_smith.orderedLabTest.append(blood_test_1)

    patient_john.underwentLabTest.append(
        blood_test_1
    )

    blood_test_1.producesResult.append(
        blood_result_1
    )

    blood_result_1.reviewedByDoctor.append(
        dr_smith
    )

    # Insurance

    patient_john.coveredByInsurance.append(
        policy_a
    )

    billing_1.submitsClaim.append(claim_a)

    claim_a.claimAgainstPolicy.append(
        policy_a
    )

    # Billing

    patient_john.hasBilling.append(
        billing_1
    )

    billing_1.generatesInvoice.append(
        invoice_1
    )

    # Care Plan

    patient_john.followsCarePlan.append(
        careplan_1
    )

    careplan_1.createdByDoctor.append(
        dr_smith
    )

    # Observation

    patient_john.hasObservation.append(
        observation_1
    )

    observation_1.recordsVitalSign.append(
        vitals_1
    )

    observation_1.enteredByNurse.append(
        nurse_mary
    )

    # Emergency

    emergency_case_1.emergencyCaseFor.append(
        patient_david
    )

    emergency_case_1.handledByDoctor.append(
        dr_williams
    )

    emergency_case_1.transportedBy.append(
        ambulance_1
    )

if __name__ == "__main__":
    print("REACHED SAVE")
    # =========================================================================
    # 9. SAVE
    # =========================================================================

    # Always save next to this script file, regardless of working directory
    script_dir   = os.path.dirname(os.path.abspath(__file__))
    output_path  = os.path.join(script_dir, "healthcare_ontology.owl")

    onto.save(file=output_path, format="rdfxml")

    # Verify the file was actually written
    if os.path.exists(output_path):
        size_kb = os.path.getsize(output_path) / 1024
        print(f"  OWL file saved successfully!")
        print(f"    Path : {output_path}")
        print(f"    Size : {size_kb:.1f} KB")
        print()
        print("Next steps in Protege:")
        print("  1. File → Open  → select healthcare_ontology.owl")
        print("  2. Browse Classes, Object Properties, Data Properties, Individuals tabs")
    else:
        print("  Save failed — file not found after save(). Check folder permissions.")
        print("SAVE COMPLETE")
