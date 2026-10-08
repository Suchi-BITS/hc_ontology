from fastapi import APIRouter, Depends

from core.auth import verify_api_key
from core.authz import Permission, require_permission
from core.dependencies import get_ontology

router = APIRouter(tags=["Clinical"], dependencies=[Depends(verify_api_key), Depends(require_permission(Permission.CLINICAL_READ))])


@router.get("/appointments")
def get_appointments():
    return get_ontology().get_appointments()


@router.get("/diagnoses")
def get_diagnoses():
    return get_ontology().get_diagnoses()


@router.get("/treatments")
def get_treatments():
    return get_ontology().get_treatments()
