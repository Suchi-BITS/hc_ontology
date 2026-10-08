# sparql_to_cypher.py
# =====================================================
# PART 1
# SPARQL Parser + Cypher Generator
# =====================================================

import os
import re
from typing import Dict, List

from dotenv import load_dotenv
from neo4j import READ_ACCESS, GraphDatabase, unit_of_work
from neo4j.exceptions import ClientError
from core.config import require_neo4j_password

load_dotenv()


class SparqlToCypher:

    """
    SPARQL
       ↓
    Parse Triple Patterns
       ↓
    Cypher Generation
    """

    def __init__(self):

        self.namespace = (

            "http://example.org/"

            "healthcare-hospital.owl#"
        )

    # =================================================
    # ENTRY POINT
    # =================================================

    def generate_cypher(

        self,

        sparql: str

    ) -> Dict:

        parsed = self.parse(

            sparql
        )

        cypher = self.build_cypher(

            parsed
        )

        return {

            "parsed":

                parsed,

            "cypher":

                cypher
        }

    # =================================================
    # SPARQL PARSER
    # =================================================

    def parse(

        self,

        sparql: str

    ) -> Dict:

        sparql = self.clean(

            sparql
        )

        select_vars = (

            self.extract_select(

                sparql
            )
        )

        where_clause = (

            self.extract_where(

                sparql
            )
        )

        triples = (

            self.extract_triples(

                where_clause
            )
        )

        filters = (

            self.extract_filters(

                where_clause
            )
        )

        return {

            "select":

                select_vars,

            "triples":

                triples,

            "filters":

                filters
        }

    # =================================================
    # CLEAN SPARQL
    # =================================================

    def clean(

        self,

        sparql: str

    ) -> str:

        sparql = sparql.replace(

            "\n",

            " "
        )

        sparql = re.sub(

            r"\s+",

            " ",

            sparql
        )

        return sparql.strip()

    # =================================================
    # EXTRACT SELECT
    # =================================================

    def extract_select(

        self,

        sparql: str

    ) -> List[str]:

        match = re.search(

            r"SELECT\s+(.*?)\s+WHERE",

            sparql,

            re.IGNORECASE
        )

        if not match:

            return []

        variables = (

            match.group(1)

            .strip()

            .split()
        )

        return [

            var.replace(

                "?",

                ""
            )

            for var in variables
        ]

    # =================================================
    # EXTRACT WHERE BLOCK
    # =================================================

    def extract_where(

        self,

        sparql: str

    ) -> str:

        match = re.search(

            r"WHERE\s*\{(.*)\}",

            sparql,

            re.IGNORECASE
        )

        if not match:

            return ""

        return (

            match.group(1)

            .strip()
        )

    # =================================================
    # EXTRACT TRIPLES
    # =================================================

    def _normalize_predicate(
        self,
        predicate: str
    ) -> str:

        predicate = predicate.strip()

        if self._is_type_predicate(predicate):

            return predicate

        if ":" in predicate:

            return predicate.split(":", 1)[-1]

        return predicate

    def _expand_where_triple_patterns(
        self,
        where_clause: str
    ) -> List[str]:

        statements = []

        for block in re.split(r"\s\.\s", where_clause):

            block = block.strip()

            if not block or block.upper().startswith("FILTER"):

                continue

            if ";" in block:

                parts = [part.strip() for part in block.split(";")]
                first_tokens = parts[0].split()

                if len(first_tokens) < 3:

                    continue

                subject = first_tokens[0]
                statements.append(" ".join(first_tokens))

                for part in parts[1:]:

                    tokens = part.split()

                    if len(tokens) == 2:

                        statements.append(
                            f"{subject} {tokens[0]} {tokens[1]}"
                        )

                    elif len(tokens) == 3:

                        statements.append(" ".join(tokens))

                continue

            if "," in block:

                parts = [part.strip() for part in block.split(",")]
                first_tokens = parts[0].split()

                if len(first_tokens) < 3:

                    continue

                subject = first_tokens[0]
                predicate = first_tokens[1]
                statements.append(" ".join(first_tokens))

                for part in parts[1:]:

                    tokens = part.split()

                    if len(tokens) == 3:

                        statements.append(" ".join(tokens))

                    elif len(tokens) == 2:

                        statements.append(
                            f"{subject} {tokens[0]} {tokens[1]}"
                        )

                    elif len(tokens) == 1:

                        statements.append(
                            f"{subject} {predicate} {tokens[0]}"
                        )

                continue

            statements.append(block)

        return statements

    def extract_triples(

        self,

        where_clause: str

    ) -> List[Dict]:

        triples = []

        for statement in self._expand_where_triple_patterns(where_clause):

            tokens = statement.split()

            if len(tokens) != 3:

                continue

            triples.append({

                "subject": tokens[0],

                "predicate": self._normalize_predicate(tokens[1]),

                "object": tokens[2]
            })

        return triples

    # =================================================
    # EXTRACT FILTERS
    # =================================================

    def extract_filters(

        self,

        where_clause: str

    ) -> List[Dict]:

        filters = []

        matches = re.findall(

            r'FILTER\s*\(\s*(.*?)\s*\)',

            where_clause,

            re.IGNORECASE
        )

        for match in matches:

            filters.append({

                "expression":

                    match
            })

        return filters

    def _is_type_predicate(
        self,
        predicate: str
    ) -> bool:

        predicate = predicate.lower()

        return predicate in {"rdf:type", "a"}

    def _normalize_label(
        self,
        value: str
    ) -> str:

        value = value.strip()

        if value.startswith("?"):

            value = value[1:]

        if value.startswith("<") and value.endswith(">"):

            value = value[1:-1]

            if "#" in value:

                value = value.rsplit("#", 1)[-1]

            elif "/" in value:

                value = value.rsplit("/", 1)[-1]

        if ":" in value:

            value = value.split(":", 1)[-1]

        return value.strip('"')

    def _normalize_literal(
        self,
        value: str
    ) -> str:

        value = value.strip()

        if (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        ):

            return value[1:-1]

        return self._normalize_label(value)

    # =================================================
    # CYPHER GENERATION
    # =================================================

    def build_cypher(

        self,

        parsed: Dict

    ) -> str:

        cypher = []

        where_conditions = []

        bound_vars = set()

        triples = parsed[

            "triples"
        ]

        if not triples:

            raise ValueError(

                "No triple patterns could be parsed from the WHERE clause. "

                "Use '.' between triples, or check SPARQL syntax."

            )

        # --------------------------------------
        # MATCH CLAUSES
        # --------------------------------------

        for triple in triples:

            subject = (

                triple["subject"]
            )

            predicate = (

                triple["predicate"]
            )

            obj = (

                triple["object"]
            )

            subject = (

                subject.replace(

                    "?",

                    ""
                )
            )

            # ----------------------------------
            # RDF TYPE -> NODE LABEL
            # ----------------------------------

            if self._is_type_predicate(predicate):

                label = self._normalize_label(obj)

                bound_vars.add(subject)

                cypher.append(

                    f"""

MATCH ({subject}:{label})

"""

                )

                continue

            # ----------------------------------
            # RELATIONSHIP
            # ----------------------------------

            if obj.startswith("?"):

                obj_var = (

                    obj.replace(

                        "?",

                        ""
                    )
                )

                bound_vars.add(subject)
                bound_vars.add(obj_var)

                cypher.append(

                    f"""

MATCH ({subject})

-[:{predicate.upper()}]->

({obj_var})

"""

                )

            # ----------------------------------
            # LITERAL PROPERTY
            # ----------------------------------

            else:

                literal = self._normalize_literal(obj)

                bound_vars.add(subject)

                cypher.append(

                    f"""

MATCH ({subject})

"""

                )

                where_conditions.append(

                    f"""

{subject}.{predicate}

=

"{literal}"

"""

                )

        # --------------------------------------
        # WHERE CLAUSE
        # --------------------------------------

        if where_conditions:

            cypher.append(

                "WHERE "

                +

                " AND ".join(

                    where_conditions
                )
            )

        # --------------------------------------
        # RETURN CLAUSE
        # --------------------------------------

        select_vars = parsed[

            "select"
        ]

        return_vars = [

            var for var in select_vars

            if var in bound_vars

        ]

        if select_vars and not return_vars:

            raise ValueError(

                f"SELECT variables {select_vars} are not bound in the "

                f"WHERE clause. Bound variables: {sorted(bound_vars)}."

            )

        if not return_vars:

            return_vars = sorted(bound_vars)

        if return_vars:

            cypher.append(

                "RETURN "

                +

                ", ".join(

                    return_vars
                )
            )

        return "\n".join(

            cypher
        )

    # =================================================
    # NEO4J CONNECTION
    # =================================================

    def connect(self):
        # Fail fast: an unreachable database must not hold a request for the driver's default 30 s of retries.
        from core.config import get_settings

        settings = get_settings()
        return GraphDatabase.driver(
            settings["neo4j_uri"],
            auth=(settings["neo4j_username"], require_neo4j_password()),
            connection_timeout=5,
            connection_acquisition_timeout=5,
            max_transaction_retry_time=2,
        )

    def _database_name(self) -> str:

        from core.config import get_settings

        return get_settings()["neo4j_database"]

    # =================================================
    # EXECUTE CYPHER
    # =================================================

    def execute_cypher(self, cypher: str) -> List[Dict]:
        """Run a query that came from a user or from the LLM, READ-ONLY.

        The control that matters is the database's own: the query runs in a read transaction on a
        READ-access session, so the server refuses any write whatever the text says. The allowlist
        policy is a second layer that refuses procedures, admin commands and unbounded traversals
        before anything is sent. A transaction timeout bounds the cost.
        """
        from core.config import get_settings
        from core.cypher_policy import require_read_only

        require_read_only(cypher)

        driver = self.connect()
        database = self._database_name()
        timeout = float(get_settings().get("query_timeout_seconds", 30))

        # The timeout belongs to the TRANSACTION (unit_of_work). A Query(timeout=...) object is only accepted by
        # session.run, not by tx.run inside execute_read, and fails against a real server (found by the live
        # Neo4j Desktop verification; a recording fake driver accepts it).
        @unit_of_work(timeout=timeout)
        def read(tx):
            return [record for record in tx.run(cypher)]

        try:
            with driver.session(database=database, default_access_mode=READ_ACCESS) as session:
                records = session.execute_read(read)
        except ClientError as exc:
            if "TransactionTimedOut" in (exc.code or ""):  # the DATABASE terminated it: a controlled 504, not a driver message
                raise TimeoutError(f"Cypher query exceeded the {timeout:g}-second limit and was terminated by the database") from None
            raise
        finally:
            driver.close()

        results = []
        for record in records:
            row = {}
            for key in record.keys():
                value = record[key]
                try:
                    row[key] = dict(value.items()) if hasattr(value, "items") else str(value)
                except Exception:
                    row[key] = str(value)
            results.append(row)
        return results

    # =================================================
    # SPARQL → CYPHER → EXECUTE
    # =================================================

    def query(

        self,

        sparql: str

    ) -> Dict:

        cypher_result = (

            self.generate_cypher(

                sparql
            )
        )

        cypher = (

            cypher_result[
                "cypher"
            ]
        )

        neo4j_results = (

            self.execute_cypher(

                cypher
            )
        )

        return {

            "sparql":

                sparql,

            "parsed":

                cypher_result[
                    "parsed"
                ],

            "generated_cypher":

                cypher,

            "results":

                neo4j_results
        }

    # =================================================
    # HEALTH CHECK
    # =================================================

    def health(self):

        driver = self.connect()

        database = self._database_name()

        with driver.session(

            database=database

        ) as session:

            count = session.run(

                """

                MATCH (n)

                RETURN count(n)

                    AS count

                """

            ).single()["count"]

        driver.close()

        return {

            "database":

                database,

            "nodes":

                count,

            "status":

                "healthy"
        }


# =====================================================
# STANDALONE TEST
# =====================================================

if __name__ == "__main__":

    translator = (

        SparqlToCypher()
    )

    sparql = """

PREFIX hc:
<http://example.org/
healthcare-hospital.owl#>

SELECT ?patient

WHERE {

    ?patient
        hc:hasDiagnosis
        ?diagnosis .

    ?diagnosis
        hc:diagnosisName
        "Hypertension" .

}

"""

    result = (

        translator

        .generate_cypher(

            sparql
        )
    )

    print(

        "\nParsed:\n"
    )

    print(

        result["parsed"]
    )

    print(

        "\nCypher:\n"
    )

    print(

        result["cypher"]
    )

