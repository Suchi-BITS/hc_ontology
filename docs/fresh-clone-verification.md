# Fresh-clone verification

A checklist for "does this project work from a fresh clone?", with an honest record of what has and has not been checked.

Three labels are used, and they are not interchangeable:

| Label | Meaning |
|---|---|
| **VERIFIED** | The step was actually executed, in this repository, and produced the stated result. |
| **STATICALLY VERIFIED** | Inspected or parsed by a tool, or covered by a consistency test, but the thing itself was not run. |
| **NOT VERIFIED** | Neither. Written to be correct, but unproven. |

Nothing in this project should be described as "works from a fresh clone" beyond the **VERIFIED** column.

## The fresh-clone procedure that was run

The files git would contain (`git ls-files --cached --others --exclude-standard`: tracked plus untracked-but-not-ignored) were copied into an empty directory. There was no `venv/`, no `.env`, no caches, no `.git`. Then, using only the system Python:

```bash
python scripts/dev.py quickstart      # setup -> doctor -> validate -> test -> demo
```

Environment: Windows 11, Python 3.11.8, Java present, git present, **Docker installed but its daemon not running**, no Neo4j, no OpenAI key, network behind antivirus HTTPS scanning (pip's `CERTIFICATE_VERIFY_FAILED` occurred and was recovered automatically).

| Stage | Result |
|---|---|
| `setup` | virtualenv created; TLS fallback engaged and recovered; pinned dependencies installed from `requirements.txt` + `constraints.txt`; `.env` generated with a random Neo4j password |
| `doctor` | every required check PASS; Docker, Neo4j and OpenAI key reported as optional/not available |
| `validate` | `VALIDATION PASSED` |
| `test` | **526 passed, 7 expected failures (documented known gaps), 0 failed** |
| `demo` | completed |

Two earlier runs of this same procedure **failed** and led to fixes: 7 tests needed a real `OPENAI_API_KEY` (now a placeholder key in tests), and a test expected a directory that the simulation had skipped (the simulation was made faithful).

## Checklist

Tick these on your own machine. The right-hand column says how each is known.

### Prerequisites

- [ ] Python 3.11 installed (`python --version`): **VERIFIED** on 3.11.8. 3.12+ is **NOT VERIFIED** (`setup` warns, does not block).
- [ ] git installed: **VERIFIED**.
- [ ] Java installed, only for the 6 reasoner tests: **VERIFIED** (present here); behaviour without Java (tests skip) is **STATICALLY VERIFIED** (skip marker).
- [ ] Docker with Compose v2, only for Neo4j: Compose CLI present, **daemon not running here**.

### Clone and configure

- [ ] The clone contains no virtualenv, caches or secrets: **VERIFIED** (the simulation copies exactly what git would contain; tests check `.gitignore`, `.dockerignore`, `.env.example`).
- [ ] `.env.example` exists and documents every variable the code reads: **STATICALLY VERIFIED** (`tests/test_consistency.py`).
- [ ] `python scripts/dev.py setup` creates `venv/`, installs pinned dependencies and `.env`: **VERIFIED** (three pristine runs).
- [ ] pip TLS failure behind a proxy/antivirus is recovered: **VERIFIED** (occurred in every run here); the logic is also unit-tested with a scripted pip (`tests/test_devtools.py`).
- [ ] `python scripts/dev.py doctor` reports problems and fixes: **VERIFIED**.
- [ ] Linux and macOS: **NOT VERIFIED** (no such machine here; the CI `quickstart` job runs on Ubuntu and has not run yet).
- [ ] `make <command>` wrappers: **NOT VERIFIED** (no `make` here; thin wrapper over `dev.py`).

### Dependencies

- [ ] `requirements.txt` (runtime) / `requirements-dev.txt` (tests) are consistent with `constraints.txt`: **STATICALLY VERIFIED** (every requirement is pinned and satisfied; every third-party import in the application is pinned; no leftover packages).
- [ ] The pinned set installs and runs the full suite: **VERIFIED**.
- [ ] `pyproject.toml` is valid and builds package metadata: **VERIFIED** (`pip install --dry-run ".[dev]"` executed).
- [ ] pytest has one configuration (in `pyproject.toml`): **STATICALLY VERIFIED**.

### Validation and tests

- [ ] `python scripts/dev.py validate` passes (parse, generator equals file, SHACL, projection plan): **VERIFIED**.
- [ ] `validate --reasoner` (OWL consistency, needs Java): **VERIFIED** through the reasoner tests.
- [ ] `python scripts/dev.py test` passes with no Neo4j and no API keys: **VERIFIED** (526 passed).
- [ ] The README's SPARQL and validation examples return what the README says: **VERIFIED** (they are tests).
- [ ] `python scripts/dev.py demo` runs offline: **VERIFIED**.

### Services and loading (needs Docker/Neo4j)

- [ ] `docker_compose.yaml` is valid and requires a Neo4j password: **VERIFIED** with Docker's own `docker compose config` (accepted with a password, rejected without one, with the intended message).
- [ ] Compose ports, health check, `depends_on: service_healthy`, no secret defaults, no source mount: **STATICALLY VERIFIED** (tests parse the file).
- [ ] `python scripts/dev.py up` starts Neo4j and waits until healthy: **NOT VERIFIED** (no Docker daemon).
- [ ] The Neo4j health check command works in the image: **NOT VERIFIED**.
- [ ] `python scripts/dev.py load` loads the projection and `--verify` matches the counts: **NOT VERIFIED** against a real Neo4j. The statements, transaction order, scoping, SHACL gate and idempotence are **VERIFIED** against a recording driver.
- [ ] Loading twice gives the same graph: **VERIFIED** at the statement level; **NOT VERIFIED** in a database.
- [ ] Cypher examples in the README return rows: **NOT VERIFIED** (the queries follow the tested projection, but were not run).
- [ ] `python scripts/dev.py demo --neo4j`: **NOT VERIFIED**.

### Docker image

- [ ] `docker build` succeeds: **NOT VERIFIED** (no daemon). Dockerfile contents (pinned install, non-root user, health check, copied files exist, no secrets) are **STATICALLY VERIFIED**.
- [ ] The container starts and `/health` answers: **NOT VERIFIED**.
- [ ] No secret enters the image: **STATICALLY VERIFIED** (`.dockerignore` excludes `.env`; no `ENV`/`ARG` with secrets; compose passes values at runtime).

### API

- [ ] `python scripts/dev.py serve` starts uvicorn: **NOT VERIFIED** as a running server; the same application is exercised in-process by the test suite (**VERIFIED**).
- [ ] The README's endpoint table matches the API: **STATICALLY VERIFIED** (43 endpoints compared with OpenAPI).
- [ ] Streamlit UI starts: **NOT VERIFIED**.

### OpenAI-dependent features

- [ ] Natural-language queries, embeddings, GraphRAG, agent: **NOT VERIFIED** (no key; these were never run in this exercise).
- [ ] The application starts without a key and names the missing variable when a feature needs one: **VERIFIED** (tests).

### CI

- [ ] `.github/workflows/*.yml` parse: **STATICALLY VERIFIED**.
- [ ] The CI jobs (`quickstart`, `neo4j`, `docker`) pass on GitHub: **NOT VERIFIED** (not yet run).

## Reproducibility problems found in this repository

| Problem | Found by | Status |
|---|---|---|
| README, scripts and compose described Ollama; code uses OpenAI | scan of docs vs code | fixed; `test_only_openai_is_configured_as_the_llm_provider` |
| `.env.example` missing; many environment variables undocumented | file check; code scan | fixed; `test_every_environment_variable_the_code_reads_is_documented_in_env_example` |
| Three Neo4j database names (`hcontology`, `HC`, `neo4j`) across files | grep | one name, tested |
| Unpinned and mixed runtime/test dependencies | inspection | `requirements*.txt` + `constraints.txt` + `pyproject.toml` |
| `constraints.txt` first generated from a shared developer virtualenv (carried Ollama, SQLAlchemy, aiohttp and others) | dependency closure comparison | regenerated from the resolved closure; leftovers are a test failure |
| Committed `venv/` (15,736 files) | git inventory | removed from the index |
| pip `CERTIFICATE_VERIFY_FAILED` on proxied/antivirus networks | the first fresh-clone attempt | automatic, announced fallback |
| 7 tests required a real OpenAI key | the first pristine run | tests use a placeholder key |
| Compose file was invalid YAML | a test | fixed and checked by Docker |
| Compose required an OpenAI key and Ollama, mounted the source tree over the image | inspection | removed |
| Placeholders such as `<your-openai-api-key>` were treated as real keys | reading `core/config.py` | treated as unset |
| README SPARQL example returned nothing (`"E11"` vs `"E11"^^xsd:string`) | executing the README example | SPARQL execution normalises string literals; the example is now a test |
| Container ran as root, no health check | inspection | non-root user, health check |
| CRLF line endings in `setup.sh` | file inspection | `.gitattributes` |
| No single documented path from clone to demo | README review | `dev.py quickstart` and the README sections 1 to 12 |

## Remaining risks

* **Everything involving Docker and Neo4j is unproven.** That is the largest gap. The first thing to do on a machine with Docker: `python scripts/dev.py up && python scripts/dev.py load && python scripts/dev.py demo --neo4j`, then run the Cypher examples.
* **Only Windows + Python 3.11 has been exercised.**
* **Unpinned transitive differences on Linux:** `constraints.txt` was resolved on Windows; Linux-only dependencies (for example `uvloop`) resolve to whatever is current.
* **First install requires network access** to PyPI; the TLS fallback briefly trusts the two PyPI hosts. Hash-pinned requirements would remove that.
* **The generated Neo4j password is for local development only.**
* **Known security gaps** remain (see [testing-strategy.md](testing-strategy.md) section 3).
