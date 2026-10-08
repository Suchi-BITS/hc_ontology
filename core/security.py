"""Authentication: WHO is calling. The only trusted source of identity and tenant.

Four ideas are kept apart on purpose (see docs/security-architecture.md):

    identity        who the caller is, and which tenant they belong to   <- this module
    authentication  proving the identity (API key -> server-side record) <- this module
    authorization   what that identity may do (role -> permissions)      <- core/authz.py
    tenant context  the data scope the identity may touch                <- enterprise/tenancy.py

Nothing the caller *sends* is trusted to say who they are. The role and the tenant are properties
of a server-side credential record; request headers such as ``X-Role`` and ``X-Tenant-ID`` are never
used to grant anything (a mismatching header is logged and ignored, or rejected for tenants).

The authenticator is an interface (``Authenticator``). Today there is one real implementation, API
keys looked up in a server-side credential store. OIDC/JWT can be added by implementing the same
interface without touching routers, authorization or tenancy.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fastapi import HTTPException, Request

from core.config import get_settings

logger = logging.getLogger("healthcare_ontology.security")

from core.security_policy import (  # noqa: E402  (the single authoritative policy; see that module)
    ENFORCED as _ENFORCED,
    NON_PRODUCTION_ENVIRONMENTS as DEVELOPMENT_ENVIRONMENTS,
    OPEN as _OPEN,
    UNCONFIGURED as _UNCONFIGURED,
    decide as _decide,
    is_non_production,
    refusal_message,
)

KEY_PREFIX = "hck_"


class SecurityConfigurationError(RuntimeError):
    """The deployment's security configuration is unsafe or incomplete."""


@dataclass(frozen=True)
class Identity:
    """An authenticated caller. Created only by an Authenticator, never from request data."""

    subject: str
    tenant_id: str
    role: str
    display_name: str = ""
    auth_method: str = "api-key"

    @property
    def label(self) -> str:
        return self.display_name or self.subject


class Authenticator(Protocol):
    def authenticate(self, request: Request) -> Identity | None:
        """Return the Identity for the credentials on the request, or None if none were presented.

        Raise AuthenticationFailed if credentials were presented but are invalid.
        """


class AuthenticationFailed(Exception):
    pass


# ---------------------------------------------------------------------------
# Credentials (server-side)
# ---------------------------------------------------------------------------

def hash_key(key: str) -> str:
    """SHA-256 of an API key. Keys are 256-bit random values, so a fast hash is appropriate
    (a slow password KDF protects low-entropy secrets; these have no such weakness)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def new_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


@dataclass(frozen=True)
class CredentialRecord:
    credential_id: str
    key_sha256: str
    tenant_id: str
    role: str
    display_name: str = ""


class CredentialStore:
    """API-key credentials loaded from a server-side JSON file (and the legacy API_KEY setting)."""

    def __init__(self, records: list[CredentialRecord]):
        self._records = records

    def __len__(self) -> int:
        return len(self._records)

    def find(self, presented_key: str) -> CredentialRecord | None:
        digest = hash_key(presented_key)
        match = None
        for record in self._records:  # always scan every record: no early exit on a match
            if hmac.compare_digest(record.key_sha256, digest):
                match = record
        return match

    @classmethod
    def load(cls) -> "CredentialStore":
        settings = get_settings()
        records: list[CredentialRecord] = []
        path = Path(settings.get("api_credentials_file") or "")
        if not path.is_absolute():
            path = Path(settings["project_root"]) / path
        if settings.get("api_credentials_file") and path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data.get("credentials", []):
                records.append(
                    CredentialRecord(
                        credential_id=item["id"],
                        key_sha256=item["key_sha256"],
                        tenant_id=item["tenant_id"],
                        role=item["role"],
                        display_name=item.get("display_name", ""),
                    )
                )
        legacy = settings.get("api_key") or ""
        if legacy:  # a single shared key: one server-side identity, least-privilege role by default
            records.append(
                CredentialRecord(
                    credential_id="shared-api-key",
                    key_sha256=hash_key(legacy),
                    tenant_id=settings["default_tenant_id"],
                    role=settings.get("api_key_role", "analyst"),
                    display_name="Shared API key",
                )
            )
        return cls(records)


class ApiKeyAuthenticator:
    """Authenticates ``X-API-Key: <key>`` or ``Authorization: Bearer <key>`` against the store."""

    def __init__(self, store: CredentialStore):
        self.store = store

    @staticmethod
    def presented_key(request: Request) -> str | None:
        key = request.headers.get("x-api-key")
        if key:
            return key.strip()
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return None

    def authenticate(self, request: Request) -> Identity | None:
        key = self.presented_key(request)
        if key is None:
            return None
        record = self.store.find(key)
        if record is None:
            raise AuthenticationFailed("unknown credential")
        return Identity(
            subject=record.credential_id,
            tenant_id=record.tenant_id,
            role=record.role,
            display_name=record.display_name,
            auth_method="api-key",
        )


class DevelopmentAuthenticator:
    """A fixed local identity for development. Only ever installed in development environments."""

    def authenticate(self, request: Request) -> Identity | None:
        settings = get_settings()
        return Identity(
            subject="local-developer",
            tenant_id=settings["default_tenant_id"],
            role="admin",
            display_name="Local developer (authentication disabled)",
            auth_method="development",
        )


# ---------------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------------

def in_development() -> bool:
    """True in development and testing environments; False in production and for any unknown name."""
    return is_non_production(get_settings().get("environment"))


def current_decision():
    settings = get_settings()
    return _decide(
        environment=settings.get("environment"),
        credentials_configured=len(_store()) > 0,
        allow_open_development_mode=bool(settings.get("allow_open_development_mode")),
        rbac_enabled=bool(settings.get("rbac_enabled", True)),
    )


_cache: dict = {}


def _store() -> CredentialStore:
    settings = get_settings()
    marker = (id(settings), _file_mtime(settings))
    if _cache.get("marker") != marker:
        _cache["marker"] = marker
        _cache["store"] = CredentialStore.load()
    return _cache["store"]


def _file_mtime(settings) -> float:
    name = settings.get("api_credentials_file")
    if not name:
        return 0.0
    path = Path(name) if Path(name).is_absolute() else Path(settings["project_root"]) / name
    return path.stat().st_mtime if path.is_file() else 0.0


def security_mode() -> str:
    """'enforced' | 'development-open' | 'unconfigured'.

    * enforced: at least one credential exists, so every request must authenticate.
    * development-open: no credentials, a development/testing environment AND the explicit opt-in
      ALLOW_OPEN_DEVELOPMENT_MODE=true: a fixed local identity.
    * unconfigured: anything else without credentials. Requests are refused and the application refuses
      to start (see validate_security_configuration).
    The decision itself is made by core/security_policy.py and nowhere else.
    """
    return current_decision().mode


def get_authenticator() -> Authenticator:
    mode = security_mode()
    if mode == "enforced":
        return ApiKeyAuthenticator(_store())
    if mode == "development-open":
        return DevelopmentAuthenticator()
    raise HTTPException(status_code=503, detail="Authentication is not configured on this server")


def validate_security_configuration() -> list[str]:
    """Called at startup. Raises in unsafe configurations; returns warnings otherwise."""
    decision = current_decision()
    if decision.mode == _UNCONFIGURED:
        raise SecurityConfigurationError(refusal_message(get_settings().get("environment")))
    return list(decision.warnings)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def authenticate_request(request: Request) -> Identity:
    """Dependency: resolve the caller's Identity (once per request) or answer 401."""
    existing = getattr(request.state, "identity", None)
    if existing is not None:
        return existing
    authenticator = get_authenticator()
    try:
        identity = authenticator.authenticate(request)
    except AuthenticationFailed as exc:
        logger.warning("authentication failed: %s (path=%s client=%s)", exc, request.url.path,
                       request.client.host if request.client else "unknown")
        raise HTTPException(status_code=401, detail="Invalid or missing credentials",
                            headers={"WWW-Authenticate": "Bearer"}) from exc
    if identity is None:
        logger.warning("authentication failed: no credentials (path=%s)", request.url.path)
        raise HTTPException(status_code=401, detail="Invalid or missing credentials",
                            headers={"WWW-Authenticate": "Bearer"})

    claimed_role = request.headers.get("x-role")
    if claimed_role and claimed_role.lower() != identity.role:
        logger.warning("ignored untrusted X-Role header %r from %s (granted role: %s)",
                       claimed_role, identity.subject, identity.role)
    request.state.identity = identity
    return identity


def request_identity(request: Request) -> Identity:
    """The Identity already established for this request (route must depend on authentication)."""
    identity = getattr(request.state, "identity", None)
    if identity is None:
        return authenticate_request(request)
    return identity
