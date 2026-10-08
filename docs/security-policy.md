# Security policy: the one place that decides

One pure function, `core/security_policy.py: decide(...)`, decides how the API authenticates and authorizes. `core/security.py`, `core/authz.py` and `core/graph_domains.py` all ask it; none keeps its own opinion. The test `tests/test_security_policy.py` runs it over every combination of environment, credentials, opt-in and RBAC setting and proves the one invariant that matters:

> **No combination of settings produces unauthenticated + admin + production.** Open mode needs *all three* of: no credentials, a non-production environment, and an explicit opt-in. In production the opt-in is not honoured at all.

This document is the specification; the code and the tests are the enforcement. Design background: [security-architecture.md](security-architecture.md). Settings reference: [security-and-configuration.md](security-and-configuration.md).

## 1. Environments

`ENVIRONMENT` is classified, not trusted as written:

| Class | ENVIRONMENT values | Meaning |
|---|---|---|
| development | `development`, `dev`, `local` | A developer's machine |
| testing | `test`, `testing` | Automated tests |
| **production** | **anything else, including unset, empty, `prod`, `staging`, and a typo such as `develpment`** | Fail closed |

An unset `ENVIRONMENT` is **production**. The `.env` that `python scripts/dev.py setup` creates sets `ENVIRONMENT=development`, so local work is unchanged.

## 2. Behaviour

| Situation | development | testing | production |
|---|---|---|---|
| Credentials configured | every request must authenticate (**enforced**) | enforced | enforced |
| No credentials, `ALLOW_OPEN_DEVELOPMENT_MODE=false` (default) | **refuses to start**, message says how to opt in | refuses to start | refuses to start |
| No credentials, `ALLOW_OPEN_DEVELOPMENT_MODE=true` | **open**: every request is admin `local-developer`, announced at startup | open | **refuses to start**; the flag is ignored and reported |
| `RBAC_ENABLED=false` | honoured | honoured | **ignored**, authorization stays on |
| Role or tenant sent in a header | never trusted in any environment | | |

*Credentials* means at least one record in `API_CREDENTIALS_FILE` or a legacy `API_KEY`. Credentials always win: once one exists, even a developer machine is enforced.

`ALLOW_OPEN_DEVELOPMENT_MODE` is a strict boolean. `ture` is a startup error, not a quiet `false`.

## 3. Developer experience

Nothing about the ordinary local workflow changes: `python scripts/dev.py setup` writes a `.env` with `ENVIRONMENT=development` and `ALLOW_OPEN_DEVELOPMENT_MODE=true`, so `python scripts/dev.py serve` runs open exactly as before. To work *with* authentication, create a credential (`python scripts/dev.py credential add --user <you> --tenant <tenant> --role admin`); the open mode then switches itself off.

An existing `.env` from before this policy has `ENVIRONMENT=development` but no opt-in. The server then refuses to start and its message names the line to add. That one-line friction is the point: the open mode is now something a developer chose.

## 4. Docker Compose

`docker_compose.yaml` is **production-mode by default**:

- the API container gets `ENVIRONMENT: production` and `ALLOW_OPEN_DEVELOPMENT_MODE: "false"` as literals. They are not read from `.env`, because `.env` describes the *host's* development setting and must not leak into the container;
- without `API_KEY` (or a credentials file in the image, which `.dockerignore` excludes) the container exits at startup with the policy's message. It is limited to three restarts rather than looping;
- published ports are bound to `127.0.0.1` by default (`API_BIND`, `NEO4J_BIND`, `STREAMLIT_BIND`). Exposing a port to other machines is a deliberate edit, not an accident;
- the legacy `API_KEY` maps to one identity: tenant `DEFAULT_TENANT_ID`, role `API_KEY_ROLE` (default `analyst`).

Secure start:

```bash
export API_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
docker compose -f docker_compose.yaml up -d --build
```

Explicit local development without credentials (open admin, loopback only):

```bash
docker compose -f docker_compose.yaml -f docker_compose.dev.yaml up -d --build
```

The override file sets `ENVIRONMENT=development` and `ALLOW_OPEN_DEVELOPMENT_MODE=true` for the API container and nothing else. It does not touch ports, so they stay on `127.0.0.1`. Do not combine it with `API_BIND=0.0.0.0`.

## 5. Kubernetes

`k8s/deployment.yaml` assumes the following; they are also written at the top of the file.

- **Image:** an explicit version tag (currently `1.0.0`, matching `pyproject.toml`) or, better, a digest. `:latest` is not used, and the CD workflow no longer publishes it. Replace `REPLACE_WITH_OWNER` with your registry owner.
- **Secrets:** the `healthcare-ontology-secrets` Secret is created outside the manifest (`kubectl create secret generic ...`). No Secret object is defined in the file, because applying one with empty values would overwrite a real one.
- **Mode:** `ENVIRONMENT=production`, `ALLOW_OPEN_DEVELOPMENT_MODE=false`. Without `API_KEY` in the Secret the pods fail to start (fail closed).
- **Tracing:** `LANGCHAIN_TRACING_V2=false` and `OTEL_ENABLED=false`. LangSmith tracing sends prompts and answers to a third party; enable it only deliberately, with its key in the Secret and a data-handling decision behind it.
- **Pod security:** `runAsNonRoot` with uid/gid 10001 (the Dockerfile's `app` user), `seccompProfile: RuntimeDefault`, `automountServiceAccountToken: false`.
- **Container security:** `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]`. Writable paths are two size-limited `emptyDir` volumes: `/tmp` and `/app/validation_reports`.
- **Resources:** CPU and memory requests and limits, plus an ephemeral-storage limit. SPARQL runs in up to `SPARQL_WORKERS` extra processes inside the container's memory limit.
- **Not covered:** Neo4j itself (assumed to be the Service `neo4j`), TLS and authentication at the Ingress, NetworkPolicy, a PodSecurity admission level. These are the operator's decisions.

## 6. SPARQL execution limit

Every externally submitted SPARQL query is bounded by `SPARQL_QUERY_TIMEOUT_SECONDS` (default 15, allowed 0.1 to 300; there is no unlimited value). `SPARQL_WORKERS` (default 2, 1 to 8) sets how many worker processes run queries.

**Why a process.** rdflib evaluates a query inside one synchronous call that cannot be cancelled. `asyncio.wait_for`, a client-side timeout, or a thread with a timeout only stop *waiting*: the work continues and the CPU stays pinned. The previous implementation did exactly that (a thread inside `with ThreadPoolExecutor`: on timeout the `with` block still waited for the thread to finish, so a four-way cartesian `COUNT(*)` held the request indefinitely). The only mechanism that really stops the computation is stopping the process that runs it. So queries run in worker processes; at the limit the parent kills the worker, starts a fresh one for the next request, and answers `504` with `SPARQL query exceeded the N-second limit and was terminated`. No stack trace or internal path is returned.

**What you pay.** One process and one parsed copy of the ontology per worker (memory); about a second to start a worker, once and again after each kill; the partial work of a killed query. **What you get.** A hard bound, and faster ordinary queries than before, because the parsed graph stays warm instead of being parsed on every call. When every worker is busy for the whole limit a request fails with `503` instead of queueing without bound.

**What it does not bound.** Memory *inside* one query (result size is bounded separately by the injected `LIMIT`), and Cypher, which has its own timeout in the Neo4j driver. All SPARQL paths use it: `/sparql`, the agent's execution node, and generated queries.

## 7. What is and is not verified

Verified by tests that ran: the policy over its whole input space; the startup refusal; the 504 and the process kill, with real worker processes; configuration validation; and the static properties of the Compose and Kubernetes files. Checked once by `docker compose config` (which needs no daemon): the resolved Compose files are production-mode by default and loopback-bound, and the override flips only the mode.

**Not verified:** starting the containers (no Docker daemon in the verification environment), applying the manifest to a cluster, the effect of `readOnlyRootFilesystem` on a running pod (the writable paths were derived from the code, not observed), and Linux/macOS behaviour of the worker processes (verified on Windows).
