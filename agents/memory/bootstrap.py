"""Bootstrap starter procedures when the graph is empty."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from enterprise.lexical_memory import tokens_for_learning

logger = logging.getLogger("healthcare_ontology.agent")

_STARTER_PROCEDURES: list[dict[str, Any]] = [
    {
        "name": "patients_diabetes",
        "query_type": "cypher",
        "template_query": (
            "MATCH (p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis) "
            "WHERE toLower(d.diagnosisName) CONTAINS 'diabetes' "
            "RETURN p.name AS patient, d.diagnosisName AS diagnosis LIMIT 50"
        ),
        "question": "Show me all patients diagnosed with diabetes",
        "concepts": ["Patient", "Diagnosis", "DiagnosisDiabetes"],
    },
    {
        "name": "patients_hypertension",
        "query_type": "cypher",
        "template_query": (
            "MATCH (p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis) "
            "WHERE toLower(d.diagnosisName) CONTAINS 'hypertension' "
            "RETURN p.name AS patient, d.diagnosisName AS diagnosis LIMIT 50"
        ),
        "question": "Show me all patients diagnosed with hypertension",
        "concepts": ["Patient", "Diagnosis", "DiagnosisHypertension"],
    },
    {
        "name": "patient_john_diagnosis",
        "query_type": "cypher",
        "template_query": (
            "MATCH (p:Patient {name: 'PatientJohn'})-[:HASDIAGNOSIS]->(d:Diagnosis) "
            "RETURN p.name AS patient, d.diagnosisName AS diagnosis"
        ),
        "question": "What is the patient diagnosis for John Doe",
        "concepts": ["PatientJohn", "Patient", "Diagnosis", "DiagnosisHypertension"],
    },
]


def bootstrap_procedural_memory(*, tenant_id: str = "default") -> dict[str, Any]:
    """Create starter Procedure nodes when none exist for the tenant."""
    from agents.memory.procedural import get_procedural_memory

    store = get_procedural_memory()
    store.ensure_schema()
    try:
        driver = store._connect()
        with driver.session(database=store._database) as session:
            existing = session.run(
                """
                MATCH (p:AgentProcedure)
                WHERE p.tenant_id = $tenant_id OR p.tenant_id = 'global'
                RETURN count(p) AS n
                """,
                tenant_id=tenant_id,
            ).single()
            if existing and int(existing["n"] or 0) > 0:
                return {"created": 0, "skipped": True, "reason": "procedures_exist"}
    except Exception as exc:
        logger.warning("Procedure bootstrap check failed: %s", exc)
        return {"created": 0, "error": str(exc)}

    now = datetime.now(timezone.utc).isoformat()
    created = 0
    try:
        driver = store._connect()
        with driver.session(database=store._database) as session:
            for proc in _STARTER_PROCEDURES:
                keywords = tokens_for_learning(
                    proc["question"],
                    validated_query=proc["template_query"],
                    concept_names=proc.get("concepts"),
                )
                session.run(
                    """
                    CREATE (p:AgentProcedure {
                        procedure_id: $procedure_id,
                        tenant_id: $tenant_id,
                        name: $name,
                        query_type: $query_type,
                        intent_keywords: $intent_keywords,
                        template_query: $template_query,
                        plan_steps_json: '[]',
                        success_count: 3,
                        avg_confidence: 0.85,
                        created_at: $now,
                        last_used_at: $now
                    })
                    """,
                    procedure_id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    name=proc["name"],
                    query_type=proc["query_type"],
                    intent_keywords=json.dumps(keywords),
                    template_query=proc["template_query"],
                    now=now,
                )
                created += 1
    except Exception as exc:
        logger.warning("Procedure bootstrap failed: %s", exc)
        return {"created": created, "error": str(exc)}

    return {"created": created, "skipped": False}
