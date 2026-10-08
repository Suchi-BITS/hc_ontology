# Troubleshooting

Organised by where the symptom shows up. Each entry is *symptom -> cause -> fix*, and most come from a failure that actually happened while building this project, so they are the ones you are likely to meet. Start with the one command that diagnoses most of them:

```bash
python scripts/dev.py doctor
```

It reports Python, the virtualenv, dependencies, `.env`, Java, Docker and Neo4j, with a fix for each failure. Nothing it prints contains a credential value.

## 1. Dependency setup

| Symptom | Cause | Fix |
|---|---|---|
| `pip` retries, then `CERTIFICATE_VERIFY_FAILED` | A proxy or antivirus re-signs HTTPS traffic with a CA that Python does not trust | `python scripts/dev.py setup` retries with the operating-system certificate store; only that failure triggers the fallback, nothing else weakens TLS. See [reproducibility.md](reproducibility.md) |
| `No module named langchain_openai` (or any package) right after installing | Wrong interpreter: `pip` and `python` are different environments | Use `python -m pip` and `python -m uvicorn`; print `python -c "import sys; print(sys.executable)"` and compare |
| `ResolutionImpossible` with `-c constraints.txt` | The index could not be reached, so pip saw no candidate versions, and reported it as a conflict | Fix the network/TLS issue above; do not delete the constraints file |
| You do not want the LLM stack | It is optional | `pip install -r requirements-core.txt -c constraints.txt`, or set `ENABLE_AI_LAYER=false`. See [core-vs-ai-architecture.md](core-vs-ai-architecture.md) |
| 6 tests are skipped | No Java, so the OWL reasoner tests cannot run | Install a JRE (`java -version`); the skip is deliberate, not a failure |
| Python 3.12+ warning | Only 3.11 is verified | It is a warning, not an error; report problems against 3.11 first |

## 2. RDF parsing

| Symptom | Cause | Fix |
|---|---|---|
| `Failed to load RDF data` / `Data file not found` | A relative path resolved against the wrong directory, or the wrong format | Pass an absolute path or a path relative to the project root; `.ttl` is read as Turtle, `.owl`/`.rdf` as RDF/XML (`core/shacl_validator.py`, `_guess_format`) |
| A Turtle fixture parses but nothing matches your query | Typed vs plain literals: `"E11"` and `"E11"^^xsd:string` are different terms to a literal comparison | Bind parameters with their datatype (`Literal("E11", datatype=XSD.string)`); the `/sparql` endpoint normalises string literals for you |
| `the committed schema differs from the generator output` or `the committed sample data differs ...` | The generator, `reference_vocab.py` or a CSV changed and the committed Turtle was not regenerated | `python scripts/generate_hc_ontology.py` (schema) and/or `python scripts/generate_sample_data.py` (data), review the diff, commit |
| `the schema contains instance data; nothing was written` | An individual that is not a vocabulary concept entered the schema module | Instances belong in `data/source/*.csv` and `scripts/generate_sample_data.py`; see [schema-and-sample-data.md](schema-and-sample-data.md) |
| SHACL fails on `data/sample_data.ttl` when validated alone | The shapes need the schema's class hierarchy to recognise the data | Validate the combined dataset: `python scripts/validate.py` |
| `RDF file not found: ...sample_data.ttl` | The data has not been generated, or `SAMPLE_DATA_FILE` points elsewhere | `python scripts/generate_sample_data.py`, or set `SAMPLE_DATA_FILE=` to run on the schema alone |
| `sample data violates the data contract (N problem(s))` | A CSV breaks a rule; the message lists every problem with file, row and code | Fix the row named in the message; codes are described in [sample-data-and-semantic-mapping.md](sample-data-and-semantic-mapping.md) |
| `MISSING_COLUMN` / `UNKNOWN_COLUMN` | A header typo | Compare with `SCHEMA` in `services/sample_data.py` |
| Two graphs look the same but a test says they differ | RDF graph equality is not text equality: blank-node labels and ordering vary | Compare with `rdflib.compare.isomorphic`, as `scripts/validate.py` does |

## 3. SHACL validation

| Symptom | Cause | Fix |
|---|---|---|
| `conforms=False` on a fixture you expected to pass | Some fixtures check one shape and are incomplete against all of them (for example `valid_patient.ttl` omits a doctor on a diagnosis, so the full set reports violations) | Validate against the shape you mean: `validate_data_file(path, shape_files=["patient_shapes.ttl"])`, as `tests/test_patient_shapes.py` does. `valid_encounter.ttl` and `valid_doctor.ttl` conform to all shapes |
| `conforms=False` only because of warnings | Strict mode (`SHACL_VALIDATION_MODE=strict`) makes warnings fail | Use the default `warn` mode, or fix the warnings |
| A relationship to the wrong kind of thing passes | Someone enabled RDFS inference in the validator, which types the target from `rdfs:range` | Keep `inference="none"`; see anti-pattern 5 in [anti-patterns.md](anti-patterns.md) |
| A `sh:in` or `sh:hasValue` that "should" match does not | Datatype mismatch: shape literals are `xsd:string`, the data has a plain or language-tagged literal | Write literals with `^^xsd:string` in shapes and data |
| `encounterStart must be a single xsd:dateTime with a time zone` | A datetime without an offset | Add `+00:00` (or the real offset): `2026-03-01T09:30:00+00:00` |
| Info-level messages in an otherwise passing run | Two lab results have no `hasCode`; "prefer" rules are Info on purpose | Nothing to fix; add a LOINC `CodeConcept` if you want them gone |

## 4. SPARQL

| Symptom | Cause | Fix |
|---|---|---|
| `only SELECT queries are allowed` | `/sparql` accepts SELECT only (no ASK, CONSTRUCT, UPDATE) | Run `cq19` and `cq20` with rdflib directly, as `tests/test_sparql_competency.py` does; the restriction is deliberate API hardening |
| `SERVICE (federated queries) is not allowed`, `FROM / FROM NAMED ... not allowed` | The query validator blocks outbound and dataset-switching constructs | Remove them; query the one graph the server holds |
| Results stop at 200 rows | The server injects `LIMIT 200` when you give none | Add your own `LIMIT` |
| Empty result where you expect rows | (1) literal datatype (section 2); (2) you asked for `?x a hc:Person` but nobody is *asserted* a bare Person; (3) the data genuinely has no such fact | (2): follow the hierarchy with `rdfs:subClassOf*` (CQ14) or apply the closure (CQ21); (3): check the source CSV |
| A query uses a name that "should exist" and returns a validation error | It is not in the ontology; queries may only use defined terms | Check spelling against `ontology/healthcare_schema.ttl`; `tests/test_sparql_competency.py` enforces this for the shipped queries |
| `UNKNOWN` prefix | A query was saved without its `PREFIX hc:` line | `PREFIX hc: <http://example.org/healthcare-hospital.owl#>` |

## 5. Neo4j

| Symptom | Cause | Fix |
|---|---|---|
| `NEO4J_PASSWORD is not set` | Required only when connecting | Copy `.env.example` to `.env` and set the password of your Neo4j Desktop database (or let `python scripts/dev.py setup` generate one for the optional Docker Neo4j). The value is never printed |
| `python scripts/dev.py doctor --neo4j` says `UNREACHABLE` or `Neo4j is not running or is not reachable` | Neo4j Desktop's database is stopped, or `NEO4J_URI` / credentials in `.env` do not match it | Start the database in Neo4j Desktop, then compare `NEO4J_URI` (default `bolt://localhost:7687`), `NEO4J_USERNAME` and `NEO4J_PASSWORD`. The command changes nothing and never starts or creates a database |
| `database 'x' does not exist` | `NEO4J_DATABASE` names a database that is not in this DBMS | `verify-neo4j` lists the databases it found. Use one of them (the default is `neo4j`), or create one in Neo4j Desktop yourself |
| `REFUSED (nothing was written): database 'x' already holds N node(s) outside this project's graph domains` | The target database contains nodes from an older exporter or another application, and loading would mix two representations of the same entities | Set `NEO4J_DATABASE` to an **empty** database. Only if mixing is intended: `python scripts/load_graph.py --allow-foreign-data`. The project never deletes the existing nodes for you |
| `verify-neo4j --projection` reports differences | The database is stale or was changed by hand | `python scripts/dev.py load` rebuilds it from the RDF (the authority); it only touches its own labels |
| `/execute-cypher` answers `503 Query object is only supported for session.run` | An old checkout: the timeout was attached to the query object | Update; the timeout is now on the transaction (fixed by the live Neo4j Desktop verification) |
| `504 Cypher query exceeded the N-second limit` | The database terminated a long query (`QUERY_TIMEOUT_SECONDS`) | Make the query cheaper or raise the limit; the termination is by the server, a little after the limit |
| Calls fail after about five seconds | The server is unreachable; the driver is configured to give up quickly instead of hanging | `python scripts/dev.py up` (needs Docker) or start your own Neo4j 5.x and set `NEO4J_URI` |
| `500` on `/neo4j/health` | `NEO4J_DATABASE` names an instance, not a database | Use the database name (`neo4j` by default) |
| `Neo4j authentication failure` | The password in `.env` differs from the one the data volume was created with | `python scripts/dev.py down --volumes` (deletes the **development** database), then `up` |
| `/neo4j/load` or `load` refuses | The SHACL gate found a violation in the RDF | Run `python scripts/validate.py`; fix the data, not the gate |
| Reset refused | Resetting is development-only and needs an explicit flag | See `docs/security-and-configuration.md`; this refusal protects agent memory and documents sharing the same database |
| `MATCH (p:Person)` returns nothing | The projection has not been loaded, or an old export is in the database | `python scripts/dev.py load`. Without a server you can still inspect it: `python scripts/validate.py` step 4 |

Nothing in the Neo4j column was exercised against a live server in the verification environment; see [fresh-clone-verification.md](fresh-clone-verification.md).

## 6. Docker

| Symptom | Cause | Fix |
|---|---|---|
| `Docker daemon: installed but not running` (doctor) | Docker Desktop is not started | Start it, then `python scripts/dev.py up` |
| `port is already allocated` (7474, 7687 or 8000) | Another process holds the port | Change `NEO4J_HTTP_PORT`, `NEO4J_BOLT_PORT` or `API_PORT` in `.env` |
| Compose errors about YAML | A value with `: ` must be quoted | `docker compose -f docker_compose.yaml config` prints the parsed file and the line |
| The API container cannot reach Neo4j | It must use the service name, not `localhost` | Inside compose the URI is `bolt://neo4j:7687` (already set) |
| The image contains secrets or a venv | It should not | `.dockerignore` excludes `.env`, credential files and `venv/`; `tests/test_devtools.py` checks it |

## 7. API

| Symptom | Cause | Fix |
|---|---|---|
| `WinError 10013` or `address already in use` | Port 8000 is busy | `python -m uvicorn api:app --port 8001` |
| `401` | No or invalid credential | `python scripts/dev.py credential add --user <you> --tenant <tenant> --role admin`; send `X-API-Key` or `Authorization: Bearer` |
| `403` although you sent `X-Role: admin` | Role headers are not trusted by design | The role comes from the server-side credential; see [security-architecture.md](security-architecture.md) |
| `403` on a tenant you named | You asked for a tenant that is not yours | Omit the tenant, or use a credential for that tenant |
| `404` on `/agent/...`, `/enterprise/...`, `/embedding/...`, `/documents/...` | The AI layer is off (`ENABLE_AI_LAYER=false`) or its libraries are not installed (see the startup log) | Install `requirements.txt` and set `ENABLE_AI_LAYER=true` |
| `503` on `/llm-query`, `/nl-query`, `/nl-to-cypher` | The AI stack is not installed, or the OpenAI key is missing | Same as above; check `OPENAI_API_KEY` |
| `{"detail":"Connection error."}` | HTTPS to OpenAI failed (proxy/TLS), **or** the endpoint is simply unreachable (the message is the same) | check `OPENAI_BASE_URL` and the network first; then `python -m pip install truststore certifi` and restart the API |
| The agent answers `refused` with `no_evidence` | An ontology-only question whose best retrieved concept scored below `AGENT_ONTOLOGY_MIN_RELEVANCE` (default 0.30): the question is probably not about the ontology | Rephrase, or lower the floor if you judge the retrieval to be relevant |
| Prompts and answers appear in LangSmith | `LANGCHAIN_TRACING_V2=true` with a key in `.env` sends every agent prompt and answer to LangSmith | Set it to `false` unless you intend that |
| `429` | The rate limiter | Wait; limits are in `.env.example` |
| Natural-language endpoints take minutes | LLM latency | Use the `/async` variants and poll `/jobs/{id}` |

## 8. Environment configuration

| Symptom | Cause | Fix |
|---|---|---|
| The API refuses to start: no credentials | No credentials exist, and open mode is off. An **unset or unknown** `ENVIRONMENT` counts as production | Create one with `credential add`; or, locally only, set `ENVIRONMENT=development` and `ALLOW_OPEN_DEVELOPMENT_MODE=true` (an older `.env` has the first but not the second). See [security-policy.md](security-policy.md) |
| `ALLOW_OPEN_DEVELOPMENT_MODE=true` has no effect | `ENVIRONMENT` is production (or misspelt, for example `develpment`); the opt-in is ignored there by design | Fix `ENVIRONMENT`, or create a credential |
| The `api` container exits straight away | Compose runs the API in production mode and `API_KEY` is empty | `export API_KEY=...` and `up` again; or, for local work only, add `-f docker_compose.dev.yaml` |
| `504` from `/sparql` with `exceeded the N-second limit and was terminated` | The query ran longer than `SPARQL_QUERY_TIMEOUT_SECONDS`; its worker process was killed | Make the query cheaper (add selective patterns, `LIMIT`, avoid unconnected patterns), or raise the limit (maximum 300) |
| Startup error `SPARQL_QUERY_TIMEOUT_SECONDS must be a number between 0.1 and 300` | An invalid value; there is no unlimited setting | Use a number in range, or remove the variable for the default of 15 |
| `503` `all SPARQL workers were busy` | Every worker was running slow queries for the whole limit | Raise `SPARQL_WORKERS` (maximum 8) or fix the slow queries |
| "Missing configuration" warnings at startup | A setting needed by a feature is unset | Read the named setting in `.env.example`; warnings never print values |
| A new environment variable is read by the code but undocumented | The suite fails | Add it to `.env.example`; `tests/test_consistency.py` enforces that every variable the code reads is documented |
| A change to `.env` has no effect | The server reads it at startup | Restart; stop uvicorn fully |
| `OPENAI_API_KEY=<your-openai-api-key>` is treated as set | It is a placeholder | The doctor recognises placeholders; replace it or leave the AI layer off |

## When you are stuck

1. `python scripts/dev.py doctor`
2. `python scripts/validate.py` (data contract, parse, generator, SHACL, projection)
3. `python scripts/dev.py test` (the suite names the failing layer by marker: `pytest -m shacl`, `-m sparql`, `-m api`)

If a failure matches none of the above, the most informative thing to capture is the first line of the error, `python --version`, and the output of `doctor`.
