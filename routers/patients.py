from fastapi import APIRouter, Depends, HTTPException

from core.auth import verify_api_key
from core.authz import Permission, require_permission
from core.dependencies import get_ontology

router = APIRouter(tags=["Patients"], dependencies=[Depends(verify_api_key), Depends(require_permission(Permission.CLINICAL_READ))])


@router.get("/patients")
def get_patients():
    return get_ontology().get_patients()


@router.get("/patients/{patient_name}")
def get_patient(patient_name: str):
    for patient in get_ontology().get_patients():
        if patient["name"] == patient_name:
            return patient
    raise HTTPException(status_code=404, detail="Patient not found")


@router.get("/patients/{patient_name}/diagnoses")
def patient_diagnoses(patient_name: str):
    result = get_ontology().get_patient_diagnoses(patient_name)
    if result is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return result


@router.get("/patients/{patient_name}/treatments")
def patient_treatments(patient_name: str):
    result = get_ontology().get_patient_treatments(patient_name)
    if result is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return result
