# embedding_service.py
# =====================================================
# PART 1
# Owlready2 Extraction + Ollama Embeddings +
# Neo4j Vector Storage
# =====================================================

import os
from typing import List, Dict

import ollama
from neo4j import GraphDatabase
from dotenv import load_dotenv
from owlready2 import get_ontology


load_dotenv()


class EmbeddingService:

    """
    OWL Annotations
            ↓
    Ollama (nomic-embed-text)
            ↓
    Embeddings
            ↓
    Neo4j HC
    """

   
    def __init__(
    self,
    ontology_path: str,
    embedding_model="nomic-embed-text:latest"
):

        self.onto = get_ontology(
        ontology_path
    ).load()

        self.embedding_model = embedding_model

        self.embedding_model = embedding_model

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

    # =================================================
    # EXTRACT EMBEDDABLE CONTENT
    # =================================================

    def extract_annotations(
        self
    ) -> List[Dict]:

        """
        Extract class annotations,
        comments and definitions.

        Returns:

        [

            {
                "node_name": ...,
                "node_type": ...,
                "text": ...
            }

        ]
        """

        documents = []

        for cls in (

            self.onto.classes()

        ):

            node_name = cls.name

            text_parts = [

                f"Class: {node_name}"
            ]

            # -------------------------
            # rdfs:comment
            # -------------------------

            if hasattr(

                cls,

                "comment"
            ):

                for comment in cls.comment:

                    text_parts.append(

                        f"Comment: "

                        f"{comment}"
                    )

            # -------------------------
            # label
            # -------------------------

            if hasattr(

                cls,

                "label"
            ):

                for label in cls.label:

                    text_parts.append(

                        f"Label: "

                        f"{label}"
                    )

            # -------------------------
            # is_a relationships
            # -------------------------

            parents = [

                parent.name

                for parent in cls.is_a

                if hasattr(
                    parent,
                    "name"
                )
            ]

            if parents:

                text_parts.append(

                    "Parents: "

                    +

                    ", ".join(
                        parents
                    )
                )

            # -------------------------
            # Object Properties
            # -------------------------

            for prop in (

                self.onto.object_properties()

            ):

                try:

                    domains = [

                        d.name

                        for d in prop.domain

                        if hasattr(
                            d,
                            "name"
                        )
                    ]

                    if node_name in domains:

                        text_parts.append(

                            f"Relationship: "

                            f"{prop.name}"
                        )

                except:

                    pass

            documents.append(

                {

                    "node_name":

                        node_name,

                    "node_type":

                        "Class",

                    "text":

                        "\n".join(
                            text_parts
                        )
                }

            )

        return documents

    # =================================================
    # GENERATE EMBEDDING
    # =================================================

    def generate_embedding(

        self,

        text: str

    ) -> List[float]:

        response = ollama.embeddings(

            model=self.embedding_model,

            prompt=text
        )

        return response[

            "embedding"
        ]

    # =================================================
    # STORE VECTOR
    # =================================================

    def store_embedding(

        self,

        node_name: str,

        embedding: List[float]

    ):

        with self.driver.session(

            database=self.database

        ) as session:

            session.run(

                """

                MERGE (

                    n:OntologyConcept

                    {

                        name:$name

                    }

                )

                SET

                    n.embedding

                    =

                    $embedding

                """,

                name=node_name,

                embedding=embedding
            )

    # =================================================
    # PROCESS SINGLE NODE
    # =================================================

    def process_document(

        self,

        document: Dict

    ):

        embedding = (

            self.generate_embedding(

                document["text"]
            )
        )

        self.store_embedding(

            document["node_name"],

            embedding
        )

        return {

            "node":

                document[
                    "node_name"
                ],

            "dimensions":

                len(
                    embedding
                ),

            "status":

                "stored"
        }

    # =================================================
    # HEALTH CHECK
    # =================================================

    def health(self):

        try:

            response = ollama.embeddings(

                model=self.embedding_model,

                prompt="test"
            )

            dimensions = len(

                response[
                    "embedding"
                ]
            )

            return {

                "status":

                    "healthy",

                "model":

                    self.embedding_model,

                "dimensions":

                    dimensions,

                "database":

                    self.database
            }

        except Exception as e:

            return {

                "status":

                    "unhealthy",

                "error":

                    str(e)
            }
# =====================================================
# PART 2A
# Batch Synchronization + Neo4j Vector Index +
# Statistics Reporting
# =====================================================

import logging
from typing import Dict


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


class EmbeddingService(EmbeddingService):

    VECTOR_INDEX_NAME = "ontology_embeddings"

    VECTOR_DIMENSIONS = 768

    VECTOR_SIMILARITY = "cosine"

    # =================================================
    # VECTOR INDEX EXISTS
    # =================================================

    def vector_index_exists(self) -> bool:

        """
        Check whether the Neo4j vector
        index already exists.
        """

        query = """
        SHOW VECTOR INDEXES
        YIELD name
        WHERE name = $index_name
        RETURN count(*) AS count
        """

        try:

            with self.driver.session(
                database=self.database
            ) as session:

                result = session.run(

                    query,

                    index_name=self.VECTOR_INDEX_NAME
                )

                record = result.single()

                exists = record["count"] > 0

                logger.info(

                    "Vector index '%s' exists: %s",

                    self.VECTOR_INDEX_NAME,

                    exists
                )

                return exists

        except Exception as e:

            logger.exception(

                "Failed checking vector index."
            )

            raise RuntimeError(

                f"Vector index check failed: {e}"
            )

    # =================================================
    # CREATE VECTOR INDEX
    # =================================================

    def create_vector_index(self):

        """
        Create Neo4j vector index
        if it does not exist.
        """

        if self.vector_index_exists():

            logger.info(

                "Vector index already exists."
            )

            return

        query = f"""
        CREATE VECTOR INDEX
        {self.VECTOR_INDEX_NAME}
        IF NOT EXISTS
        FOR (n:OntologyConcept)
        ON (n.embedding)
        OPTIONS {{
            indexConfig: {{
                `vector.dimensions`: {self.VECTOR_DIMENSIONS},
                `vector.similarity_function`: '{self.VECTOR_SIMILARITY}'
            }}
        }}
        """

        try:

            with self.driver.session(
                database=self.database
            ) as session:

                session.run(query)

                logger.info(

                    "Created vector index '%s'.",

                    self.VECTOR_INDEX_NAME
                )

        except Exception as e:

            logger.exception(

                "Failed creating vector index."
            )

            raise RuntimeError(

                f"Vector index creation failed: {e}"
            )

    def ensure_vector_index(self):

        """
        Create the Neo4j vector index when it is missing.
        """

        if not self.vector_index_exists():

            self.create_vector_index()

    # =================================================
    # BATCH SYNCHRONIZATION
    # =================================================

    def synchronize_embeddings(self):

        """
        Extract all ontology annotations
        and synchronize them into Neo4j.
        """

        documents = self.extract_annotations()

        logger.info(

            "Found %s ontology documents.",

            len(documents)
        )

        results = []

        successful = 0

        failed = 0

        for document in documents:

            try:

                result = self.process_document(

                    document
                )

                results.append(result)

                successful += 1

                logger.info(

                    "Processed: %s",

                    document["node_name"]
                )

            except Exception as e:

                failed += 1

                logger.exception(

                    "Failed processing %s",

                    document["node_name"]
                )

                results.append(

                    {

                        "node":

                            document[
                                "node_name"
                            ],

                        "status":

                            "failed",

                        "error":

                            str(e)
                    }

                )

        self.ensure_vector_index()

        return {

            "total_documents":

                len(documents),

            "successful":

                successful,

            "failed":

                failed,

            "results":

                results
        }

    # =================================================
    # STATISTICS REPORTING
    # =================================================

    def get_statistics(self) -> Dict:

        """
        Return embedding statistics.
        """

        query = """

        MATCH (

            n:OntologyConcept

        )

        RETURN

            count(n)

            AS total_nodes,

            count(

                n.embedding

            )

            AS embedded_nodes

        """

        try:

            with self.driver.session(
                database=self.database
            ) as session:

                result = session.run(query)

                record = result.single()

                return {

                    "database":

                        self.database,

                    "embedding_model":

                        self.embedding_model,

                    "vector_index":

                        self.VECTOR_INDEX_NAME,

                    "index_exists":

                        self.vector_index_exists(),

                    "vector_dimensions":

                        self.VECTOR_DIMENSIONS,

                    "total_nodes":

                        record[
                            "total_nodes"
                        ],

                    "embedded_nodes":

                        record[
                            "embedded_nodes"
                        ]
                }

        except Exception as e:

            logger.exception(

                "Statistics collection failed."
            )

            raise RuntimeError(

                f"Statistics failed: {e}"
            )

    # =================================================
    # COMPLETE INITIALIZATION
    # =================================================

    def initialize_embeddings(self):

        """
        Complete setup:

        1. Synchronize ontology
        2. Create vector index
        3. Return statistics
        """

        sync_result = (

            self.synchronize_embeddings()
        )

        self.create_vector_index()

        stats = self.get_statistics()

        return {

            "synchronization":

                sync_result,

            "statistics":

                stats
        }

    # =================================================
    # CLOSE CONNECTION
    # =================================================

    def close(self):

        if self.driver:

            self.driver.close()

            logger.info(

                "Neo4j connection closed."
            )


# =====================================================
# STANDALONE TESTING
# =====================================================

if __name__ == "__main__":

   
    embedding_service = EmbeddingService(

        ontology_path="healthcare_ontology.owl"
    )

    print("\nHealth Check")

    print(

        embedding_service.health()
    )

    print("\nSynchronizing")

    sync = (

        embedding_service

        .synchronize_embeddings()
    )

    print(sync)

    print("\nCreating Vector Index")

    embedding_service.create_vector_index()

    print(

        "\nStatistics"
    )

    print(

        embedding_service

        .get_statistics()
    )

    embedding_service.close()

# =====================================================
# PART 2B
# Similarity Search + FastAPI Integration
# =====================================================

from typing import List, Dict, Optional
import logging


logger = logging.getLogger(__name__)


class EmbeddingService(EmbeddingService):

    # =================================================
    # VECTOR SIMILARITY SEARCH
    # =================================================

    def similarity_search(
        self,
        query: str,
        top_k: int = 5
    ) -> List[Dict]:

        """
        Search ontology concepts using
        Neo4j vector indexes.

        Parameters
        ----------
        query : str
            User query.

        top_k : int
            Number of results.

        Returns
        -------
        List[Dict]
        """

        try:

            self.ensure_vector_index()

            query_embedding = (

                self.generate_embedding(
                    query
                )
            )

            cypher = """

            CALL db.index.vector.queryNodes(

                $index_name,
                $top_k,
                $embedding

            )

            YIELD

                node,
                score

            RETURN

                node.name AS name,
                score

            ORDER BY

                score DESC

            """

            with self.driver.session(

                database=self.database

            ) as session:

                result = session.run(

                    cypher,

                    index_name=

                        self.VECTOR_INDEX_NAME,

                    top_k=

                        top_k,

                    embedding=

                        query_embedding
                )

                records = []

                for record in result:

                    records.append(

                        {

                            "name":

                                record["name"],

                            "score":

                                float(

                                    record["score"]
                                )
                        }
                    )

                return records

        except Exception as e:

            logger.exception(

                "Similarity search failed."
            )

            raise RuntimeError(

                f"Similarity search failed: {e}"
            )

    # =================================================
    # SIMILARITY SEARCH WITH DETAILS
    # =================================================

    def similarity_search_detailed(

        self,
        query: str,
        top_k: int = 5

    ) -> List[Dict]:

        """
        Return ontology concepts
        together with metadata.
        """

        try:

            self.ensure_vector_index()

            query_embedding = (

                self.generate_embedding(
                    query
                )
            )

            cypher = """

            CALL db.index.vector.queryNodes(

                $index_name,
                $top_k,
                $embedding

            )

            YIELD

                node,
                score

            RETURN

                node.name AS name,
                labels(node) AS labels,
                score

            ORDER BY

                score DESC

            """

            with self.driver.session(

                database=self.database

            ) as session:

                result = session.run(

                    cypher,

                    index_name=

                        self.VECTOR_INDEX_NAME,

                    top_k=

                        top_k,

                    embedding=

                        query_embedding
                )

                return [

                    {

                        "name":

                            record["name"],

                        "labels":

                            record["labels"],

                        "score":

                            float(
                                record["score"]
                            )
                    }

                    for record in result
                ]

        except Exception as e:

            logger.exception(

                "Detailed search failed."
            )

            raise RuntimeError(

                f"Detailed search failed: {e}"
            )

    # =================================================
    # FASTAPI RESPONSE FORMATTER
    # =================================================

    def search_api(

        self,
        query: str,
        top_k: int = 5

    ) -> Dict:

        """
        Method intended for
        FastAPI endpoints.
        """

        try:

            results = (

                self.similarity_search(

                    query=query,

                    top_k=top_k
                )
            )

            return {

                "query":

                    query,

                "top_k":

                    top_k,

                "results":

                    results,

                "count":

                    len(results)
            }

        except Exception as e:

            logger.exception(

                "API search failed."
            )

            return {

                "query":

                    query,

                "status":

                    "error",

                "error":

                    str(e),

                "results":

                    []
            }

    # =================================================
    # FASTAPI HEALTH ENDPOINT
    # =================================================

    def api_health(self):

        """
        Health endpoint for APIs.
        """

        try:

            health = self.health()

            statistics = (

                self.get_statistics()
            )

            return {

                "status":

                    "healthy",

                "embedding_service":

                    health,

                "statistics":

                    statistics
            }

        except Exception as e:

            logger.exception(

                "Health endpoint failed."
            )

            return {

                "status":

                    "unhealthy",

                "error":

                    str(e)
            }

    # =================================================
    # QUERY BY EXISTING NODE NAME
    # =================================================

    def find_similar_concepts(

        self,
        node_name: str,
        top_k: int = 5

    ) -> List[Dict]:

        """
        Find concepts similar to
        an existing ontology concept.
        """

        try:

            self.ensure_vector_index()

            cypher = """

            MATCH (

                n:OntologyConcept

                {

                    name:$name

                }

            )

            CALL db.index.vector.queryNodes(

                $index_name,

                $top_k,

                n.embedding

            )

            YIELD

                node,
                score

            WHERE

                node.name <> $name

            RETURN

                node.name AS name,

                score

            ORDER BY

                score DESC

            """

            with self.driver.session(

                database=self.database

            ) as session:

                result = session.run(

                    cypher,

                    name=node_name,

                    top_k=top_k,

                    index_name=

                        self.VECTOR_INDEX_NAME
                )

                return [

                    {

                        "name":

                            record["name"],

                        "score":

                            float(
                                record["score"]
                            )
                    }

                    for record in result
                ]

        except Exception as e:

            logger.exception(

                "Concept similarity failed."
            )

            raise RuntimeError(

                f"Concept similarity failed: {e}"
            )

    # =================================================
    # FASTAPI VALIDATION HELPER
    # =================================================

    @staticmethod
    def validate_search_request(

        query: Optional[str],
        top_k: int

    ):

        """
        Validate API requests.
        """

        if not query:

            raise ValueError(

                "Query cannot be empty."
            )

        if top_k <= 0:

            raise ValueError(

                "top_k must be positive."
            )

        if top_k > 100:

            raise ValueError(

                "top_k cannot exceed 100."
            )

    # =================================================
    # FASTAPI ENDPOINT HANDLER
    # =================================================

    def handle_search_request(

        self,
        query: str,
        top_k: int = 5

    ):

        """
        Wrapper intended for
        FastAPI routes.
        """

        try:

            self.validate_search_request(

                query,
                top_k
            )

            return self.search_api(

                query,
                top_k
            )

        except Exception as e:

            return {

                "status":

                    "error",

                "error":

                    str(e),

                "results":

                    []
            }
