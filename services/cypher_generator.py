# cypher_generator.py
# Natural Language -> Cypher via LangChain + Ollama (+ validation / repair)

from __future__ import annotations

import logging
import re
import time
from typing import Dict, List

from langchain_core.prompts import PromptTemplate
from langchain_ollama import ChatOllama

from core.cypher_validator import CypherQueryValidator
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
      Ollama (qwen2.5)
            ↓
         Cypher
            ↓
      CypherQueryValidator
    """

    def __init__(
        self,
        ontology,
        model_name: str = "qwen2.5:latest",
        explain_fn=None,
    ):
        self.ontology = ontology
        self.explain_fn = explain_fn
        self.llm = ChatOllama(model=model_name, temperature=0)
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

- Each individual is a node with label from its class (e.g. Patient, Doctor, Diagnosis).
- Every node has a `name` property (string) with the individual name.
- Object properties become relationships with UPPERCASE type names
  (e.g. hasDiagnosis -> HASDIAGNOSIS).
- Data properties are stored as node properties using camelCase names
  (e.g. diagnosisName, patientAge).

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
6. Return ONLY the Cypher query.

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
        lines = []
        for line in cypher.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            lines.append(line)
        return "\n".join(lines).strip()

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

Return ONLY a read-only MATCH ... RETURN Cypher query.
Do not use CREATE, MERGE, SET, DELETE, DETACH, REMOVE, DROP, or CALL DBMS.
"""
        response = self.llm.invoke(repair_prompt)
        return self.clean_cypher(response.content)

    def generate_and_validate(self, question: str, max_attempts: int = 3) -> Dict:
        cache_key = query_cache.make_key("cypher", question.strip().lower())
        cached = query_cache.get(cache_key)
        if cached is not None:
            metrics.incr("cypher_cache_hit")
            return {**cached, "cached": True}

        metrics.incr("cypher_llm_generate")
        cypher = self.generate(question)
        last = None
        started = time.perf_counter()

        for attempt in range(max_attempts):
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
