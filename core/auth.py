"""Authentication dependency used by every router.

``verify_api_key`` keeps its historical name so router wiring did not change, but it no longer compares
one shared key: it resolves the caller's server-side Identity (core/security.py) and answers 401 if
there is none. See docs/security-architecture.md.
"""

from fastapi import Depends

from core.security import Identity, authenticate_request


async def verify_api_key(identity: Identity = Depends(authenticate_request)) -> Identity:
    return identity
