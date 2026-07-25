import os

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from core.config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(_api_key_header)):
    """
    Optional API key protection.
    If API_KEY is not set in the environment, all requests are allowed.
    """
    expected = get_settings()["api_key"]
    if not expected:
        return None
    if api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key
