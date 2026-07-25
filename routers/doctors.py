from fastapi import APIRouter, Depends, HTTPException

from core.auth import verify_api_key
from core.dependencies import get_ontology

router = APIRouter(tags=["Doctors"], dependencies=[Depends(verify_api_key)])


@router.get("/doctors")
def get_doctors():
    return get_ontology().get_doctors()


@router.get("/doctors/{doctor_name}")
def get_doctor(doctor_name: str):
    for doctor in get_ontology().get_doctors():
        if doctor["name"] == doctor_name:
            return doctor
    raise HTTPException(status_code=404, detail="Doctor not found")


@router.get("/doctors/{doctor_name}/patients")
def doctor_patients(doctor_name: str):
    result = get_ontology().get_doctor_patients(doctor_name)
    if result is None:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return result
