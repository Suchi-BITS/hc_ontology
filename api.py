from dotenv import load_dotenv

load_dotenv()

from email import generator

from fastapi import FastAPI, HTTPException, Query
from typing import List, Dict, Any

from httpx import request

from load_ontology import HealthcareOntology

# =====================================================
# APP
# =====================================================

app = FastAPI(
    title="Healthcare Ontology API",
    description="""
    Production Healthcare Ontology Service

    Source:
    OWL Ontology -> Owlready2 -> FastAPI
    """,
    version="1.0.0"
)

# =====================================================
# LOAD ONTOLOGY
# =====================================================

ontology = HealthcareOntology()

# =====================================================
# HEALTH CHECK
# =====================================================

@app.get(
    "/",
    tags=["System"]
)
def home():

    return {
        "service": "Healthcare Ontology API",
        "status": "running",
        "ontology_loaded": True
    }


@app.get(
    "/health",
    tags=["System"]
)
def health():

    return {
        "status": "healthy"
    }

# =====================================================
# METADATA
# =====================================================

@app.get(
    "/classes",
    tags=["Ontology"]
)
def get_classes():

    return ontology.get_classes()


@app.get(
    "/object-properties",
    tags=["Ontology"]
)
def get_object_properties():

    return ontology.get_object_properties()


@app.get(
    "/data-properties",
    tags=["Ontology"]
)
def get_data_properties():

    return ontology.get_data_properties()


@app.get(
    "/individuals",
    tags=["Ontology"]
)
def get_individuals():

    return ontology.get_individuals()

# =====================================================
# PATIENTS
# =====================================================

@app.get(
    "/patients",
    tags=["Patients"]
)
def get_patients():

    return ontology.get_patients()


@app.get(
    "/patients/{patient_name}",
    tags=["Patients"]
)
def get_patient(
    patient_name: str
):

    patients = ontology.get_patients()

    for patient in patients:

        if patient["name"] == patient_name:
            return patient

    raise HTTPException(
        status_code=404,
        detail="Patient not found"
    )

# =====================================================
# DOCTORS
# =====================================================

@app.get(
    "/doctors",
    tags=["Doctors"]
)
def get_doctors():

    return ontology.get_doctors()


@app.get(
    "/doctors/{doctor_name}",
    tags=["Doctors"]
)
def get_doctor(
    doctor_name: str
):

    doctors = ontology.get_doctors()

    for doctor in doctors:

        if doctor["name"] == doctor_name:
            return doctor

    raise HTTPException(
        status_code=404,
        detail="Doctor not found"
    )

# =====================================================
# APPOINTMENTS
# =====================================================

@app.get(
    "/appointments",
    tags=["Appointments"]
)
def get_appointments():

    return ontology.get_appointments()

# =====================================================
# DIAGNOSES
# =====================================================

@app.get(
    "/diagnoses",
    tags=["Diagnosis"]
)
def get_diagnoses():

    return ontology.get_diagnoses()

# =====================================================
# TREATMENTS
# =====================================================

@app.get(
    "/treatments",
    tags=["Treatment"]
)
def get_treatments():

    return ontology.get_treatments()

# =====================================================
# GENERIC INSTANCE LOOKUP
# =====================================================

@app.get(
    "/instances/{class_name}",
    tags=["Ontology"]
)
def get_instances(
    class_name: str
):

    instances = ontology.get_instances(
        class_name
    )

    if not instances:

        raise HTTPException(
            status_code=404,
            detail=f"No instances found for {class_name}"
        )

    return instances

# =====================================================
# SEARCH
# =====================================================

@app.get(
    "/search",
    tags=["Search"]
)
def search(
    q: str = Query(
        ...,
        description="Search ontology individuals"
    )
):

    return {
        "query": q,
        "results": ontology.search(q)
    }

# Patient -> Diagnosis traversal
@app.get(
    "/patients/{patient_name}/diagnoses",
    tags=["Graph Traversal"]
)
def patient_diagnoses(
    patient_name: str
):

    result = ontology.get_patient_diagnoses(
        patient_name
    )

    if result is None:

        raise HTTPException(
            status_code=404,
            detail="Patient not found"
        )

    return result

@app.get(
    "/patients/{patient_name}/treatments",
    tags=["Graph Traversal"]
)
def patient_treatments(
    patient_name: str
):

    result = ontology.get_patient_treatments(
        patient_name
    )

    if result is None:

        raise HTTPException(
            status_code=404,
            detail="Patient not found"
        )

    return result

@app.get(
    "/doctors/{doctor_name}/patients",
    tags=["Graph Traversal"]
)
def doctor_patients(
    doctor_name: str
):

    result = ontology.get_doctor_patients(
        doctor_name
    )

    if result is None:

        raise HTTPException(
            status_code=404,
            detail="Doctor not found"
        )

    return result

@app.get(
    "/rdf/triples",
    tags=["Knowledge Graph"]
)
def rdf_triples():

    return ontology.get_rdf_triples()
# =====================================================
# STATS
# =====================================================

@app.get(
    "/stats",
    tags=["System"]
)
def stats():

    return {

        "classes":
            len(
                ontology.get_classes()
            ),

        "individuals":
            len(
                ontology.get_individuals()
            ),

        "object_properties":
            len(
                ontology.get_object_properties()
            ),

        "data_properties":
            len(
                ontology.get_data_properties()
            )
    }

# =====================================================
# HOSPITAL GRAPH SUMMARY
# =====================================================

@app.get(
    "/graph-summary",
    tags=["Knowledge Graph"]
)
def graph_summary():

    return {

        "patients":
            len(
                ontology.get_instances(
                    "Patient"
                )
            ),

        "doctors":
            len(
                ontology.get_instances(
                    "Doctor"
                )
            ),

        "appointments":
            len(
                ontology.get_instances(
                    "Appointment"
                )
            ),

        "diagnoses":
            len(
                ontology.get_instances(
                    "Diagnosis"
                )
            ),

        "treatments":
            len(
                ontology.get_instances(
                    "Treatment"
                )
            )
    }

from pydantic import BaseModel

class SparqlRequest(
    BaseModel
):

    query: str

@app.post(
    "/sparql",
    tags=["SPARQL"]
)
def sparql_query(
    request: SparqlRequest
):

    return ontology.execute_sparql(
        request.query
    )

@app.get(
    "/neo4j/export",
    tags=["Neo4j"]
)
def neo4j_export():

    return {

        "cypher":
            ontology.export_neo4j_cypher()
    }


from pydantic import BaseModel

class NLQueryRequest(
    BaseModel
):

    question: str


from sparql_generator import SparqlGenerator

generator = SparqlGenerator(
    ontology, model_name="qwen2.5:latest"
)


from pydantic import BaseModel

class LLMQueryRequest(
    BaseModel
):

    question: str

@app.post(
    "/llm-query",
    tags=["LLM + SPARQL"]
)
def llm_query(
    request: LLMQueryRequest
):

    try:
        return generator.generate_and_validate(
            request.question
        )
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )

@app.post(
    "/nl-query",
    tags=["Natural Language"]
)
def nl_query(
    request: NLQueryRequest
):

    return generator.generate_and_validate(

        request.question
    )
# @app.post(
#     "/nl-query"
# )
# def nl_query(
#     request
# ):

#     sparql = generator.generate(
#         request.question
#     )

#     result = ontology.execute_sparql(
#         sparql
#     )

#     return {

#         "question":
#             request.question,

#         "generated_sparql":
#             sparql,

#         "result":
#             result
#     }

from sparql_to_cypher import (
    SparqlToCypher
)
from cypher_generator import CypherGenerator

translator = (
    SparqlToCypher()
)
cypher_generator = CypherGenerator(
    ontology,
    model_name="qwen2.5:latest"
)
class SparqlCypherRequest(
    BaseModel
):

    query: str
@app.post(
    "/sparql-to-cypher",
    tags=["Neo4j"]
)
def sparql_to_cypher(
        request: SparqlCypherRequest
):

    try:
        return translator.query(
            request.query
        )
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )

@app.get(
    "/neo4j/health",
    tags=["Neo4j"]
)
def neo4j_health():

    try:
        return translator.health()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )


class ExecuteCypherRequest(
    BaseModel
):

    cypher: str


@app.post(
    "/nl-to-cypher",
    tags=["Neo4j"]
)
def nl_to_cypher(
    request: NLQueryRequest
):

    try:
        return cypher_generator.generate_response(
            request.question
        )
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )


@app.post(
    "/execute-cypher",
    tags=["Neo4j"]
)
def execute_cypher(
    request: ExecuteCypherRequest
):

    try:
        return {
            "results": translator.execute_cypher(
                request.cypher
            )
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )


from embedding_service import EmbeddingService
#from embedding_service import OntologyService


embedding_service = EmbeddingService(

    ontology_path="healthcare_ontology.owl"

)


@app.post(
    "/embedding/sync",
    tags=["Embeddings"]
)
def embedding_sync():

    try:
        result = embedding_service.synchronize_embeddings()

        status = (
            "success"
            if result["failed"] == 0
            else "completed_with_errors"
        )

        return {
            "status": status,
            "processed": result["successful"],
            "failed": result["failed"]
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )


@app.get(
    "/embedding/health",
    tags=["Embeddings"]
)
def embedding_health():

    try:
        health = embedding_service.health()

        if health.get("status") != "healthy":
            raise HTTPException(
                status_code=503,
                detail=health.get("error", "Embedding service unhealthy")
            )

        return {
            "status": health["status"],
            "model": health["model"],
            "dimensions": health["dimensions"]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )


@app.get(
    "/embedding/search",
    tags=["Embeddings"]
)
def embedding_search(
    query: str = Query(
        ...,
        description="Search ontology concepts by meaning"
    ),
    top_k: int = Query(
        5,
        ge=1,
        le=100,
        description="Number of results to return"
    )
):

    try:
        response = embedding_service.handle_search_request(
            query=query,
            top_k=top_k
        )

        if response.get("status") == "error":
            raise HTTPException(
                status_code=503,
                detail=response.get("error", "Search failed")
            )

        return response["results"]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )


@app.get(
    "/embedding/similar/{concept}",
    tags=["Embeddings"]
)
def embedding_similar(
    concept: str,
    top_k: int = Query(
        5,
        ge=1,
        le=100,
        description="Number of similar concepts to return"
    )
):

    try:
        return embedding_service.find_similar_concepts(
            node_name=concept,
            top_k=top_k
        )
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )


@app.get("/health")
def health():

    return embedding_service.api_health()


@app.get("/search")
def search(

    query: str,
    top_k: int = 5

):

    return embedding_service.handle_search_request(

        query=query,

        top_k=top_k
    )


@app.get("/similar/{concept}")
def similar(

    concept: str,
    top_k: int = 5

):

    return embedding_service.find_similar_concepts(

        node_name=concept,

        top_k=top_k
    )
# =====================================================
# START
# =====================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
