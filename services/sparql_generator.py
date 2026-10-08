# sparql_generator.py
# ==============================================
# PART 1
# LangChain + OpenAI + Dynamic Schema Extraction
# ==============================================

import re
from typing import Dict, List

from langchain_core.prompts import PromptTemplate
from rdflib import Graph

from core.llm import get_chat_llm


class SparqlGenerator:

    """
    Natural Language
            ↓
        LangChain
            ↓
      LangChain
            ↓
      OpenAI
            ↓
         SPARQL
    """

    def __init__(
    self,
    ontology,
    model_name: str = "gpt-4.1-mini"
):

        self.ontology = ontology

        self.namespace = (
            "http://example.org/"
            "healthcare-hospital.owl#"
        )

        self.model_name = model_name
        self.llm = get_chat_llm(model=model_name, temperature=0)

        self.prompt = PromptTemplate(

            input_variables=[

                "namespace",

                "classes",

                "object_properties",

                "data_properties",

                "inferred_properties",

                "question"
            ],

            template="""
You are an expert SPARQL generator.

Generate SPARQL query ONLY.

Do not explain.

Do not use markdown.

Do not surround with ```sparql.

Ontology Namespace:

{namespace}

PREFIX:

PREFIX hc: <{namespace}>

Available Classes:

{classes}

Available Object Properties:

{object_properties}

Available Data Properties:

{data_properties}

NOT STORED in the data (inferred by a reasoner, so a query using them returns NOTHING).
Use the property in brackets instead:

{inferred_properties}

Rules:

1. Use ONLY the classes listed above.

2. Use ONLY the properties listed above.

3. Always include:

PREFIX hc: <{namespace}>

4. Return valid SPARQL.

5. Return ONLY SELECT queries.

6. Use object properties exactly as defined.

7. If the question cannot be answered,
return an empty SELECT query.

8. The data is stored as asserted: an individual has only its most
specific class (a diagnosis is hc:Diagnosis, not hc:Condition, and a
patient is hc:Patient, not hc:Person). Query the most specific class.

Question:

{question}

SPARQL:
"""
        )

    # ==========================================
    # DYNAMIC SCHEMA EXTRACTION
    # ==========================================

    def get_schema(self) -> Dict:

        return {

            "classes":

                self.get_classes(),

            "object_properties":

                self.get_object_properties(),

            "data_properties":

                self.get_data_properties()
        }

    def get_classes(self) -> List[str]:

        return sorted(

            [

                cls.name

                for cls in (

                    self.ontology

                    .onto

                    .classes()

                )

            ]

        )

    def get_object_properties(self) -> List[str]:

        return sorted(

            [

                prop.name

                for prop in (

                    self.ontology

                    .onto

                    .object_properties()

                )

            ]

        )

    def get_data_properties(self) -> List[str]:

        return sorted(

            [

                prop.name

                for prop in (

                    self.ontology

                    .onto

                    .data_properties()

                )

            ]

        )

    @staticmethod
    def property_lines(properties) -> str:
        """One line per property with its direction: `hasDiagnosis (Patient -> Diagnosis)`.

        A bare list of names is not enough: given only `hasDiagnosis` the model writes `?diagnosis hc:hasDiagnosis
        ?patient`, a valid query that matches nothing.
        """
        def names(values):
            flat = []
            for v in values or []:
                flat.extend(getattr(v, "Classes", None) or [v])
            return " | ".join(sorted(getattr(v, "name", None) or getattr(v, "__name__", str(v)) for v in flat)) or "?"

        lines = []
        for prop in sorted(properties, key=lambda p: p.name):
            domain, rng = names(prop.domain), names(prop.range)
            lines.append(f"{prop.name} ({domain} -> {rng})")
        return "\n".join(lines)

    def inferred_properties_text(self) -> str:
        """Object properties that exist only as the inferred inverse of another (the data stores the forward one).

        Found from the ontology itself: an inverse whose comment says it is inferred. Without this the model
        happily writes a valid query over a property no triple uses, and gets an empty answer.
        """
        lines = []
        for prop in self.ontology.onto.object_properties():
            inverse = getattr(prop, "inverse_property", None)
            comment = " ".join(str(c) for c in (getattr(prop, "comment", None) or []))
            if inverse is not None and "nverse of" in comment:
                lines.append(f"{prop.name} [use {inverse.name}]")
        return "\n".join(sorted(lines)) or "(none)"

    # ==========================================
    # PROMPT CONSTRUCTION
    # ==========================================

    def build_prompt(

        self,

        question: str

    ):

        schema = self.get_schema()

        return self.prompt.format(

            namespace=self.namespace,

            classes="\n".join(

                schema["classes"]

            ),

            object_properties=self.property_lines(self.ontology.onto.object_properties()),

            data_properties=self.property_lines(self.ontology.onto.data_properties()),

            inferred_properties=self.inferred_properties_text(),

            question=question
        )

    # ==========================================
    # SPARQL GENERATION
    # ==========================================

    def generate(

        self,

        question: str

    ) -> str:

        prompt = self.build_prompt(

            question
        )

        response = self.llm.invoke(

            prompt
        )

        sparql = response.content

        sparql = self.clean_sparql(

            sparql
        )

        return sparql

    # ==========================================
    # CLEANUP
    # ==========================================

    def clean_sparql(

        self,

        sparql: str

    ) -> str:

        sparql = sparql.strip()

        sparql = re.sub(

            r"```sparql",

            "",

            sparql,

            flags=re.IGNORECASE
        )

        sparql = sparql.replace(

            "```",

            ""
        )

        return sparql.strip()

    def validate_prefix(
        self,
        sparql: str
    ) -> bool:

        sparql_upper = sparql.upper()

        return "PREFIX HC:" in sparql_upper

    def validate_select(
        self,
        sparql: str
    ) -> bool:

        sparql_upper = sparql.upper()

        return (
            sparql_upper.strip().startswith("PREFIX")
            and "SELECT" in sparql_upper
        )

    def _build_validator(self):
        from core.config import get_settings
        from core.sparql_validator import SparqlQueryValidator

        settings = get_settings()
        schema = self.get_schema()
        return SparqlQueryValidator(
            classes=schema["classes"],
            object_properties=schema["object_properties"],
            data_properties=schema["data_properties"],
            default_limit=settings["query_default_limit"],
            timeout_seconds=settings["query_timeout_seconds"],
            namespace=self.namespace,
        )

    def validate_execution(
        self,
        sparql: str
    ):

        try:
            # The same bounded execution path as the public /sparql endpoint (generated queries are
            # untrusted too): a worker process that is terminated when the time limit passes.
            results = self.ontology.execute_sparql(sparql)

            return {
                "valid": True,
                "results": results
            }

        except Exception as e:

            return {
                "valid": False,
                "error": str(e)
            }

    def validate(
        self,
        sparql: str
    ):
        """Run shared SparqlQueryValidator stages, then execute against the OWL graph."""
        import logging

        from core.metrics import metrics

        logger = logging.getLogger("healthcare_ontology.query")
        validator = self._build_validator()
        check = validator.run_all_checks(sparql)
        if not check.valid:
            metrics.incr("sparql_validation_fail")
            logger.warning(
                "SPARQL validation failed stage=%s error=%s",
                check.stage,
                check.error,
            )
            return {
                "valid": False,
                "error": check.error,
                "stage": check.stage,
                "details": check.details,
                "sparql": check.query,
            }

        metrics.incr("sparql_validation_pass")
        logger.info(
            "SPARQL validation passed; executing query (limit stages applied)"
        )
        exec_result = self.validate_execution(check.query)
        if exec_result.get("valid"):
            exec_result["sparql"] = check.query
        return exec_result

    def repair(
        self,
        question: str,
        broken_query: str,
        error: str
    ):

        repair_prompt = f"""
You generated an invalid SPARQL query.

Question:

{question}

Broken Query:

{broken_query}

Validation Error:

{error}

Fix the query.

Return ONLY a read-only SELECT SPARQL query.
Do not use INSERT, DELETE, DROP, CLEAR, LOAD, CREATE, or MODIFY.

Namespace:

PREFIX hc:
<{self.namespace}>
"""

        response = self.llm.invoke(repair_prompt)

        repaired = self.clean_sparql(response.content)

        return repaired

    def generate_and_validate(
        self,
        question: str,
        max_attempts: int = 3
    ):
        import logging
        import time

        from core.metrics import metrics
        from core.query_cache import query_cache

        logger = logging.getLogger("healthcare_ontology.query")
        cache_key = query_cache.make_key("sparql", question.strip().lower())
        cached = query_cache.get(cache_key)
        if cached is not None:
            metrics.incr("sparql_cache_hit")
            return {**cached, "cached": True}

        metrics.incr("sparql_llm_generate")
        sparql = self.generate(question)
        validation = {"valid": False, "error": "No attempts made"}
        started = time.perf_counter()

        for attempt in range(max_attempts):

            validation = self.validate(sparql)

            if validation["valid"]:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                payload = {
                    "question": question,
                    "sparql": validation.get("sparql", sparql),
                    "results": validation["results"],
                    "attempts": attempt + 1,
                    "elapsed_ms": elapsed_ms,
                    "cached": False,
                }
                query_cache.set(cache_key, payload)
                logger.info(
                    "NL→SPARQL ok attempts=%s elapsed_ms=%s",
                    attempt + 1,
                    elapsed_ms,
                )
                return payload

            logger.info(
                "NL→SPARQL repair attempt=%s stage=%s error=%s",
                attempt + 1,
                validation.get("stage"),
                validation.get("error"),
            )
            sparql = self.repair(
                question,
                sparql,
                validation["error"]
            )

        metrics.incr("sparql_llm_failed")
        return {
            "question": question,
            "status": "failed",
            "sparql": sparql,
            "error": validation["error"],
            "stage": validation.get("stage"),
        }


# ==============================================
# STANDALONE TEST
# ==============================================

if __name__ == "__main__":

    from services.load_ontology import (

        HealthcareOntology

    )

    ontology = (

        HealthcareOntology()
    )

    generator = (

        SparqlGenerator(

            ontology
        )
    )

    question = (

        "Show all patients "

        "diagnosed with "

        "hypertension"
    )

    print(

        "\nQuestion:\n"

    )

    print(

        question
    )

    print(

        "\nGenerated SPARQL:\n"

    )

    print(

        generator.generate(

            question
        )
    )

