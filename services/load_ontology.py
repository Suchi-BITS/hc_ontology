import ollama
from owlready2 import *
import os

#from asyncio import graph
from neo4j import GraphDatabase
from rdflib import Graph

class HealthcareOntology:

    def __init__(
        self,
        owl_file="healthcare_ontology.owl"
    ):

        self.owl_file = owl_file

        self.onto = get_ontology(
            os.path.abspath(owl_file)
        ).load()

    # ==========================================
    # SAVE
    # ==========================================

    def save(self):

        self.onto.save(
            file=self.owl_file
        )

    # ==========================================
    # METADATA
    # ==========================================

    def get_classes(self):

        return [
            cls.name
            for cls in self.onto.classes()
        ]

    def get_object_properties(self):

        return [
            p.name
            for p in self.onto.object_properties()
        ]

    def get_data_properties(self):

        return [
            p.name
            for p in self.onto.data_properties()
        ]

    def get_individuals(self):

        return [
            i.name
            for i in self.onto.individuals()
        ]

    # ==========================================
    # GENERIC CLASS LOOKUP
    # ==========================================

    def get_instances(
        self,
        class_name
    ):

        cls = getattr(
            self.onto,
            class_name,
            None
        )

        if not cls:
            return []

        return [
            x.name
            for x in cls.instances()
        ]

    # ==========================================
    # PATIENTS
    # ==========================================

    def get_patients(self):

        Patient = self.onto.Patient

        results = []

        for p in Patient.instances():

            results.append({
                "name": p.name,
                "first_name":
                    p.firstName[0]
                    if p.firstName else "",
                "last_name":
                    p.lastName[0]
                    if p.lastName else "",
                "blood_group":
                    p.bloodGroup[0]
                    if p.bloodGroup else ""
            })

        return results

    # ==========================================
    # DOCTORS
    # ==========================================

    def get_doctors(self):

        Doctor = self.onto.Doctor

        results = []

        for d in Doctor.instances():

            results.append({
                "name": d.name,
                "specialization":
                    d.specialization[0]
                    if d.specialization else ""
            })

        return results

    # ==========================================
    # APPOINTMENTS
    # ==========================================

    def get_appointments(self):

        Appointment = self.onto.Appointment

        results = []

        for appt in Appointment.instances():

            patient = ""

            doctor = ""

            if appt.appointmentForPatient:
                patient = \
                    appt.appointmentForPatient[0].name

            if appt.appointmentWithDoctor:
                doctor = \
                    appt.appointmentWithDoctor[0].name

            results.append({
                "appointment":
                    appt.name,
                "patient":
                    patient,
                "doctor":
                    doctor
            })

        return results

    # ==========================================
    # DIAGNOSES
    # ==========================================

    def get_diagnoses(self):

        Diagnosis = self.onto.Diagnosis

        output = []

        for d in Diagnosis.instances():

            output.append({
                "name": d.name
            })

        return output

    # ==========================================
    # TREATMENTS
    # ==========================================

    def get_treatments(self):

        Treatment = self.onto.Treatment

        return [
            {
                "name": t.name
            }
            for t in Treatment.instances()
        ]

    # ==========================================
    # SEARCH
    # ==========================================

    def search(self, text):

        results = []

        text = text.lower()

        for i in self.onto.individuals():

            if text in i.name.lower():

                results.append(
                    i.name
                )

        return results

    def get_patient_diagnoses(
    self,
    patient_name: str
):

      patient = getattr(
        self.onto,
        patient_name,
        None
    )

      if not patient:
        return None

      diagnoses = []

      if hasattr(patient,
        "hasDiagnosis"
    ):

        for diagnosis in patient.hasDiagnosis:

            diagnoses.append({

                "diagnosis_name":
                    diagnosis.name,

                "diagnosis_code":
                    diagnosis.diagnosisCode[0]
                    if hasattr(
                        diagnosis,
                        "diagnosisCode"
                    )
                    and diagnosis.diagnosisCode
                    else "",

                "diagnosis_title":
                    diagnosis.diagnosisName[0]
                    if hasattr(
                        diagnosis,
                        "diagnosisName"
                    )
                    and diagnosis.diagnosisName
                    else ""
            })

        return {

        "patient":
            patient.name,

        "diagnoses":
            diagnoses
    }
    
    #patient-treatment traversal
    def get_patient_treatments(
    self,
    patient_name: str
):

        patient = getattr(
        self.onto,
        patient_name,
        None
    )

        if not patient:
            return None

        treatments = []

        for diagnosis in patient.hasDiagnosis:

            if hasattr(
            diagnosis,
            "requiresTreatment"
        ):

                for treatment in diagnosis.requiresTreatment:

                    treatments.append({

                    "diagnosis":
                        diagnosis.name,

                    "treatment":
                        treatment.name
                })

        return {

        "patient":
            patient.name,

        "treatments":
            treatments
    }

    # Doctor → Patient Traversal
    def get_doctor_patients(
    self,
    doctor_name: str
):

        doctor = getattr(
        self.onto,
        doctor_name,
        None
    )

        if not doctor:
            return None

        patients = []

        Diagnosis = self.onto.Diagnosis

        for diagnosis in Diagnosis.instances():

            if doctor in diagnosis.diagnosedBy:

                for patient in diagnosis.diagnosisForPatient:

                    patients.append({

                    "patient":
                        patient.name,

                    "diagnosis":
                        diagnosis.name
                })

        return {

        "doctor":
            doctor.name,

        "patients":
            patients
    }

    def get_rdf_triples(self):

        triples = []

        for subject in self.onto.individuals():

            for prop in subject.get_properties():

                try:

                    values = prop[subject]

                    for value in values:

                        triples.append({

                        "subject":
                            subject.name,

                        "predicate":
                            prop.name,

                        "object":
                            getattr(
                                value,
                                "name",
                                str(value)
                            )
                    })

                except:
                    pass

        return triples
    
    def execute_sparql(
    self,
    query: str):

        graph = Graph()

        graph.parse(
        self.owl_file,
        format="xml"
    )

        rows = graph.query(query)

        output = []

        for row in rows:

            output.append([
            str(x)
            for x in row
        ])

        return output
    
    def natural_language_query(
    self,
    question: str
):

     q = question.lower()

     if "patients" in q and \
       "hypertension" in q:

        results = []

        Diagnosis = self.onto.Diagnosis

        for d in Diagnosis.instances():

            if "hypertension" in d.name.lower():

                for p in d.diagnosisForPatient:

                    results.append(
                        p.name
                    )

        return results

     if "doctors" in q:

        return self.get_doctors()

     if "patients" in q:

        return self.get_patients()

     return {

        "message":
            "No rule matched."
    }

    def export_neo4j_cypher(
    self
):

        statements = []

    # Nodes

        for individual in self.onto.individuals():

            cls = individual.is_a[0].name

            statements.append(

            f"""
            MERGE (n:{cls}
            {{name:'{individual.name}'}})
            """
        )

    # Relationships

        for subject in self.onto.individuals():

            for prop in subject.get_properties():

                try:

                    for obj in prop[subject]:

                        if hasattr(
                        obj,
                        "name"
                    ):

                            statements.append(

                            f"""
                            MATCH (a {{name:'{subject.name}'}})
                            MATCH (b {{name:'{obj.name}'}})
                            MERGE (a)-[:{prop.name.upper()}]->(b)
                            """
                        )

                except:
                    pass

        return statements
    
# from openai import OpenAI
# import os

# client = OpenAI(
#     api_key=os.getenv(
#         "OPENAI_API_KEY"
#     )
# )

    def ontology_schema_prompt(self):

        return """
Healthcare Ontology

Classes:
- Patient
- Doctor
- Diagnosis
- Treatment
- Appointment
- Prescription
- Medication

Object Properties:
- hasDiagnosis
- diagnosisForPatient
- diagnosedBy
- requiresTreatment
- receivesTreatment
- prescribedBy
- prescribedFor
- containsMedication

Generate ONLY SPARQL.

Do not explain.
Return query only.
"""
    def generate_sparql(
        self,
        question: str,
        model: str = "llama3:latest"
    ):

        response = ollama.chat(

            model=model,

            messages=[

                {
                    "role": "system",

                    "content":

                        self.ontology_schema_prompt()
                },

                {
                    "role": "user",

                    "content":

                        question
                }
            ]
        )

        return response["message"]["content"]