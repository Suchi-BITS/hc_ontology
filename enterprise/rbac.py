"""RBAC — roles, permissions, and request enforcement."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from fastapi import Header, HTTPException, Security
from fastapi.security import APIKeyHeader

from core.config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class Permission(str, Enum):
    ONTOLOGY_READ = "ontology:read"
    ONTOLOGY_WRITE = "ontology:write"
    AGENT_RUN = "agent:run"
    AGENT_APPROVE = "agent:approve"
    AGENT_EVAL = "agent:eval"
    ADMIN = "admin:*"
    METRICS_READ = "metrics:read"
    WORKFLOW_RUN = "workflow:run"


ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "viewer": {Permission.ONTOLOGY_READ, Permission.METRICS_READ},
    "analyst": {
        Permission.ONTOLOGY_READ,
        Permission.AGENT_RUN,
        Permission.METRICS_READ,
        Permission.AGENT_EVAL,
    },
    "approver": {
        Permission.ONTOLOGY_READ,
        Permission.AGENT_RUN,
        Permission.AGENT_APPROVE,
        Permission.METRICS_READ,
    },
    "admin": {
        Permission.ONTOLOGY_READ,
        Permission.ONTOLOGY_WRITE,
        Permission.AGENT_RUN,
        Permission.AGENT_APPROVE,
        Permission.AGENT_EVAL,
        Permission.ADMIN,
        Permission.METRICS_READ,
        Permission.WORKFLOW_RUN,
    },
}


@dataclass
class Principal:
    subject: str
    role: str = "analyst"
    tenant_id: str = "default"
    api_key_present: bool = False
    permissions: set[Permission] = field(default_factory=set)

    def has(self, perm: Permission) -> bool:
        if Permission.ADMIN in self.permissions:
            return True
        return perm in self.permissions


async def get_principal(
    api_key: str | None = Security(_api_key_header),
    x_role: str | None = Header(default=None, alias="X-Role"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
) -> Principal:
    settings = get_settings()
    expected = settings.get("api_key") or ""
    if expected and api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    role = (x_role or "analyst").lower()
    if role not in ROLE_PERMISSIONS:
        role = "viewer"
    return Principal(
        subject=x_user_id or "anonymous",
        role=role,
        tenant_id=x_tenant_id or settings.get("default_tenant_id", "default"),
        api_key_present=bool(api_key),
        permissions=set(ROLE_PERMISSIONS[role]),
    )


def require_permission(perm: Permission):
    async def _dep(principal: Principal = Security(get_principal)) -> Principal:
        settings = get_settings()
        if not settings.get("rbac_enabled", True):
            return principal
        if not principal.has(perm):
            raise HTTPException(
                status_code=403,
                detail=f"Role '{principal.role}' lacks permission {perm.value}",
            )
        return principal

    return _dep
