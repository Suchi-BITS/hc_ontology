"""Verify demo individuals in the ontology and export them to Neo4j."""

from __future__ import annotations

import logging
from typing import Any

from services.load_ontology import HealthcareOntology
from services.neo4j_exporter import Neo4jExporter

logger = logging.getLogger("healthcare_ontology.seed")


# Individuals the demo queries rely on. They ship in the generated ontology
# (scripts/generate_hc_ontology.py); this module no longer edits the OWL file.
REQUIRED_DEMO_INDIVIDUALS = (
    "PatientAlice",
    "PatientBob",
    "DiagnosisDiabetesAlice",
    "DiagnosisDiabetesBob",
    "Metformin",
    "InsulinGlargine",
    "PrescriptionDiabetesAlice",
    "PrescriptionDiabetesBob",
    "PrescriptionHypertensionJohn",
)


def seed_demo_ontology(hc: HealthcareOntology) -> dict[str, Any]:
    """Verify that the demo individuals exist in the loaded ontology.

    Earlier versions created demo individuals here and rewrote the OWL file,
    which let a data-entry shortcut (metformin created as an Analgesic) silently
    corrupt the model. Demo data now lives in the generator; this only checks.
    """
    onto = hc.onto
    missing = [n for n in REQUIRED_DEMO_INDIVIDUALS if getattr(onto, n, None) is None]
    if missing:
        raise RuntimeError(
            "Demo individuals missing from the ontology: "
            + ", ".join(missing)
            + ". Regenerate it with `python scripts/generate_hc_ontology.py`."
        )
    return {"owl_saved": False, "entities_present": list(REQUIRED_DEMO_INDIVIDUALS)}


def verify_source_data() -> None:
    """Fail before touching the graph if the CSV sample data breaks the data contract."""
    from services import sample_data

    sample_data.require_valid(sample_data.load_dataset(), sample_data.load_drug_reference(), source_dir=sample_data.SOURCE_DIR)


def seed_demo_ontology_and_neo4j() -> dict[str, Any]:
    """Development helper: verify demo data in the ontology, then synchronize the projection.

    * Validates first, always: the source CSVs against the data contract, then the RDF against SHACL
      (inside the exporter). There is no switch to skip either; invalid data is never loaded.
    * Reads the authoritative RDF; never edits it.
    * Never clears the database. The projection sync is scoped to the projection labels,
      so agent memory, documents and embeddings are untouched.
    * Not exposed over HTTP. Run it with scripts/seed_neo4j_demo.py.
    """
    from agents.memory.bootstrap import bootstrap_procedural_memory
    from core.dependencies import get_shacl_validator
    from core.graph_domains import require_demo_allowed

    require_demo_allowed()  # development only, explicitly enabled; refuses in production

    verify_source_data()
    hc = HealthcareOntology()
    owl_result = seed_demo_ontology(hc)
    exporter = Neo4jExporter(owl_file=hc.owl_file, validator=get_shacl_validator())
    try:
        projection_result = exporter.sync(validate=True)
    finally:
        exporter.close()
    proc_result = bootstrap_procedural_memory()
    return {
        "status": "success",
        "owl": owl_result,
        "projection": projection_result,
        "procedures": proc_result,
        "hint_queries": [
            "MATCH (p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis) RETURN p.name, d.diagnosisName LIMIT 25",
            "MATCH (p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis {diagnosisName: 'Diabetes'}) RETURN p.name",
            "MATCH (p:Patient)-[:HASCONDITION]->(c:Condition) RETURN p.name, c.diagnosisName LIMIT 25",
            "MATCH (p:Patient)<-[:PRESCRIBEDFOR]-(rx:Prescription)-[:CONTAINSMEDICATION]->(m) RETURN p.name, m.medicationName",
        ],
    }
