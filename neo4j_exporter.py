# neo4j_exporter.py

import os
from typing import Dict, Any

from neo4j import GraphDatabase
from dotenv import load_dotenv


load_dotenv()


class Neo4jExporter:

    """
    Exports OWLReady2 ontology individuals,
    object properties, and data properties
    into Neo4j.

    Flow:

    OWL
      ↓
    Cypher Generation
      ↓
    Cypher Execution
      ↓
    Neo4j Database (HC)
    """

    def __init__(self, ontology):

        self.ontology = ontology

        self.driver = GraphDatabase.driver(

            os.getenv(
                "NEO4J_URI",
                "bolt://localhost:7687"
            ),

            auth=(

                os.getenv(
                    "NEO4J_USERNAME",
                    "neo4j"
                ),

                os.getenv(
                    "NEO4J_PASSWORD"
                )
            )
        )

        self.database = os.getenv(
            "NEO4J_DATABASE",
            "HC"
        )

    # ==========================================
    # PUBLIC API
    # ==========================================

    def export(self) -> Dict[str, Any]:

        """
        Main export function.
        """

        stats = {

            "database":
                self.database,

            "nodes_created":
                0,

            "properties_added":
                0,

            "relationships_created":
                0
        }

        with self.driver.session(
            database=self.database
        ) as session:

            # ----------------------------------
            # PASS 1 : Nodes
            # ----------------------------------

            stats["nodes_created"] = (

                self._create_nodes(
                    session
                )
            )

            # ----------------------------------
            # PASS 2 : Data Properties
            # ----------------------------------

            stats["properties_added"] = (

                self._add_properties(
                    session
                )
            )

            # ----------------------------------
            # PASS 3 : Relationships
            # ----------------------------------

            stats[
                "relationships_created"
            ] = (

                self._create_relationships(
                    session
                )
            )

        return {

            "status":
                "success",

            **stats
        }

    # ==========================================
    # CREATE NODES
    # ==========================================

    def _create_nodes(
        self,
        session
    ) -> int:

        count = 0

        for individual in (

            self.ontology.onto.individuals()

        ):

            try:

                label = (

                    individual.is_a[0].name
                )

            except Exception:

                label = "Entity"

            cypher = f"""

            MERGE (n:{label}

            {{
                name:$name
            }}

            )

            """

            session.run(

                cypher,

                name=individual.name
            )

            count += 1

        return count

    # ==========================================
    # DATA PROPERTIES
    # ==========================================

    def _add_properties(
        self,
        session
    ) -> int:

        count = 0

        for individual in (

            self.ontology.onto.individuals()

        ):

            for prop in (

                self.ontology.onto.data_properties()

            ):

                try:

                    values = prop[individual]

                except Exception:

                    continue

                if not values:

                    continue

                label = (

                    individual.is_a[0].name
                )

                value = values[0]

                cypher = f"""

                MATCH (n:{label}

                {{
                    name:$name
                }}

                )

                SET n.{prop.name}

                    = $value

                """

                session.run(

                    cypher,

                    name=individual.name,

                    value=str(value)
                )

                count += 1

        return count

    # ==========================================
    # RELATIONSHIPS
    # ==========================================

    def _create_relationships(
        self,
        session
    ) -> int:

        count = 0

        for subject in (

            self.ontology.onto.individuals()

        ):

            for prop in (

                subject.get_properties()

            ):

                try:

                    values = prop[subject]

                except Exception:

                    continue

                for obj in values:

                    if not hasattr(
                        obj,
                        "name"
                    ):

                        continue

                    rel = (

                        prop.name.upper()
                    )

                    cypher = f"""

                    MATCH (a

                    {{
                        name:$a
                    }}

                    )

                    MATCH (b

                    {{
                        name:$b
                    }}

                    )

                    MERGE

                    (a)-[:{rel}]->(b)

                    """

                    session.run(

                        cypher,

                        a=subject.name,

                        b=obj.name
                    )

                    count += 1

        return count

    # ==========================================
    # CLEAR DATABASE
    # ==========================================

    def clear_database(self):

        with self.driver.session(
            database=self.database
        ) as session:

            session.run(

                """

                MATCH (n)

                DETACH DELETE n

                """

            )

        return {

            "status":

                "database cleared",

            "database":

                self.database
        }

    # ==========================================
    # VERIFY EXPORT
    # ==========================================

    def summary(self):

        with self.driver.session(
            database=self.database
        ) as session:

            node_count = (

                session.run(

                    """

                    MATCH (n)

                    RETURN count(n)

                        AS count

                    """

                ).single()["count"]

            )

            rel_count = (

                session.run(

                    """

                    MATCH ()-[r]->()

                    RETURN count(r)

                        AS count

                    """

                ).single()["count"]

            )

        return {

            "database":
                self.database,

            "nodes":
                node_count,

            "relationships":
                rel_count
        }

    # ==========================================
    # CLOSE
    # ==========================================

    def close(self):

        self.driver.close()


# ==================================================
# STANDALONE TEST
# ==================================================

if __name__ == "__main__":

    from load_ontology import (

        HealthcareOntology

    )

    ontology = (

        HealthcareOntology()
    )

    exporter = (

        Neo4jExporter(
            ontology
        )
    )

    print(

        "\nExporting ontology "

        "to Neo4j...\n"

    )

    result = (

        exporter.export()
    )

    print(result)

    print(

        "\nNeo4j Summary:\n"

    )

    print(

        exporter.summary()
    )

    exporter.close()

