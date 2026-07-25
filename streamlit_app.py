"""
Healthcare Ontology Platform — Streamlit UI for course demos.

Run (API must be running):
    streamlit run streamlit_app.py
"""

import os

import httpx
import streamlit as st

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
        value="List all patients",
        height=80,
    )
    if st.button("Generate & run Cypher", type="primary"):
        with st.spinner("Generating Cypher (Ollama may take 1–3 min)..."):
            try:
                gen = post("/nl-to-cypher", {"question": question})
                st.code(gen.get("generated_cypher", ""), language="sql")
                if gen.get("generated_cypher"):
                    results = post(
                        "/execute-cypher",
                        {"cypher": gen["generated_cypher"]},
                    )
                    st.subheader("Results")
                    st.json(results.get("results", []))
            except httpx.HTTPStatusError as e:
                st.error(e.response.text)
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

    if st.button("Load ontology into Neo4j", type="primary"):
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
