"""The test pyramid: which level(s) each test module belongs to.

One place to classify tests. ``conftest.py`` turns this into pytest markers, so you can run a
level on its own, for example ``pytest -m shacl`` or ``pytest -m "not reasoner and not e2e"``.
``tests/test_strategy.py`` fails if a test module is missing from this table.
"""

LEVELS = {
    # fast, no files or services: pure functions and small classes
    "unit": [
        "test_query_validation", "test_lexical_memory", "test_memory", "test_memory_debug",
        "test_memory_preview", "test_governance", "test_enterprise", "test_agent_graph",
        "test_cypher_generation", "test_devtools",
    ],
    # the ontology artifact: classes, properties, inverses, datatypes, labels, anti-patterns, reasoning
    "ontology": ["test_ontology"],
    # RDF artifact checks: parsing, literal forms, generator output equals the committed file
    "rdf": ["test_ontology"],
    # shapes: a valid example and an invalid example for each rule
    "shacl": [
        "test_shape_contracts", "test_clinical_shapes", "test_doctor_shapes", "test_patient_shapes",
        "test_shacl_validation",
    ],
    # competency questions as executable queries
    "sparql": ["test_sparql_competency"],
    # RDF -> property graph: semantics, determinism, oracle, writer plan, guards
    "projection": ["test_graph_projection", "test_projection_oracle", "test_neo4j_sync"],
    # HTTP surface: auth, RBAC, tenancy, input, safe queries, errors
    "api": ["test_api", "test_api_validation", "test_api_boundaries"],
    # several components together, still in-process
    "integration": ["test_ontology_service", "test_ci_checks", "test_docs_claims", "test_ai_layer_fixes", "test_neo4j_desktop", "test_semantic_review", "test_schema_and_data", "test_sparql_timeout", "test_security_policy", "test_deployment_hardening", "test_book_exercises", "test_sample_data", "test_architecture_boundaries", "test_audit_regressions", "test_consistency", "test_security_architecture"],
    # the whole pipeline in order
    "e2e": ["test_pipeline_e2e", "test_neo4j_live", "test_ai_live"],
}

DESCRIPTIONS = {
    "unit": "pure logic, no I/O",
    "ontology": "the ontology model and its semantics",
    "rdf": "the RDF artifact and its serialization",
    "shacl": "SHACL shapes: valid and invalid examples",
    "sparql": "competency questions run as SPARQL",
    "projection": "RDF to Neo4j projection logic and writer plan",
    "api": "HTTP boundaries: auth, authorization, input, errors",
    "integration": "components together, in process",
    "e2e": "generator to gate to projection to API",
    "reasoner": "needs Java (OWL reasoner); skipped without it",
}


def levels_for(module_stem: str) -> list[str]:
    return [level for level, modules in LEVELS.items() if module_stem in modules]
