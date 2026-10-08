# Security and Configuration

This is a teaching/reference project, not a clinical system. Do not load real patient data into it.

## What the application actually uses

Verified in code (`core/config.py`, `core/llm.py`, `services/*`):

| Service | Used? | Required for | Variables |
|---|---|---|---|
| OpenAI (chat + embeddings) | Yes | NL->SPARQL/Cypher, embeddings, GraphRAG, agent | `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_EMBEDDING_MODEL`, `OPENAI_EMBEDDING_DIMENSIONS` |
| Neo4j | Yes | `/neo4j/*`, `/embedding/*`, `/documents/*`, agent memory | `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` |
| LangSmith | Optional | Tracing (sends prompts/answers to a third party) | `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`, `LANGSMITH_ENDPOINT` |
| OpenTelemetry | Optional | Export traces | `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT` |
| Ollama | **No** | - | Not used anywhere in the code or configuration. |

The ontology, `/sparql`, SHACL validation and the read-only ontology routes work without OpenAI or Neo4j.

## Environment variables

`.env.example` lists every variable with placeholders. Copy it to `.env` and fill in values. Key groups:

- **Required for LLM/embedding/agent features:** `OPENAI_API_KEY`
- **Required for graph features:** `NEO4J_PASSWORD` (plus `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_DATABASE`)
- **API protection:** `API_KEY` (empty disables auth - local development only)
- **Optional telemetry:** LangSmith and OTEL variables (keep off unless you accept the data-sharing implications)
- **Tuning:** query limits, rate limits, agent and memory settings (defaults are in `core/config.py`)

### Behavior when a required value is missing

- At API startup, the log names each missing variable (never its value) as a warning. The API still starts so ontology-only features keep working.
- When a feature needs the value, it fails with an error naming the variable, the feature that needs it, and where to set it (`NEO4J_PASSWORD` via `core.config.require_neo4j_password`, `OPENAI_API_KEY` via `core.llm.require_api_key`).
- Docker Compose refuses to start the `api` service if `NEO4J_PASSWORD` or `OPENAI_API_KEY` is unset. There are no fallback passwords.

## Local development

```bash
python -m venv venv            # no virtual environment is committed
source venv/bin/activate       # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # then edit .env
python -m uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

Bind to `127.0.0.1` unless you have set `API_KEY` and put the service behind TLS.

## Docker

- `.dockerignore` keeps `.env`, `.env.*`, keys, `.git`, virtual environments and caches out of the build context, so credentials cannot be baked into an image.
- `docker_compose.yaml` passes configuration to containers as environment variables at runtime, taken from your shell or the project `.env` (Compose reads `.env` for substitution; it is not copied into the image).
- The source bind mount (`.:/app`) was removed from the `api` service because it exposed the host `.env` inside the container. For live-reload development, run uvicorn on the host instead.
- Kubernetes: `k8s/deployment.yaml` ships an empty Secret. Create the real one out of band (see the comment in the file) and do not `kubectl apply` the placeholder over an existing Secret.

## Credential rotation (action required)

Earlier local `docker build` runs used `COPY . .` with no `.dockerignore`, so a `.env` present in the working directory may have been copied into local images (and into any image that was pushed from such a build). The `.env` file was never committed to Git, and a scan of tracked files and history found no key-shaped strings, but treat the credentials as exposed and **rotate them**:

1. **OpenAI:** revoke the old key in the OpenAI dashboard, create a new one, update `.env`.
2. **LangSmith:** revoke and recreate the API key in LangSmith settings, update `.env`.
3. **Neo4j:** change the database user password (`ALTER CURRENT USER SET PASSWORD FROM '<old>' TO '<new>'` or via Neo4j Desktop), update `.env`.
4. Delete old local images (`docker image ls`, `docker image rm ...`) and, if any image was pushed to a registry, delete those tags and treat their contents as public.
5. Restart the API and any containers.

These steps are manual; nothing in this repository rotates credentials.

## What must never be committed

- `.env` or any `.env.*` file (only `.env.example`, with placeholders, is allowed)
- API keys, tokens, passwords, private keys, certificates (`*.pem`, `*.key`, `*.p12`, `*.pfx`)
- Kubernetes Secret manifests with real values
- Virtual environments (`venv/`, `.venv/`), `__pycache__/`, `*.pyc`
- Real patient data or validation reports containing it (`validation_reports/` is git-ignored)
- Debug output captured with `MEMORY_DEBUG_CONTEXT=true` (it prints prompts and ontology context)

## Authentication and credentials

Identity, role and tenant are looked up on the server from a credential; request headers such as `X-Role` and `X-Tenant-ID` are never trusted. Full design: [security-architecture.md](security-architecture.md).

```bash
python scripts/dev.py credential add --user suchismita --display-name "Suchismita" --tenant abhigya-ai-lab --role admin
python scripts/dev.py credential list
python scripts/dev.py credential remove --user suchismita
```

The key is printed once; only its SHA-256 hash is stored in `.credentials.json` (git-ignored, excluded from the Docker image). With at least one credential, every protected request must authenticate. With none, the server refuses to start, unless `ENVIRONMENT` is a development or testing value **and** you have set `ALLOW_OPEN_DEVELOPMENT_MODE=true`, which runs open as an admin `local-developer` (announced at startup). An unset or unknown `ENVIRONMENT` is production. The full specification is [security-policy.md](security-policy.md).

| Variable | Purpose |
|---|---|
| `API_CREDENTIALS_FILE` | Credential store (default `.credentials.json`) |
| `API_KEY`, `API_KEY_ROLE` | Legacy single shared key; maps to the default tenant with this role (default `analyst`) |
| `ALLOW_OPEN_DEVELOPMENT_MODE` | Explicit opt-in to run with no credentials (strict true/false). Honoured only in development/testing; ignored in production. Replaces the former `AUTH_MODE` |
| `SPARQL_QUERY_TIMEOUT_SECONDS` | Hard limit for every SPARQL query (default 15; 0.1 to 300; never unlimited). A longer query is terminated and the API answers 504 |
| `SPARQL_WORKERS` | Worker processes running SPARQL (default 2; 1 to 8) |
| `ALLOW_DEMO_SEED` | Development-only opt-in for `scripts/seed_neo4j_demo.py`; refused in production |
| `TRUSTED_PROXIES` | Peers whose `X-Forwarded-For` is believed for rate limiting (default: none) |

## Known remaining risks

See [security-architecture.md](security-architecture.md) section 10. In short: API-key authentication only (no OIDC/SSO), the clinical graph is shared across tenants, the tenant registry is in memory, Neo4j Community has no database roles (so the read-only transaction and the procedure allowlist stand in for a restricted user, and are not exercised against a live server here), the container still runs with default Docker networking, and the Git history still contains the previously committed `venv/` and `__pycache__/` (removing them needs a separate, coordinated history rewrite).
