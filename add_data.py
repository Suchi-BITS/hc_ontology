from load_ontology import HealthcareOntology

hc = HealthcareOntology()
onto = hc.onto

def create_hospital_structure():

    city_hospital = onto.Hospital("CityHospital")

    city_hospital.hospitalName = ["City General Hospital"]

    cardiology = onto.CardiologyDepartment("CardiologyDept")
    neurology = onto.NeurologyDepartment("NeurologyDept")
    emergency = onto.EmergencyDepartment("EmergencyDept")
    laboratory = onto.LaboratoryDepartment("LaboratoryDept")
    pharmacy = onto.PharmacyDepartment("PharmacyDept")
    icu = onto.ICUDepartment("ICUDept")

    city_hospital.hasDepartment.extend([
        cardiology,
        neurology,
        emergency,
        laboratory,
        pharmacy,
        icu
    ])

    ward_a = onto.Ward("WardA")
    ward_b = onto.Ward("WardB")

    cardiology.containsWard.append(ward_a)
    neurology.containsWard.append(ward_b)

    room101 = onto.Room("Room101")
    room102 = onto.Room("Room102")

    ward_a.containsRoom.extend([
        room101,
        room102
    ])

    bed1 = onto.Bed("Bed1")
    bed2 = onto.Bed("Bed2")

    room101.containsBed.extend([
        bed1,
        bed2
    ])

    return city_hospital


def create_staff():

    dr_smith = onto.Cardiologist("DrSmith")
    dr_john = onto.Neurologist("DrJohn")
    dr_williams = onto.Surgeon("DrWilliams")

    dr_smith.firstName = ["Robert"]
    dr_john.firstName = ["John"]
    dr_williams.firstName = ["William"]

    nurse_mary = onto.Nurse("NurseMary")
    nurse_rita = onto.Nurse("NurseRita")

    return {
        "smith": dr_smith,
        "john": dr_john,
        "surgeon": dr_williams,
        "mary": nurse_mary,
        "rita": nurse_rita
    }


def create_patients():

    p1 = onto.Patient("PatientJohn")
    p2 = onto.Patient("PatientEmma")
    p3 = onto.Patient("PatientDavid")

    p1.firstName = ["John"]
    p2.firstName = ["Emma"]
    p3.firstName = ["David"]

    return [p1, p2, p3]


def create_medical_records(patients):

    for patient in patients:

        mr = onto.MedicalRecord(
            f"MR_{patient.name}"
        )

        patient.hasMedicalRecord.append(
            mr
        )


def create_diagnoses(
    patients,
    doctors
):

    flu = onto.Diagnosis("Flu")
    hypertension = onto.Diagnosis(
        "Hypertension"
    )

    patients[0].hasDiagnosis.append(
        hypertension
    )

    patients[1].hasDiagnosis.append(
        flu
    )

    hypertension.diagnosedBy.append(
        doctors["smith"]
    )

    flu.diagnosedBy.append(
        doctors["john"]
    )


def create_treatments(
    patients,
    doctors
):

    t1 = onto.MedicationTreatment(
        "BloodPressureTreatment"
    )

    t2 = onto.MedicationTreatment(
        "FluTreatment"
    )

    t1.performedByDoctor.append(
        doctors["smith"]
    )

    t2.performedByDoctor.append(
        doctors["john"]
    )

    patients[0].receivesTreatment.append(
        t1
    )

    patients[1].receivesTreatment.append(
        t2
    )


def create_medications():

    aspirin = onto.Analgesic(
        "Aspirin"
    )

    paracetamol = onto.Analgesic(
        "Paracetamol"
    )

    amoxicillin = onto.Antibiotic(
        "Amoxicillin"
    )

    return aspirin, paracetamol, amoxicillin


def create_prescriptions(
    patients,
    doctors,
    medications
):

    rx1 = onto.Prescription("RX001")

    rx1.prescribedBy.append(
        doctors["smith"]
    )

    rx1.prescribedFor.append(
        patients[0]
    )

    rx1.containsMedication.append(
        medications[0]
    )


def create_lab_tests(
    patients,
    doctors
):

    blood_test = onto.BloodTest(
        "BloodTest001"
    )

    result = onto.LabResult(
        "BloodResult001"
    )

    blood_test.producesResult.append(
        result
    )

    result.reviewedByDoctor.append(
        doctors["smith"]
    )

    patients[0].underwentLabTest.append(
        blood_test
    )


def create_insurance(
    patients
):

    policy = onto.InsurancePolicy(
        "PolicyA"
    )

    claim = onto.InsuranceClaim(
        "ClaimA"
    )

    patients[0].coveredByInsurance.append(
        policy
    )

    claim.claimAgainstPolicy.append(
        policy
    )


def create_billing(
    patients
):

    billing = onto.Billing(
        "Billing001"
    )

    invoice = onto.Invoice(
        "Invoice001"
    )

    billing.generatesInvoice.append(
        invoice
    )

    patients[0].hasBilling.append(
        billing
    )


def create_care_plan(
    patients,
    doctors
):

    cp = onto.CarePlan(
        "CarePlan001"
    )

    cp.createdByDoctor.append(
        doctors["smith"]
    )

    patients[0].followsCarePlan.append(
        cp
    )


def create_emergency_case(
    patients,
    doctors
):

    ec = onto.EmergencyCase(
        "Emergency001"
    )

    ambulance = onto.Ambulance(
        "Ambulance001"
    )

    ec.emergencyCaseFor.append(
        patients[2]
    )

    ec.handledByDoctor.append(
        doctors["surgeon"]
    )

    ec.transportedBy.append(
        ambulance
    )


if __name__ == "__main__":

    create_hospital_structure()

    doctors = create_staff()

    patients = create_patients()

    create_medical_records(
        patients
    )

    create_diagnoses(
        patients,
        doctors
    )

    create_treatments(
        patients,
        doctors
    )

    medications = create_medications()

    create_prescriptions(
        patients,
        doctors,
        medications
    )

    create_lab_tests(
        patients,
        doctors
    )

    create_insurance(
        patients
    )

    create_billing(
        patients
    )

    create_care_plan(
        patients,
        doctors
    )

    create_emergency_case(
        patients,
        doctors
    )

    hc.save()

    print(
        "Healthcare ontology populated successfully."
    )

