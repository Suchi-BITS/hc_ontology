"""
Healthcare Ontology API — application entry point.

Run:
    uvicorn api:app --reload --host 127.0.0.1 --port 8000
"""

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI

from core.config import get_settings
from core.logging_config import setup_logging
from routers import clinical, doctors, embedding, neo4j, ontology, patients, shacl, sparql, system

logger = setup_logging()
settings = get_settings()

app = FastAPI(
    title=settings["app_name"],
    description="""
Healthcare Ontology Platform — Udemy course project.

**Pipelines**
- OWL ontology exploration (Owlready2)
- SPARQL querying (RDFLib)
- Natural language → SPARQL (Ollama + LangChain)
- SPARQL → Cypher → Neo4j
- Natural language → Cypher (Ollama)
- Semantic vector search (Ollama embeddings + Neo4j)
- SHACL validation (pySHACL)
- Query validation (SPARQL/Cypher safety + schema whitelist)
- Async LLM jobs (`/llm-query/async`, `/nl-to-cypher/async` → `/jobs/{id}`)

**Setup**
1. Configure `.env` from `.env.example`
2. Start Ollama and Neo4j
3. `POST /embedding/sync` before semantic search
    """,
    version=settings["app_version"],
)

app.include_router(system.router)
app.include_router(ontology.router)
app.include_router(patients.router)
app.include_router(doctors.router)
app.include_router(clinical.router)
app.include_router(sparql.router)
app.include_router(neo4j.router)
app.include_router(embedding.router)
app.include_router(shacl.router)


@app.on_event("startup")
def on_startup():
    from core.query_cache import query_cache

    query_cache.ttl_seconds = float(settings["query_cache_ttl_seconds"])
    logger.info(
        "Starting %s v%s [%s] query_cache_ttl=%ss llm_rate_limit=%s/min",
        settings["app_name"],
        settings["app_version"],
        settings["environment"],
        settings["query_cache_ttl_seconds"],
        settings["llm_rate_limit_per_minute"],
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=settings["debug"],
    )
