"""Composition root: which service implements what.

The CORE getters (ontology, SHACL validator) import only core modules. The getters that need the LLM
stack or the Neo4j driver import their service inside the function, so importing this module (and
therefore the core routers) works without openai, langchain or a Neo4j server. See
docs/core-vs-ai-architecture.md.
"""

import os
from functools import lru_cache

from services.load_ontology import HealthcareOntology

from core.config import get_settings
from core.shacl_validator import ShaclValidator


def _resolve_owl_path():
    """The configured dataset: schema + sample data (see core/dataset.py)."""
    from core.dataset import Dataset

    return Dataset.default()


@lru_cache
def get_ontology() -> HealthcareOntology:
    return HealthcareOntology(owl_file=_resolve_owl_path())


@lru_cache
def get_sparql_generator():  # ADVANCED: natural language -> SPARQL (needs the LLM stack)
    from services.sparql_generator import SparqlGenerator

    settings = get_settings()
    return SparqlGenerator(get_ontology(), model_name=settings["llm_model"])


@lru_cache
def get_sparql_to_cypher():  # needs the neo4j driver, not an LLM
    from services.sparql_to_cypher import SparqlToCypher

    return SparqlToCypher()


@lru_cache
def get_cypher_generator():  # ADVANCED: natural language -> Cypher (needs the LLM stack)
    from services.cypher_generator import CypherGenerator

    settings = get_settings()
    return CypherGenerator(get_ontology(), model_name=settings["llm_model"])


@lru_cache
def get_neo4j_exporter():  # needs the neo4j driver
    from services.neo4j_exporter import Neo4jExporter

    # The projection reads the authoritative RDF file directly (not the Owlready2 object model)
    # and is gated by the SHACL shapes.
    return Neo4jExporter(owl_file=_resolve_owl_path(), validator=get_shacl_validator())


@lru_cache
def get_embedding_service():  # ADVANCED: embeddings (needs openai and Neo4j)
    from services.embedding_service import EmbeddingService

    settings = get_settings()
    return EmbeddingService(
        ontology_path=_resolve_owl_path(),
        embedding_model=settings["embedding_model"],
    )


@lru_cache
def get_shacl_validator() -> ShaclValidator:
    settings = get_settings()
    from core.shacl_loader import ShaclLoader

    return ShaclValidator(
        loader=ShaclLoader(shapes_dir=settings["shapes_dir"]),
        owl_file=_resolve_owl_path(),
        validation_mode=settings["shacl_validation_mode"],
        data_dir=settings["data_dir"],
    )
