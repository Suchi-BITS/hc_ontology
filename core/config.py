import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@lru_cache
def get_settings():
    shapes_dir = os.getenv("SHAPES_DIR", str(_PROJECT_ROOT / "shapes"))
    data_dir = os.getenv("DATA_DIR", str(_PROJECT_ROOT / "data"))
    reports_dir = os.getenv(
        "VALIDATION_REPORTS_DIR",
        str(_PROJECT_ROOT / "validation_reports"),
    )
    # warn: warnings/infos do not flip conforms=False (pySHACL allow_warnings)
    # strict: any Warning also fails conformance
    validation_mode = os.getenv("SHACL_VALIDATION_MODE", "warn").lower()
    if validation_mode not in ("warn", "strict"):
        validation_mode = "warn"

    return {
        "app_name": os.getenv("APP_NAME", "Healthcare Ontology API"),
        "app_version": os.getenv("APP_VERSION", "1.0.0"),
        "environment": os.getenv("ENVIRONMENT", "development"),
        "debug": os.getenv("DEBUG", "false").lower() == "true",
        "owl_file": os.getenv("OWL_FILE_PATH", "healthcare_ontology.owl"),
        "shapes_dir": shapes_dir,
        "data_dir": data_dir,
        "sample_instances_dir": str(Path(data_dir) / "sample_instances"),
        "validation_reports_dir": reports_dir,
        "shacl_validation_mode": validation_mode,
        "ollama_model": os.getenv("OLLAMA_MODEL", "qwen2.5:latest"),
        "embedding_model": os.getenv("EMBEDDING_MODEL", "nomic-embed-text:latest"),
        "neo4j_uri": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        "neo4j_username": os.getenv("NEO4J_USERNAME", "neo4j"),
        "neo4j_password": os.getenv("NEO4J_PASSWORD", ""),
        "neo4j_database": os.getenv("NEO4J_DATABASE", "neo4j"),
        "api_key": os.getenv("API_KEY", ""),
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
        "api_base_url": os.getenv("API_BASE_URL", "http://127.0.0.1:8000"),
        "project_root": str(_PROJECT_ROOT),
        "query_default_limit": int(os.getenv("QUERY_DEFAULT_LIMIT", "200")),
        "query_timeout_seconds": float(os.getenv("QUERY_TIMEOUT_SECONDS", "30")),
        "llm_rate_limit_per_minute": int(os.getenv("LLM_RATE_LIMIT_PER_MINUTE", "10")),
        "query_cache_ttl_seconds": float(os.getenv("QUERY_CACHE_TTL_SECONDS", "300")),
        "agent_max_retries": int(os.getenv("AGENT_MAX_RETRIES", "3")),
        "agent_force_hitl": os.getenv("AGENT_FORCE_HITL", "false").lower() == "true",
        # Enterprise
        "default_tenant_id": os.getenv("DEFAULT_TENANT_ID", "default"),
        "rbac_enabled": os.getenv("RBAC_ENABLED", "true").lower() == "true",
        "guardrails_enabled": os.getenv("GUARDRAILS_ENABLED", "true").lower() == "true",
        "cost_budget_usd_per_day": float(os.getenv("COST_BUDGET_USD_PER_DAY", "25")),
        "langchain_tracing": os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true",
        "langchain_api_key": os.getenv("LANGCHAIN_API_KEY", "") or os.getenv("LANGSMITH_API_KEY", ""),
        "langchain_project": os.getenv("LANGCHAIN_PROJECT", "healthcare-ontology-agents"),
        "langsmith_endpoint": os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
        "otel_enabled": os.getenv("OTEL_ENABLED", "false").lower() == "true",
        "otel_service_name": os.getenv("OTEL_SERVICE_NAME", "healthcare-ontology-api"),
        "otel_exporter_otlp_endpoint": os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
    }
