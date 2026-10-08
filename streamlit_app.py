"""

Healthcare Ontology Platform — Streamlit UI for course demos.



Run (API must be running):

    streamlit run streamlit_app.py

"""



import os

import re

import uuid

from pathlib import Path



import httpx

import streamlit as st

from dotenv import load_dotenv



_ROOT = Path(__file__).resolve().parent

load_dotenv(_ROOT / ".env")



API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

API_KEY = os.getenv("API_KEY", "")





def headers():

    h = {"Accept": "application/json"}

    if API_KEY:

        h["X-API-Key"] = API_KEY

    return h





def get(path: str, **params):

    r = httpx.get(f"{API_BASE}{path}", params=params, headers=headers(), timeout=120.0)

    r.raise_for_status()

    return r.json()





def post(path: str, json_body: dict):

    r = httpx.post(

        f"{API_BASE}{path}",

        json=json_body,

        headers=headers(),

        timeout=300.0,

    )

    r.raise_for_status()

    return r.json()





def _streamlit_session_id() -> str:

    if "nl_session_id" not in st.session_state:

        st.session_state.nl_session_id = f"streamlit-{uuid.uuid4().hex[:8]}"

    return st.session_state.nl_session_id





def _log_memory_preview(question: str) -> None:

    """Print MEMORY DEBUG blocks in the uvicorn terminal (no-op when debug is off)."""

    try:

        post(

            "/agent/memory/preview",

            {"question": question, "session_id": _streamlit_session_id()},

        )

    except Exception:

        pass





_PATIENT_STOPWORDS = frozenset({

    "a", "an", "the", "and", "or", "between", "with", "for", "all", "list",

    "who", "what", "which", "is", "are", "was", "were", "has", "have", "had",

    "diagnosed", "diagnosis", "diagnoses", "patient", "patients", "show", "me",

})





def _patient_name_from_question(question: str) -> str | None:

    """Map natural names to ontology individual ids (e.g. John Doe -> PatientJohn)."""

    q = (question or "").lower()

    if "john doe" in q or "patientjohn" in q.replace(" ", ""):

        return "PatientJohn"

    match = re.search(r"\b(Patient[A-Z][A-Za-z0-9]*)\b", question or "")

    if match:

        return match.group(1)

    match = re.search(r"patient\s+(\w+)", q, re.I)

    if match:

        token = match.group(1).lower()

        if token not in _PATIENT_STOPWORDS:

            return token if token.startswith("patient") else f"Patient{token.capitalize()}"

    return None





def _is_schema_relationship_question(question: str) -> bool:

    q = (question or "").lower()

    if "patient" not in q or "diagnos" not in q:

        return False

    return any(

        kw in q

        for kw in (

            "relationship",

            "relate",

            "relation",

            "link",

            "linked",

            "connect",

            "connection",

            "object property",

            "property between",

            "how are",

            "what is the relationship",

        )

    )





def try_direct_relationship_answer(question: str) -> dict | None:

    """Explain Patient–Diagnosis ontology/Cypher relationship with a live example."""

    if not _is_schema_relationship_question(question):

        return None

    props = get("/object-properties")

    rel = "hasDiagnosis" if "hasDiagnosis" in props else None

    example = get("/patients/PatientJohn/diagnoses")

    return {

        "question": question,

        "answer": (

            "A Patient is linked to a Diagnosis via the object property "

            "`hasDiagnosis` (inverse: `diagnosisForPatient`)."

        ),

        "ontology": {

            "object_property": rel or "hasDiagnosis",

            "inverse_property": "diagnosisForPatient",

            "direction": "Patient --hasDiagnosis--> Diagnosis",

        },

        "neo4j_pattern": {

            "relationship": "HASDIAGNOSIS",

            "cypher": (

                "MATCH (p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis) "

                "RETURN p.name, d.diagnosisName LIMIT 50"

            ),

        },

        "example": {

            "patient": "PatientJohn",

            "patient_display": "John Doe",

            "diagnoses": example.get("diagnoses") or [],

        },

    }





def try_direct_patient_diagnosis(question: str) -> dict | None:

    """Answer diagnosis questions for a specific patient via REST (no LLM)."""

    if _is_schema_relationship_question(question):

        return None

    if "diagnos" not in (question or "").lower():

        return None

    patient = _patient_name_from_question(question)

    if not patient:

        return None

    try:

        return get(f"/patients/{patient}/diagnoses")

    except httpx.HTTPStatusError as e:

        if e.response.status_code == 404:

            return {"patient": patient, "diagnoses": [], "note": "Patient not found in ontology"}

        raise





def try_direct_patients_by_condition(question: str) -> dict | None:

    """List patients matching a condition keyword (e.g. diabetes) without LLM."""

    q = (question or "").lower()

    if not any(k in q for k in ("patient", "patients", "show", "list", "all", "me")):

        return None

    condition_aliases = {

        "diabetes": ("diabetes", "diabetic"),

        "hypertension": ("hypertension", "hypertensive"),

        "migraine": ("migraine",),

    }

    condition = None

    for canonical, aliases in condition_aliases.items():

        if any(a in q for a in aliases):

            condition = canonical

            break

    if not condition:

        return None

    patients = get("/patients")

    matched: list[dict] = []

    for row in patients:

        name = row.get("name") or row.get("patient_name")

        if not name:

            continue

        try:

            diag_data = get(f"/patients/{name}/diagnoses")

        except httpx.HTTPStatusError:

            continue

        for d in diag_data.get("diagnoses") or []:

            title = (d.get("diagnosis_title") or d.get("diagnosis_name") or "").lower()

            if condition in title or condition in (d.get("diagnosis_name") or "").lower():

                matched.append({"patient": name, **d})

    return {

        "question": question,

        "condition": condition,

        "patients": matched,

        "count": len(matched),

    }





def try_direct_ontology_answer(question: str) -> dict | None:

    direct = try_direct_relationship_answer(question)

    if direct is not None:

        return direct

    direct = try_direct_patient_diagnosis(question)

    if direct is not None:

        return direct

    return try_direct_patients_by_condition(question)





st.set_page_config(

    page_title="Healthcare Ontology",

    page_icon="🏥",

    layout="wide",

)



st.title("Healthcare Ontology Platform")

st.caption(f"API: `{API_BASE}` · [OpenAPI docs]({API_BASE}/docs)")



tab1, tab2, tab3, tab4, tab5 = st.tabs(

    ["Overview", "Ask (NL→Cypher)", "SPARQL", "Semantic Search", "Admin"]

)



with tab1:

    col1, col2, col3 = st.columns(3)

    try:

        health = get("/health")

        stats = get("/stats")

        col1.metric("API", health.get("status", "?"))

        col2.metric("Classes", stats.get("classes", 0))

        col3.metric("Individuals", stats.get("individuals", 0))

        st.subheader("Graph summary")

        st.json(get("/graph-summary"))

        st.subheader("Sample patients")

        st.dataframe(get("/patients"), use_container_width=True)

    except Exception as e:

        st.error(f"Cannot reach API: {e}")

        st.info("Start the API: `uvicorn api:app --reload`")



with tab2:

    st.subheader("Natural language → Cypher → Neo4j")

    question = st.text_area(

        "Question",

        value="What is the patient diagnosis for John Doe?",

        height=80,

    )

    st.caption(

        "Tip: ontology patient id is `PatientJohn` (John Doe). "

        "Ask *relationship between patient and diagnosis* for schema help, "

        "or *What is John Doe's diagnosis?* for a specific patient. "

        f"session_id `{_streamlit_session_id()}` — reuse across turns; "

        "with `MEMORY_DEBUG_CONTEXT=true`, memory snapshots print in the **uvicorn terminal**."

    )

    if st.button("Generate & run Cypher", type="primary"):

        with st.spinner("Generating Cypher (OpenAI may take 30–90 sec)..."):

            try:

                direct = try_direct_ontology_answer(question)

                if direct is not None:

                    _log_memory_preview(question)

                    st.info("Answered from ontology API (no LLM required)")

                    st.json(direct)

                else:

                    gen = post(

                        "/nl-to-cypher",

                        {

                            "question": question,

                            "session_id": _streamlit_session_id(),

                        },

                    )

                    if gen.get("status") == "failed":

                        st.error(gen.get("error") or "Cypher generation failed")

                        if gen.get("generated_cypher"):

                            from core.cypher_repair import repair_cypher



                            st.code(repair_cypher(gen.get("generated_cypher", "")), language="sql")

                    else:

                        from core.cypher_repair import repair_cypher



                        cypher = repair_cypher(gen.get("generated_cypher", ""))

                        st.code(cypher, language="sql")

                        if cypher:

                            results = post(

                                "/execute-cypher",

                                {"cypher": cypher},

                            )

                            st.subheader("Results")

                            st.json(results.get("results", []))

            except httpx.HTTPStatusError as e:

                try:

                    detail = e.response.json().get("detail", e.response.text)

                except Exception:

                    detail = e.response.text

                st.error(detail)

            except httpx.ConnectError:

                st.error(

                    f"Cannot reach API at {API_BASE}. "

                    "Start it with: `python -m uvicorn api:app --reload --host 127.0.0.1 --port 8001`"

                )

            except Exception as e:

                st.error(str(e))



with tab3:

    st.subheader("SPARQL query")

    sparql = st.text_area(

        "SPARQL",

        value=(

            "PREFIX hc: <http://example.org/healthcare-hospital.owl#>\n"

            "SELECT ?patient WHERE { ?patient rdf:type hc:Patient }"

        ),

        height=120,

    )

    if st.button("Run SPARQL"):

        try:

            st.json(post("/sparql", {"query": sparql}))

        except Exception as e:

            st.error(str(e))



    st.divider()

    nl_question = st.text_input("Or ask in English (LLM → SPARQL)")

    if st.button("LLM SPARQL") and nl_question:

        with st.spinner("Generating SPARQL..."):

            try:

                st.json(post("/llm-query", {"question": nl_question}))

            except Exception as e:

                st.error(str(e))



with tab4:

    st.subheader("Semantic search (run /embedding/sync first)")

    q = st.text_input("Search query", value="heart disease treatment")

    top_k = st.slider("top_k", 1, 20, 5)

    if st.button("Search embeddings"):

        try:

            results = get("/embedding/search", query=q, top_k=top_k)

            st.json(results)

        except Exception as e:

            st.error(str(e))



    concept = st.text_input("Similar to concept", value="Patient")

    if st.button("Find similar"):

        try:

            st.json(get(f"/embedding/similar/{concept}", top_k=top_k))

        except Exception as e:

            st.error(str(e))



with tab5:

    st.subheader("Service health")

    for label, path in [

        ("API", "/health"),

        ("Neo4j", "/neo4j/health"),

        ("Embeddings", "/embedding/health"),

    ]:

        try:

            st.write(f"**{label}**")

            st.json(get(path))

        except Exception as e:

            st.warning(f"{label}: {e}")



    st.caption("Neo4j is a derived projection of the RDF/OWL ontology (the authority). Loading is idempotent and never clears memory, documents or embeddings.")

    if st.button("Synchronize Neo4j projection from RDF", type="primary"):

        with st.spinner("Exporting OWL → Neo4j..."):

            try:

                st.json(post("/neo4j/load", {}))

            except Exception as e:

                st.error(str(e))



    if st.button("Sync embeddings to Neo4j"):

        with st.spinner("Syncing ontology annotations..."):

            try:

                st.json(post("/embedding/sync", {}))

            except Exception as e:

                st.error(str(e))


