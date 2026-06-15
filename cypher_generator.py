# cypher_generator.py
# Natural Language -> Cypher via LangChain + Ollama

import re
from typing import Dict, List

from langchain_core.prompts import PromptTemplate
from langchain_ollama import ChatOllama


class CypherGenerator:

    """
    Natural Language
            ↓
        LangChain
            ↓
      Ollama (qwen2.5)
            ↓
         Cypher
    """

    def __init__(
        self,
        ontology,
        model_name: str = "qwen2.5:latest"
    ):

        self.ontology = ontology

        self.llm = ChatOllama(
            model=model_name,
            temperature=0
        )

        self.prompt = PromptTemplate(
            input_variables=[
                "classes",
                "object_properties",
                "data_properties",
                "question"
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
3. Do NOT use CREATE, MERGE, SET, DELETE, or DETACH DELETE.
4. Prefer matching nodes by label and `name` when filtering individuals.
5. Return ONLY the Cypher query.

Question:

{question}

Cypher:
"""
        )

    def get_classes(self) -> List[str]:

        return sorted(
            cls.name for cls in self.ontology.onto.classes()
        )

    def get_object_properties(self) -> List[str]:

        return sorted(
            [
                prop.name.upper()
                for prop in self.ontology.onto.object_properties()
            ]
        )

    def get_data_properties(self) -> List[str]:

        return sorted(
            prop.name for prop in self.ontology.onto.data_properties()
        )

    def build_prompt(self, question: str) -> str:

        return self.prompt.format(
            classes="\n".join(f"- {name}" for name in self.get_classes()),
            object_properties="\n".join(
                f"- {name}" for name in self.get_object_properties()
            ),
            data_properties="\n".join(
                f"- {name}" for name in self.get_data_properties()
            ),
            question=question
        )

    def clean_cypher(self, cypher: str) -> str:

        cypher = cypher.strip()

        cypher = re.sub(
            r"```cypher",
            "",
            cypher,
            flags=re.IGNORECASE
        )

        cypher = cypher.replace("```", "")
        cypher = cypher.strip()

        lines = []
        for line in cypher.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("//"):
                continue
            lines.append(line)

        return "\n".join(lines).strip()

    def generate(self, question: str) -> str:

        prompt = self.build_prompt(question)

        response = self.llm.invoke(prompt)

        cypher = self.clean_cypher(response.content)

        if not cypher:

            raise ValueError("Model returned an empty Cypher query.")

        upper = cypher.upper()

        if not any(keyword in upper for keyword in ("MATCH", "RETURN", "WITH")):

            raise ValueError(
                "Generated text does not look like a valid Cypher query."
            )

        forbidden = (
            "CREATE ",
            "MERGE ",
            "DELETE ",
            "DETACH ",
            "SET ",
            "REMOVE ",
            "DROP "
        )

        if any(keyword in upper for keyword in forbidden):

            raise ValueError(
                "Generated Cypher must be read-only (MATCH/RETURN only)."
            )

        return cypher

    def generate_response(self, question: str) -> Dict[str, str]:

        return {
            "question": question,
            "generated_cypher": self.generate(question)
        }
