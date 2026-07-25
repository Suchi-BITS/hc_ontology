import os
from functools import lru_cache

from services.cypher_generator import CypherGenerator
from services.embedding_service import EmbeddingService
from services.load_ontology import HealthcareOntology
from services.sparql_generator import SparqlGenerator
from services.neo4j_exporter import Neo4jExporter
from services.sparql_to_cypher import SparqlToCypher

from core.config import get_settings
from core.shacl_validator import ShaclValidator


def _resolve_owl_path() -> str:
    settings = get_settings()
    owl_file = settings["owl_file"]
    if not os.path.isfile(owl_file) and os.path.isfile("healthcare_ontology.owl"):
        return "healthcare_ontology.owl"
    return owl_file


@lru_cache
def get_ontology() -> HealthcareOntology:
    return HealthcareOntology(owl_file=_resolve_owl_path())


@lru_cache
def get_sparql_generator() -> SparqlGenerator:
    settings = get_settings()
    return SparqlGenerator(get_ontology(), model_name=settings["ollama_model"])


@lru_cache
def get_sparql_to_cypher() -> SparqlToCypher:
    return SparqlToCypher()


@lru_cache
def get_cypher_generator() -> CypherGenerator:
    settings = get_settings()
    return CypherGenerator(get_ontology(), model_name=settings["ollama_model"])


@lru_cache
def get_neo4j_exporter() -> Neo4jExporter:
    return Neo4jExporter(get_ontology())


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService(ontology_path=_resolve_owl_path())


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
