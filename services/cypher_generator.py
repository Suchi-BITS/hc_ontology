# cypher_generator.py
# Natural Language -> Cypher via LangChain + OpenAI (+ validation / repair)

from __future__ import annotations

import logging
import re
import time
from typing import Dict, List

from langchain_core.prompts import PromptTemplate

from core.cypher_validator import CypherQueryValidator
from core.llm import get_chat_llm
from core.metrics import metrics
from core.query_cache import query_cache
from core.query_validator import QueryValidationError

logger = logging.getLogger("healthcare_ontology.query")


class CypherGenerator:
    """
    Natural Language
            ↓
        LangChain
            ↓
      OpenAI
            ↓
         Cypher
            ↓
      CypherQueryValidator
    """

    def __init__(
        self,
        ontology,
        model_name: str = "gpt-4.1-mini",
        explain_fn=None,
    ):
        self.ontology = ontology
        self.explain_fn = explain_fn
        self.model_name = model_name
        self.llm = get_chat_llm(model=model_name, temperature=0)
        self.prompt = PromptTemplate(
            input_variables=[
                "classes",
                "object_properties",
                "data_properties",
                "question",
            ],
            template="""
You are an expert Neo4j Cypher generator for a healthcare ontology graph.

Generate a valid Cypher query ONLY.

Do not explain.
Do not use markdown.
Do not surround with ```cypher.

Graph model:

- The graph is a projection of the RDF ontology. Each individual is a node that carries
  ALL of its classes as labels, including superclasses (a diagnosis is both :Diagnosis and
  :Condition; a doctor is both :Doctor and :Practitioner and :Person).
- Every node has `iri` (its stable identity) and `name` (the display name, the IRI local name).
- Object properties become relationships with UPPERCASE type names
  (e.g. hasDiagnosis -> HASDIAGNOSIS). Inverse and super-property relationships also exist
  (e.g. DIAGNOSISFORPATIENT, HASCONDITION).
- Data properties are node properties with camelCase names and native types
  (dates are Cypher dates). Single-valued properties are scalars (d.diagnosisName = 'Diabetes');
  contact properties (phoneNumber, emailAddress, address, emergencyContact, observationValueText)
  are lists - test them with `'x' IN n.phoneNumber`.
- Specialty, gender, encounter type and medication category are linked concept nodes
  (e.g. (d:Doctor)-[:HASSPECIALTY]->(s:Specialty)), not properties.
- Medications are NOT linked directly to patients. Use Prescription as the bridge:
  (rx:Prescription)-[:PRESCRIBEDFOR]->(p:Patient)
  (rx)-[:CONTAINSMEDICATION]->(m:Medication)

Available node labels (classes):

{classes}

Available relationship types (from object properties):

{object_properties}

Available node properties (from data properties):

{data_properties}

Rules:

1. Use ONLY the labels, relationships, and properties listed above.
2. Return ONLY read queries (MATCH ... RETURN ...).
3. Do NOT use CREATE, MERGE, SET, DELETE, DETACH, REMOVE, DROP, or CALL DBMS.
4. Prefer matching nodes by label and `name` when filtering individuals.
5. Include LIMIT 50 unless the question needs a different bound.
6. RETURN must list at least one expression (e.g. RETURN p.name, d.diagnosisName). Never leave RETURN empty.
7. For patient diagnoses use (p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis), not DIAGNOSISFORPATIENT.
8. Return ONLY the Cypher query.

Question:

{question}

Cypher:
""",
        )

    def get_classes(self) -> List[str]:
        return sorted(cls.name for cls in self.ontology.onto.classes())

    def get_object_properties(self) -> List[str]:
        return sorted(
            prop.name.upper() for prop in self.ontology.onto.object_properties()
        )

    def get_data_properties(self) -> List[str]:
        return sorted(prop.name for prop in self.ontology.onto.data_properties())

    def build_prompt(self, question: str) -> str:
        return self.prompt.format(
            classes="\n".join(f"- {name}" for name in self.get_classes()),
            object_properties="\n".join(
                f"- {name}" for name in self.get_object_properties()
            ),
            data_properties="\n".join(
                f"- {name}" for name in self.get_data_properties()
            ),
            question=question,
        )

    def clean_cypher(self, cypher: str) -> str:
        cypher = cypher.strip()
        cypher = re.sub(r"```cypher", "", cypher, flags=re.IGNORECASE)
        cypher = cypher.replace("```", "").strip()

        match = re.search(
            r"\bMATCH\b.+?\bRETURN\b.+?(?:\nLIMIT\s+\d+)?",
            cypher,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            block = match.group(0)
            lines = [
                line
                for line in block.splitlines()
                if line.strip() and not line.strip().startswith("//")
            ]
            cypher = "\n".join(lines).strip()
        else:
            lines = []
            started = False
            for line in cypher.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("//"):
                    continue
                if re.match(r"^MATCH\b", stripped, re.IGNORECASE):
                    started = True
                if started:
                    lines.append(line)
            cypher = "\n".join(lines).strip()

        return self.normalize_cypher(cypher)

    def normalize_cypher(self, cypher: str) -> str:
        """Repair common LLM mistakes before validation/execution."""
        from core.cypher_repair import repair_cypher

        return repair_cypher(cypher)

    def _build_validator(self) -> CypherQueryValidator:
        from core.config import get_settings

        settings = get_settings()
        return CypherQueryValidator(
            classes=self.get_classes(),
            object_properties=self.get_object_properties(),
            data_properties=self.get_data_properties(),
            default_limit=settings["query_default_limit"],
            timeout_seconds=settings["query_timeout_seconds"],
            explain_fn=self.explain_fn,
        )

    def validate(self, cypher: str):
        validator = self._build_validator()
        result = validator.run_all_checks(cypher)
        if result.valid:
            metrics.incr("cypher_validation_pass")
        else:
            metrics.incr("cypher_validation_fail")
            logger.warning(
                "Cypher validation failed stage=%s error=%s",
                result.stage,
                result.error,
            )
        return result

    def generate(self, question: str) -> str:
        prompt = self.build_prompt(question)
        response = self.llm.invoke(prompt)
        cypher = self.clean_cypher(response.content)
        if not cypher:
            raise ValueError("Model returned an empty Cypher query.")
        return cypher

    def repair(self, question: str, broken_query: str, error: str) -> str:
        repair_prompt = f"""
You generated an invalid Cypher query for a healthcare ontology graph.

Question:
{question}

Broken query:
{broken_query}

Validation error:
{error}

Graph model reminders:
- Medications reach patients through Prescription nodes, not direct edges.
  (rx:Prescription)-[:PRESCRIBEDFOR]->(p:Patient)
  (rx)-[:CONTAINSMEDICATION]->(m:Medication)
- Diagnoses use (p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis).

Available node labels (classes):
{chr(10).join(f"- {name}" for name in self.get_classes())}

Available relationship types (from object properties):
{chr(10).join(f"- {name}" for name in self.get_object_properties())}

Available node properties (from data properties):
{chr(10).join(f"- {name}" for name in self.get_data_properties())}

Return ONLY a read-only MATCH ... RETURN Cypher query.
Use ONLY the labels, relationships, and properties listed above.
Do not explain. Do not repeat these instructions in your answer.
"""
        response = self.llm.invoke(repair_prompt)
        return self.clean_cypher(response.content)

    def generate_and_validate(self, question: str, max_attempts: int = 3) -> Dict:
        cache_key = query_cache.make_key("cypher", question.strip().lower())
        cached = query_cache.get(cache_key)
        if cached is not None:
            metrics.incr("cypher_cache_hit")
            out = dict(cached)
            if out.get("generated_cypher"):
                out["generated_cypher"] = self.normalize_cypher(out["generated_cypher"])
            return {**out, "cached": True}

        metrics.incr("cypher_llm_generate")
        cypher = self.generate(question)
        last = None
        started = time.perf_counter()

        for attempt in range(max_attempts):
            cypher = self.normalize_cypher(cypher)
            last = self.validate(cypher)
            if last.valid:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                payload = {
                    "question": question,
                    "generated_cypher": last.query,
                    "attempts": attempt + 1,
                    "elapsed_ms": elapsed_ms,
                    "cached": False,
                }
                query_cache.set(cache_key, payload)
                logger.info(
                    "NL→Cypher ok attempts=%s elapsed_ms=%s",
                    attempt + 1,
                    elapsed_ms,
                )
                return payload
            logger.info(
                "NL→Cypher repair attempt=%s stage=%s error=%s",
                attempt + 1,
                last.stage,
                last.error,
            )
            cypher = self.repair(question, cypher, last.error or "invalid")

        metrics.incr("cypher_llm_failed")
        return {
            "question": question,
            "status": "failed",
            "generated_cypher": cypher,
            "error": last.error if last else "validation failed",
            "stage": last.stage if last else None,
        }

    def generate_response(self, question: str) -> Dict[str, str]:
        return self.generate_and_validate(question)
