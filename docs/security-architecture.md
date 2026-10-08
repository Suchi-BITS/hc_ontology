# Security Architecture: Identity, Authorization, Tenancy and Query Execution

This chapter explains who is trusted to say what in this system, and why the answer is almost always "the server, never the caller". It is written around one running example.

**The example.** *Abhigya AI Lab* is a tenant (`abhigya-ai-lab`). *Suchismita* is its administrator. A colleague who may only read, an analyst, a user of a different tenant (*Research Lab*), a platform operator, and an attacker complete the cast. Every test in `tests/test_security_architecture.py` uses these people.

## 1. Threat model

What we protect: patient-like records in the ontology and the graph; the integrity of the graph and of agent memory; one tenant's data from another tenant; the credentials; the ability to run expensive or dangerous work.

Who we defend against:

| Actor | Capability | Example attack |
|---|---|---|
| Anonymous network caller | Can reach the API | Call `POST /neo4j/load`, scrape `/patients` |
| Authenticated but low-privilege user | Has a valid key (a viewer) | Add `X-Role: admin` to be treated as an admin |
| User of another tenant | Valid key, wrong tenant | Add `X-Tenant-ID: abhigya-ai-lab`; guess a job id; read an ontology by id |
| Prompt-injected LLM | Produces text that is executed as a query | `MATCH (n) DETACH DELETE n`, `CALL apoc.cypher.doIt(...)` |
| Malicious query author | Types a query into `/execute-cypher` or `/sparql` | Comment tricks, `;` stacking, `SERVICE <http://evil>`, `FROM <http://evil>`, unbounded traversals |
| Careless operator | Runs a demo helper on the wrong system | Seed endpoint that wipes the database |
| Network observer / log reader | Sees traffic and logs | Recover keys from responses and logs |

Out of scope here (see limitations): TLS termination, DDoS, a compromised host, malicious dependencies.

## 2. Four ideas, kept apart

| Idea | Question | Where | Trusted input |
|---|---|---|---|
| **Identity** | Who is calling? Which tenant do they belong to? | `core/security.py` (`Identity`) | A server-side credential record |
| **Authentication** | Can they prove it? | `core/security.py` (`Authenticator`) | A secret they hold (API key) |
| **Authorization** | What may this identity do? | `core/authz.py` (`Permission`, `ROLE_PERMISSIONS`) | The identity's role, mapped on the server |
| **Tenant context** | Whose data may they touch? | `enterprise/tenancy.py` (`require_tenant`) | The identity's tenant |

Mixing these is how header-spoofing bugs happen. The earlier design read the role and tenant from `X-Role` and `X-Tenant-ID`, so a caller could *state* their identity instead of *proving* it.

## 3. Trust boundaries

### Before

```
caller ──(X-API-Key: one shared secret, optional)──▶ API
       ──(X-Role: admin)────────────────────────────▶ treated as the role
       ──(X-Tenant-ID: any)─────────────────────────▶ treated as the tenant
       ──(Cypher text)──▶ keyword blocklist ──▶ session.run (write-capable)
```

Everything in the arrows was believed. One shared key proved nothing about *who*; the headers then claimed everything else.

### After

```
caller ──(API key)──▶ AUTHENTICATION ──▶ Identity{subject, tenant, role}   <- built from a SERVER-SIDE record
                                              │
         X-Role, X-Tenant-ID, ?tenant_id ─────┤  (never inputs; a tenant mismatch is refused, a role claim is ignored and logged)
                                              ▼
                              AUTHORIZATION: role ──server table──▶ permissions ──▶ route allowed?
                                              ▼
                              TENANCY: identity.tenant ──▶ every tenant-scoped read/write
                                              ▼
              query text ──▶ allowlist policy ──▶ READ-ONLY transaction ──▶ server procedure allowlist
```

The line that matters: **the only things read from the request are the credential and the query text.** Everything else is looked up.

## 4. Authentication

* A **credential** is a record in a server-side file (`API_CREDENTIALS_FILE`, default `.credentials.json`, git-ignored): `id`, `tenant_id`, `role`, `display_name`, and a **SHA-256 hash** of a random 256-bit key. The key is shown once, when created, and never stored. (A fast hash is correct here: the key is 256 bits of randomness, not a human password, so there is nothing for a slow KDF to protect.)
* Creating Suchismita's credential:

  ```bash
  python scripts/dev.py credential add --user suchismita --display-name "Suchismita" \
         --tenant abhigya-ai-lab --role admin
  #   API key (shown ONCE, store it safely): hck_...
  ```
  She then sends `X-API-Key: hck_...` (or `Authorization: Bearer hck_...`).
* Lookup compares against *every* stored hash in constant time, so timing reveals nothing about which key was close.
* `Authenticator` is an interface. `ApiKeyAuthenticator` is the real implementation. An OIDC/JWT authenticator would build the same `Identity` from a verified token; nothing else (routers, authorization, tenancy, services) would change. **No authentication infrastructure beyond API keys is claimed.**
* Failures answer `401 {"detail": "Invalid or missing credentials"}` with no hint about which part failed, and are logged without the key.

### Modes (the only places where "open" is possible)

| `security_mode()` | When | Behavior |
|---|---|---|
| `enforced` | At least one credential exists (file or `API_KEY`) | Every protected request must authenticate |
| `development-open` | No credentials, a development/testing `ENVIRONMENT` **and** the explicit opt-in `ALLOW_OPEN_DEVELOPMENT_MODE=true` | Requests run as `local-developer` (admin). Announced as a startup warning. Headers are still not trusted. Never available in production: see [security-policy.md](security-policy.md) |
| `unconfigured` | No credentials in any other environment | Startup is **refused** (`SecurityConfigurationError`) and requests get 503 |

So production cannot accidentally run open: there is no flag that makes it so.

The legacy `API_KEY` setting survives as *one* server-side credential: it maps to the default tenant with `API_KEY_ROLE` (default `analyst`, least privilege that can still work), not to admin.

### Public endpoints

`GET /` and `GET /health` are public because orchestrator probes carry no credentials, and they reveal nothing. `GET /enterprise/health` and `GET /enterprise/metrics` (Prometheus) are also unauthenticated; the latter exposes counters only. Put them behind the network boundary if that is not acceptable.

## 5. Authorization

Roles are a server-side table (`ROLE_PERMISSIONS`). A role comes from the credential, is mapped to permissions on the server, and is checked at the route with `require_permission(...)`.

| Permission | viewer | analyst | approver | admin | platform_admin |
|---|:-:|:-:|:-:|:-:|:-:|
| `ontology:read`, `clinical:read`, `metrics:read` | yes | yes | yes | yes | yes |
| `query:execute` (SPARQL, Cypher, natural language) | | yes | yes | yes | yes |
| `agent:run` | | yes | yes | yes | yes |
| `agent:approve` | | | yes | yes | yes |
| `agent:eval` | | yes | | yes | yes |
| `graph:write` (load the projection, sync embeddings) | | | | yes | yes |
| `ontology:write`, `workflow:run`, `admin:*` (own tenant) | | | | yes | yes |
| `platform:admin` (create tenants, see all tenants) | | | | | yes |

Suchismita (`admin`) may load the graph; her read-only colleague may not, whatever headers they send. A role the server does not know gets `viewer`.

`X-Role` has no effect. If it disagrees with the granted role, the request still runs with the granted role and a warning is logged (`ignored untrusted X-Role header 'admin' from reader`). `RBAC_ENABLED=false` works only in development; elsewhere it is ignored and authorization stays on.

## 6. Tenancy

The tenant is a property of the identity. Tracing it through a request:

```
request ─▶ authentication ─▶ Identity.tenant_id ─▶ require_tenant ─▶ service ─▶ query
   │                              ▲                     │
   │  X-Tenant-ID / ?tenant_id ───┘ only compared;       └─ 403 if it names a different tenant
   │                                 never selected
```

* `require_tenant` returns the caller's own tenant. A request that *names another tenant* (header or query parameter) is refused with 403 and logged, so a forged or confused client fails loudly instead of silently reading its own data. Naming your own tenant is harmless.
* An identity whose tenant is unknown or deactivated gets 403.
* **Where tenant filtering must occur**, and does:

| Resource | Filter |
|---|---|
| Ontology catalog and by-id reads, publish, activate | `tenant in ontology.tenant_ids`, otherwise 404 (indistinguishable from "does not exist") |
| Tenant catalog | A tenant sees only itself; only `platform:admin` sees all or creates tenants |
| Jobs (`/jobs`, `/agent/jobs`, `/enterprise/jobs`) | A job belongs to the tenant that started it; another tenant's job is a 404 |
| Workflows | The body's `tenant_id` is overwritten with the caller's |
| Agent threads (`/agent/state`, `/agent/resume`) | The checkpoint's tenant must match the caller's |
| Agent memory, documents, cost | Queries carry `tenant_id` from `require_tenant` |

* **What is not isolated (be honest about it).** The clinical graph and the OWL file are **shared** by all tenants of one deployment: Neo4j Community has a single database, and the ontology is one file. Tenant isolation covers the catalog, jobs, documents, agent memory and cost, not the shared clinical data. Isolating clinical data per tenant needs a database per tenant (Neo4j Enterprise) or an `iri`-level tenant property enforced in every query. The `clinical:read` permission is the gate today. This is the biggest tenancy limitation.

## 7. Query safety

The principle: **prevent writes; do not try to detect every malicious write.** A blocklist loses to the first keyword nobody listed. So the layers are ordered by strength:

1. **The database refuses.** User and LLM Cypher runs in a *read transaction on a READ-access session* (`execute_read`, `default_access_mode=READ_ACCESS`, with a transaction timeout). A `DELETE` that reaches the server is rejected by the server. The application has no write-capable call on this path (a test inspects the source for `session.run`, `execute_write`).
2. **The server allows only the procedures we need.** `docker_compose.yaml` sets `dbms.security.procedures.allowlist` to the four read-only procedures the application uses. APOC is **not installed** and nothing in the application uses it (a test enforces both). A query that somehow slipped through still cannot call `dbms.*` or `apoc.*`.
3. **A structural allowlist** (`core/cypher_policy.py`) refuses before anything is sent:
   * every Cypher *reserved word* must be on a short read-only list (`MATCH`, `WHERE`, `RETURN`, ...). `CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, `CALL`, `LOAD`, `FOREACH`, `USE`, `SHOW`, ... are not on it;
   * every *function call* must be on a function allowlist, which excludes any namespaced call (`apoc.x()`, `db.x()`);
   * comments, `;`, control characters and non-ASCII outside string literals are refused. A checker and the real lexer must agree on where text ends; where they might not, the policy **fails closed** (this also refuses a string literal that contains `;` or `//`: a deliberate cost);
   * traversals need an upper bound of at most 6 (no `[*]`); no `$parameters`; at most 5000 characters.
   Names such as labels, variables and properties are free (`n.set`, `:Set` are fine), because they cannot execute anything.
4. **Schema validation** (labels, relationship types, properties must exist in the ontology) and a **`LIMIT`** are applied as before.
5. **SPARQL** is checked on the *parsed query*, not its text: it must be a `SELECT`, with no `FROM`/`FROM NAMED` (which would make the server fetch a caller-chosen document) and no `SERVICE` (which would send bindings to a caller-chosen URL). Update forms never parse as queries. A lookalike such as `rdfs:subClassOf` is no longer mistaken for an unknown ontology term.
6. **No injection by construction elsewhere:** projection labels and relationship types come from the validated ontology (`^[A-Za-z][A-Za-z0-9_]*$`), and every data value is a query parameter (see [semantic-authority-and-graph-projection.md](semantic-authority-and-graph-projection.md)).

Honest note on layer 1: the READ-access guarantee is enforced by the Neo4j server for a standalone instance as documented, and is the design's central control. It is exercised in the tests with a recording driver (the session mode and the transaction type), **not against a live Neo4j server in this repository**. A restricted database *user* would be a further layer, but needs Enterprise Edition role-based access control, which Community Edition lacks.

## 8. Destructive operations

* `POST /neo4j/seed-demo` **does not exist** (removed earlier because it ran `MATCH (n) DETACH DELETE n`). A test asserts there is no seed/reset/wipe/clear route in development **or** production, even for an authenticated admin.
* Demo data is loaded only by `scripts/seed_neo4j_demo.py --yes`, and only if `ENVIRONMENT` is a development value **and** `ALLOW_DEMO_SEED=true`. In production it refuses with exit code 2 before connecting to anything; the library function refuses too.
* The projection load (`POST /neo4j/load`) needs `graph:write`, validates against SHACL, and is scoped to the projection labels (`Resource`, `OntologyClass`, `ProjectionMeta`), so it cannot delete agent memory, documents or embeddings. The optional projection reset (`--reset-projection`) needs the development environment plus `ALLOW_PROJECTION_RESET=true` and is likewise scoped.
* Destructive work is never implicit: no endpoint, startup hook or import deletes anything.

## 9. Security tests

`tests/test_security_architecture.py` covers, for the cast above:

| Concern | Tests |
|---|---|
| Authentication | anonymous and unknown keys are 401 on 11 endpoints; bearer and header both work; hashes only; legacy key is least privilege |
| Forged `X-Role` | a viewer sending `X-Role: admin` cannot load the graph, sync embeddings or create tenants; the header cannot demote an admin either; the forgery is logged |
| Forged `X-Tenant-ID` | header and query forms refused with 403, also on agent and document endpoints; own tenant harmless; unknown and inactive tenants locked out |
| Cross-tenant access | ontology by id (404), publish/activate (404), tenant catalog, jobs (404), workflow body override |
| Unauthorized write | viewers and analysts get 403 on five write endpoints; authorization runs before any work |
| Cypher injection | ten payloads (stacked statements, comments, homoglyphs, parameter smuggling, trailing writes) refused by policy and endpoint |
| Procedure invocation | eleven forms (`CALL`, `apoc.*`, `dbms.*`, subqueries, `LOAD CSV`, `USE`, `SHOW`) refused |
| Production seed endpoint | no route in any environment; refusal in production even when enabled; the script exits 2 |
| Destructive operation | read-only session and transaction proven with a recording driver; writes never reach the driver; server procedure allowlist present; no APOC |
| Startup | production without credentials refuses to start and serves 503; development-open announces itself |

Run them with `pytest tests/test_security_architecture.py`.

## 10. Known limitations

* **Only API-key authentication exists.** No OIDC/JWT, SSO, key expiry, rotation tooling, or per-key rate limiting. The `Authenticator` interface is the extension point.
* **A leaked key is a leaked identity.** Keys are bearer secrets; use TLS (not provided by this application) and rotate by removing and re-adding the credential.
* **The clinical graph and OWL file are shared across tenants** (section 6).
* **Credentials are read from a file and the tenant registry is in memory.** Tenants created at runtime are lost on restart and are not shared between replicas; the credential file must be distributed to every replica.
* **The Cypher policy is token-level, not a full parser.** It is deliberately a second layer; the read-only transaction is the control that does not depend on parsing.
* **Neo4j Community has no database users or roles**, so there is no restricted database user; the READ-access transaction and the procedure allowlist stand in for it. Not exercised against a live server here.
* **Public probes and Prometheus metrics** are unauthenticated.
* **Rate limits are per process.**
* **Audit logging** is application logging (who was refused and why), not a tamper-proof audit trail.
* **Prompt injection of the LLM** is handled by treating its output as untrusted query text (the layers above), not by trying to stop the injection.
