import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


class ConfigurationError(ValueError):
    """A setting has a value the application cannot safely run with. The message names the setting."""


def _env_bool(name: str, default: bool = False) -> bool:
    """Strict boolean: a typo such as ALLOW_OPEN_DEVELOPMENT_MODE=ture must fail, not quietly mean false."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    raise ConfigurationError(f"{name} must be true or false, got {raw!r}")


def _env_number(name: str, default: float, low: float, high: float, integer: bool = False) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    kind = "a whole number" if integer else "a number"
    try:
        value = float(raw)
        if integer and value != int(value):
            raise ValueError
    except ValueError:
        raise ConfigurationError(f"{name} must be {kind} between {low:g} and {high:g}, got {raw!r}") from None
    if not (low <= value <= high):  # also rejects nan and inf
        raise ConfigurationError(f"{name} must be {kind} between {low:g} and {high:g}, got {raw!r}")
    return int(value) if integer else value


def _secret(name: str, default: str = "") -> str:
    """Read a credential; an unfilled `.env.example` placeholder such as <your-api-key> counts as unset."""
    value = os.getenv(name, default) or ""
    if value.startswith("<") and value.endswith(">"):
        return ""
    return value


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
        # Unset means production: the safe default. Local development sets ENVIRONMENT=development
        # (the generated .env does) and, to run without credentials, ALLOW_OPEN_DEVELOPMENT_MODE=true.
        "environment": os.getenv("ENVIRONMENT", "production"),
        # Explicit opt-in for running with NO credentials. Honoured only in development/testing
        # environments; ignored (and reported) anywhere else. See core/security_policy.py.
        "allow_open_development_mode": _env_bool("ALLOW_OPEN_DEVELOPMENT_MODE", False),
        # Every externally submitted SPARQL query is bounded by this. Never unlimited.
        "sparql_query_timeout_seconds": _env_number("SPARQL_QUERY_TIMEOUT_SECONDS", 15.0, 0.1, 300.0),
        "sparql_workers": _env_number("SPARQL_WORKERS", 2, 1, 8, integer=True),
        # Development-only opt-in for removing the RDF projection from Neo4j (never in production).
        "allow_projection_reset": os.getenv("ALLOW_PROJECTION_RESET", "false").lower() == "true",
        "debug": os.getenv("DEBUG", "false").lower() == "true",
        # The runtime dataset is two artifacts: the SCHEMA and (optionally) the synthetic SAMPLE DATA.
        # An empty SAMPLE_DATA_FILE runs the platform on the schema alone. See core/dataset.py.
        "ontology_schema_file": os.getenv("ONTOLOGY_SCHEMA_FILE", "ontology/healthcare_schema.ttl"),
        "sample_data_file": os.getenv("SAMPLE_DATA_FILE", "data/sample_data.ttl"),
        "shapes_dir": shapes_dir,
        "data_dir": data_dir,
        "sample_instances_dir": str(Path(data_dir) / "sample_instances"),
        "validation_reports_dir": reports_dir,
        "shacl_validation_mode": validation_mode,
        "openai_api_key": _secret("OPENAI_API_KEY"),
        "llm_model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        "embedding_model": os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        "embedding_dimensions": int(
            os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "1536")
        ),
        "neo4j_uri": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        # NEO4J_USERNAME is the project's name; NEO4J_USER is accepted as an alias (Neo4j Desktop's own wording).
        "neo4j_username": os.getenv("NEO4J_USERNAME") or os.getenv("NEO4J_USER") or "neo4j",
        "neo4j_password": _secret("NEO4J_PASSWORD"),
        "neo4j_database": os.getenv("NEO4J_DATABASE", "neo4j"),
        "api_key": os.getenv("API_KEY", ""),
        # Authentication (see docs/security-architecture.md): identity, role and tenant come from a
        # server-side credential record, never from request headers.
        "api_credentials_file": os.getenv("API_CREDENTIALS_FILE", ".credentials.json"),
        "api_key_role": os.getenv("API_KEY_ROLE", "analyst"),
        "trusted_proxies": os.getenv("TRUSTED_PROXIES", ""),  # peers allowed to set X-Forwarded-For
        "allow_demo_seed": os.getenv("ALLOW_DEMO_SEED", "false").lower() == "true",
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
        "api_base_url": os.getenv("API_BASE_URL", "http://127.0.0.1:8000"),
        "project_root": str(_PROJECT_ROOT),
        "query_default_limit": int(os.getenv("QUERY_DEFAULT_LIMIT", "200")),
        "query_timeout_seconds": float(os.getenv("QUERY_TIMEOUT_SECONDS", "30")),
        "llm_rate_limit_per_minute": int(os.getenv("LLM_RATE_LIMIT_PER_MINUTE", "10")),
        "query_cache_ttl_seconds": float(os.getenv("QUERY_CACHE_TTL_SECONDS", "300")),
        "agent_max_retries": int(os.getenv("AGENT_MAX_RETRIES", "3")),
        "agent_force_hitl": os.getenv("AGENT_FORCE_HITL", "false").lower() == "true",
        "agent_abstention_threshold": float(os.getenv("AGENT_ABSTENTION_THRESHOLD", "0.45")),
        # Ontology-only answers (no query, no rows) are refused unless the best retrieved concept is at least this relevant.
        "agent_ontology_min_relevance": _env_number("AGENT_ONTOLOGY_MIN_RELEVANCE", 0.30, 0.0, 1.0),
        "agent_retrieval_pool_size": int(os.getenv("AGENT_RETRIEVAL_POOL_SIZE", "16")),
        "agent_retrieval_top_k": int(os.getenv("AGENT_RETRIEVAL_TOP_K", "8")),
        "agent_structured_llm": os.getenv("AGENT_STRUCTURED_LLM", "true").lower() == "true",
        # Memory subsystem
        "working_memory_max_chars": int(os.getenv("WORKING_MEMORY_MAX_CHARS", "6000")),
        "episodic_context_turns": int(os.getenv("EPISODIC_CONTEXT_TURNS", "5")),
        "episodic_similar_top_k": int(os.getenv("EPISODIC_SIMILAR_TOP_K", "3")),
        "procedural_match_threshold": float(os.getenv("PROCEDURAL_MATCH_THRESHOLD", "0.35")),
        "procedural_auto_learn": os.getenv("PROCEDURAL_AUTO_LEARN", "true").lower() == "true",
        "procedural_min_confidence": float(os.getenv("PROCEDURAL_MIN_CONFIDENCE", "0.7")),
        "semantic_enable_graph_rag": os.getenv("SEMANTIC_ENABLE_GRAPH_RAG", "true").lower() == "true",
        # Meta-memory (control plane over four-memory subsystem)
        "meta_memory_enabled": os.getenv("META_MEMORY_ENABLED", "true").lower() == "true",
        "meta_memory_retain_threshold": float(os.getenv("META_MEMORY_RETAIN_THRESHOLD", "0.35")),
        "meta_memory_session_archive_turns": int(os.getenv("META_MEMORY_SESSION_ARCHIVE_TURNS", "15")),
        "meta_memory_keep_recent_turns": int(os.getenv("META_MEMORY_KEEP_RECENT_TURNS", "5")),
        "meta_memory_purge_failed": os.getenv("META_MEMORY_PURGE_FAILED", "false").lower() == "true",
        "meta_memory_failed_ttl_hours": int(os.getenv("META_MEMORY_FAILED_TTL_HOURS", "24")),
        "meta_memory_procedure_decay_days": int(os.getenv("META_MEMORY_PROCEDURE_DECAY_DAYS", "30")),
        "memory_debug_context": os.getenv("MEMORY_DEBUG_CONTEXT", "false").lower() == "true",
        "memory_debug_context_full": os.getenv("MEMORY_DEBUG_CONTEXT_FULL", "false").lower() == "true",
        # The optional AI layer (agent, enterprise, embeddings, documents routers). The core API does not need it.
        "enable_ai_layer": os.getenv("ENABLE_AI_LAYER", "true").lower() == "true",
        # Enterprise
        "default_tenant_id": os.getenv("DEFAULT_TENANT_ID", "default"),
        "rbac_enabled": os.getenv("RBAC_ENABLED", "true").lower() == "true",
        "guardrails_enabled": os.getenv("GUARDRAILS_ENABLED", "true").lower() == "true",
        "cost_budget_usd_per_day": float(os.getenv("COST_BUDGET_USD_PER_DAY", "25")),
        "langchain_tracing": os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true",
        "langchain_api_key": _secret("LANGCHAIN_API_KEY") or _secret("LANGSMITH_API_KEY"),
        "langchain_project": os.getenv("LANGCHAIN_PROJECT", "healthcare-ontology-agents"),
        "langsmith_endpoint": os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
        "otel_enabled": os.getenv("OTEL_ENABLED", "false").lower() == "true",
        "otel_service_name": os.getenv("OTEL_SERVICE_NAME", "healthcare-ontology-api"),
        "otel_exporter_otlp_endpoint": os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
    }


def require_neo4j_password() -> str:
    """Return NEO4J_PASSWORD or fail with an actionable message (never prints the value)."""
    password = get_settings().get("neo4j_password") or ""
    if not password:
        raise RuntimeError(
            "NEO4J_PASSWORD is not set. It is required to connect to Neo4j "
            "(used by /neo4j/*, /embedding/*, /documents/* and the agent memory). "
            "Copy .env.example to .env and set NEO4J_PASSWORD, or export it in the "
            "environment. See docs/security-and-configuration.md."
        )
    return password


def missing_configuration() -> list[str]:
    """Names (never values) of unset variables that gate external services."""
    s = get_settings()
    missing = []
    if not s.get("openai_api_key"):
        missing.append("OPENAI_API_KEY (LLM, embeddings, agent)")
    if not s.get("neo4j_password"):
        missing.append("NEO4J_PASSWORD (Neo4j graph, embeddings, memory)")
    return missing
