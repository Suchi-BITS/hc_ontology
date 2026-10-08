import os

from rdflib import XSD, Graph, Literal

from core.dataset import as_dataset

class HealthcareOntology:

    def __init__(self, owl_file=None):
        """owl_file: a Dataset (schema + sample data), a path to one RDF file, or None for the configured dataset.
        (The name is historical; the object model is built from the merged graph, whatever files it came from.)"""
        self.dataset = as_dataset(owl_file)
        self.owl_file = self.dataset  # what the SPARQL workers and the exporter are given

        self.onto = self.dataset.load_owlready()

    @staticmethod
    def _scalar(value):
        """First value of a property as a string; handles functional (scalar) and list values."""
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        return "" if value is None else str(value)

    @staticmethod
    def _as_list(value):
        """Owlready2 returns a scalar for functional properties and a list otherwise."""
        if value is None:
            return []
        return list(value) if isinstance(value, (list, tuple)) else [value]

    @staticmethod
    def _preferred_code(entity):
        """codeValue of the ICD-10 coding if present, else the first coding, else empty."""
        codes = list(getattr(entity, "hasCode", []) or [])
        icd = [c for c in codes if (c.codeSystem or "").endswith("icd-10")]
        chosen = (icd or codes or [None])[0]
        return (chosen.codeValue if chosen is not None else "") or ""

    @staticmethod
    def _concept_label(concept):
        """Display label of a SKOS-style vocabulary individual."""
        return concept.label.first() or concept.name

    # ==========================================
    # SAVE
    # ==========================================

    def save(self):
        raise NotImplementedError(
            "The ontology is generated, not edited at runtime: regenerate ontology/healthcare_schema.ttl and "
            "data/sample_data.ttl with scripts/generate_hc_ontology.py and scripts/generate_sample_data.py."
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
                    self._scalar(p.firstName),
                "last_name":
                    self._scalar(p.lastName),
                "blood_group":
                    self._scalar(p.bloodGroup)
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
                    self._concept_label(d.hasSpecialty[0])
                    if d.hasSpecialty else ""
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
                    self._as_list(appt.appointmentForPatient)[0].name

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
                    self._preferred_code(diagnosis),

                "diagnosis_title":
                    self._scalar(diagnosis.diagnosisName)
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

                for patient in self._as_list(diagnosis.diagnosisForPatient):

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
    
    def execute_sparql(self, query: str):
        """Run a SELECT query with a HARD time limit (SPARQL_QUERY_TIMEOUT_SECONDS).

        Execution happens in a killable worker process (core/sparql_exec.py): rdflib cannot be interrupted
        in-process, so the limit is enforced by terminating the worker. Raises SparqlTimeout (a TimeoutError).
        """
        from core.config import get_settings
        from core.sparql_exec import get_runner

        settings = get_settings()
        runner = get_runner(self.dataset, settings["sparql_workers"])
        return runner.run(query, settings["sparql_query_timeout_seconds"])

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

                for p in self._as_list(d.diagnosisForPatient):

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
        model: str | None = None,
    ):
        # The LLM stack is imported only when natural language is actually used: the ontology service
        # (parse, describe, SPARQL) must work without openai or langchain installed.
        from core.config import get_settings
        from core.llm import get_chat_llm

        from langchain_core.messages import HumanMessage, SystemMessage

        llm = get_chat_llm(
            model=model or get_settings()["llm_model"],
            temperature=0,
        )
        response = llm.invoke(
            [
                SystemMessage(content=self.ontology_schema_prompt()),
                HumanMessage(content=question),
            ]
        )
        return getattr(response, "content", str(response))