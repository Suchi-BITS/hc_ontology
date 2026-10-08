"""
Healthcare Ontology API — application entry point.

Run:
    uvicorn api:app --reload --host 127.0.0.1 --port 8000
"""

from dotenv import load_dotenv

load_dotenv()

import logging
import sys

from core.ssl_config import configure_ssl

configure_ssl()

from fastapi import FastAPI

from core.config import get_settings
from core.logging_config import setup_logging
from routers import clinical, doctors, neo4j, ontology, patients, shacl, sparql, system

logger = setup_logging()
settings = get_settings()

app = FastAPI(
    title=settings["app_name"],
    description="""
Healthcare Ontology Platform — Udemy course project.

**Pipelines**
- OWL ontology exploration (Owlready2)
- SPARQL querying (RDFLib)
- Natural language → SPARQL (OpenAI + LangChain)
- SPARQL → Cypher → Neo4j
- Natural language → Cypher (OpenAI)
- Semantic vector search (OpenAI embeddings + Neo4j)
- SHACL validation (pySHACL)
- Query validation (SPARQL/Cypher safety + schema whitelist)
- Async LLM jobs (`/llm-query/async`, `/nl-to-cypher/async` → `/jobs/{id}`)
- Multi-agent LangGraph (`/agent/query`, `/agent/resume`, KG memory)
- Enterprise: multi-tenancy, RBAC, guardrails, hybrid retrieval, LangSmith/OTEL,
  eval, workflows, cost/monitoring (`/enterprise/*`)

**Setup**
1. Configure `.env` from `.env.example` (set `LANGCHAIN_API_KEY` for LangSmith)
2. Set `OPENAI_API_KEY` and `OPENAI_MODEL` in `.env`
3. Start Neo4j
4. `POST /embedding/sync` before semantic search
    """,
    version=settings["app_version"],
)

# CORE: ontology, RDF, SHACL, SPARQL, the graph projection and the clinical read APIs.
# Nothing here needs an LLM, an agent framework or a vector index.
app.include_router(system.router)
app.include_router(ontology.router)
app.include_router(patients.router)
app.include_router(doctors.router)
app.include_router(clinical.router)
app.include_router(sparql.router)
app.include_router(neo4j.router)
app.include_router(shacl.router)


def include_ai_layer(application: FastAPI) -> bool:
    """ADVANCED: embeddings, document ingestion, the LangGraph agent and the enterprise controls.

    Set ENABLE_AI_LAYER=false to run the core API alone. If the layer is enabled but its libraries are not
    installed, the core API still starts and says so, instead of failing to import.
    """
    if not get_settings()["enable_ai_layer"]:
        logger.info("AI layer disabled (ENABLE_AI_LAYER=false): serving the core API only")
        return False
    try:
        from routers import agent, documents, embedding, enterprise
    except ImportError as exc:  # openai / langchain / langgraph not installed
        logger.warning("AI layer unavailable (%s); serving the core API only. Install requirements.txt for the full stack.", exc)
        return False
    for module in (embedding, agent, enterprise, documents):
        application.include_router(module.router)
    return True


AI_LAYER_ACTIVE = include_ai_layer(app)


@app.on_event("startup")
def on_startup():
    from core.query_cache import query_cache
    from enterprise.observability import configure_observability

    query_cache.ttl_seconds = float(settings["query_cache_ttl_seconds"])
    # Refuse to start with unsafe security configuration (for example production with no credentials).
    from core.security import validate_security_configuration

    for warning in validate_security_configuration():
        logger.warning("SECURITY: %s", warning)
    from core.config import missing_configuration

    for item in missing_configuration():
        logger.warning(
            "Missing configuration: %s - dependent features will fail until it is set "
            "(see .env.example and docs/security-and-configuration.md)",
            item,
        )
    obs = configure_observability()
    logger.info(
        "Starting %s v%s [%s] query_cache_ttl=%ss llm_rate_limit=%s/min observability=%s",
        settings["app_name"],
        settings["app_version"],
        settings["environment"],
        settings["query_cache_ttl_seconds"],
        settings["llm_rate_limit_per_minute"],
        obs,
    )
    if settings.get("memory_debug_context"):
        banner = (
            "\n"
            + "=" * 78
            + "\nMEMORY_DEBUG_CONTEXT=true\n"
            "Memory snapshots print in THIS terminal when MEMORY_DEBUG_CONTEXT=true.\n"
            "Streamlit Ask (NL→Cypher) and POST /agent/query both print memory debug.\n"
            + "=" * 78
            + "\n"
        )
        sys.stderr.write(banner)
        sys.stderr.flush()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=settings["debug"],
    )
