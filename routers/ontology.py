from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import verify_api_key
from core.dependencies import get_ontology

router = APIRouter(tags=["Ontology"], dependencies=[Depends(verify_api_key)])


@router.get("/classes")
def get_classes():
    return get_ontology().get_classes()


@router.get("/object-properties")
def get_object_properties():
    return get_ontology().get_object_properties()


@router.get("/data-properties")
def get_data_properties():
    return get_ontology().get_data_properties()


@router.get("/individuals")
def get_individuals():
    return get_ontology().get_individuals()


@router.get("/instances/{class_name}")
def get_instances(class_name: str):
    instances = get_ontology().get_instances(class_name)
    if not instances:
        raise HTTPException(
            status_code=404,
            detail=f"No instances found for {class_name}",
        )
    return instances


@router.get("/search")
def search_ontology(
    q: str = Query(..., description="Search ontology individuals by name"),
):
    return {"query": q, "results": get_ontology().search(q)}


@router.get("/rdf/triples")
def rdf_triples():
    return get_ontology().get_rdf_triples()


@router.get("/graph-summary")
def graph_summary():
    ontology = get_ontology()
    return {
        "patients": len(ontology.get_instances("Patient")),
        "doctors": len(ontology.get_instances("Doctor")),
        "appointments": len(ontology.get_instances("Appointment")),
        "diagnoses": len(ontology.get_instances("Diagnosis")),
        "treatments": len(ontology.get_instances("Treatment")),
    }
