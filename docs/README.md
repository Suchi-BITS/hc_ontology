# Documentation index

Start with [reader-journey.md](reader-journey.md): fourteen steps from the hospital's questions to the optional AI layer, using the project's real structure. Everything else is reference for one step or one concern.

## The book path

| Step | Read | Then run |
|---|---|---|
| Orientation | [reader-journey.md](reader-journey.md), [architecture-diagrams.md](architecture-diagrams.md) | `python scripts/dev.py quickstart` |
| Chapter by chapter, with exercises | [book-chapter-mapping.md](book-chapter-mapping.md) | exercises E01 to E14 |
| 01 Domain, 08 SPARQL | [competency-questions.md](competency-questions.md) | `python scripts/build_cq_doc.py --check` |
| 02 to 06 Vocabulary, taxonomy, ontology, RDF, OWL | [ontology-engineering.md](ontology-engineering.md), [schema-and-sample-data.md](schema-and-sample-data.md) | `python scripts/generate_hc_ontology.py --output out.ttl` |
| 05, 09, 10 Data and the knowledge graph | [sample-data-and-semantic-mapping.md](sample-data-and-semantic-mapping.md), [semantic-authority-and-graph-projection.md](semantic-authority-and-graph-projection.md), [neo4j-desktop.md](neo4j-desktop.md) | `python scripts/validate.py`, then `python scripts/dev.py doctor --neo4j` |
| 10 Validation | [testing-strategy.md](testing-strategy.md) | `python scripts/dev.py test` |
| 11 API | [security-policy.md](security-policy.md), [security-architecture.md](security-architecture.md), [security-and-configuration.md](security-and-configuration.md) | `python scripts/dev.py serve` |
| 13 to 14 The optional AI layer | [core-vs-ai-architecture.md](core-vs-ai-architecture.md) | `ENABLE_AI_LAYER=false` to leave it out |

## Lessons and reference

| Document | What it is for |
|---|---|
| [anti-patterns.md](anti-patterns.md) | Eight mistakes this project made or avoided, each with its evidence |
| [troubleshooting.md](troubleshooting.md) | Symptom, cause, fix: setup, RDF, SHACL, SPARQL, Neo4j, Docker, API, environment |
| [reproducibility.md](reproducibility.md) | How a fresh clone reaches a working state, and the pinned versions |
| [fresh-clone-verification.md](fresh-clone-verification.md) | What was actually verified from a pristine clone, and what was not |
| [AI_LAYER_LIVE_VERIFICATION.md](AI_LAYER_LIVE_VERIFICATION.md) | The optional AI layer run for real (OpenAI, embeddings, retrieval, the agent, approval, abstention, outages): verdicts per area, four defects found and fixed |
| [NEO4J_DESKTOP_LIVE_VERIFICATION.md](NEO4J_DESKTOP_LIVE_VERIFICATION.md) | The live run against a real Neo4j Desktop database: what was executed, what it showed, the bugs it found |

## Older material

| Document | Note |
|---|---|
| [UDEMY_GRAPH_ALGORITHMS_SCRIPT.md](UDEMY_GRAPH_ALGORITHMS_SCRIPT.md), [UDEMY_REASONING_SCRIPT.md](UDEMY_REASONING_SCRIPT.md), [YOUTUBE_MEMORY_LAYER_SCRIPT.md](YOUTUBE_MEMORY_LAYER_SCRIPT.md) | Video scripts from the course this repository began as. They predate the redesign and are not kept in step with it: where they disagree with the documents above, the documents above are right |
| [../system_design.md](../system_design.md), [../graph_schema_design.md](../graph_schema_design.md) | Design notes. Updated for the authentication and tenancy changes only |

## Conventions

Documents state what was verified and what was not. A claim that depends on Docker, Neo4j, an OpenAI key or a platform other than the one it was written on says so. Commands are run from the project root. Every document that names a repository path or a test is checked by `tests/test_book_exercises.py`, so a renamed file or test fails the build instead of leaving a dead reference.
