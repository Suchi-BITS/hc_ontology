"""Authorization: WHAT an authenticated identity may do.

Roles are resolved on the server, from the Identity created by core/security.py. A role is never read
from the request. Permissions are checked at the route (``require_permission``); resource scope
(which tenant's data) is checked in enterprise/tenancy.py and in the services.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from fastapi import Depends, HTTPException

from core.config import get_settings
from core.security import Identity, authenticate_request, in_development

logger = logging.getLogger("healthcare_ontology.security")


class Permission(str, Enum):
    ONTOLOGY_READ = "ontology:read"
    ONTOLOGY_WRITE = "ontology:write"
    CLINICAL_READ = "clinical:read"      # individuals, patients, doctors, triples
    QUERY_EXECUTE = "query:execute"      # SPARQL, Cypher, natural-language queries
    GRAPH_WRITE = "graph:write"          # load the Neo4j projection, sync embeddings
    AGENT_RUN = "agent:run"
    AGENT_APPROVE = "agent:approve"
    AGENT_EVAL = "agent:eval"
    METRICS_READ = "metrics:read"
    WORKFLOW_RUN = "workflow:run"
    ADMIN = "admin:*"                    # administer one's own tenant
    PLATFORM_ADMIN = "platform:admin"    # create tenants, see all tenants (cross-tenant)


_READER = {Permission.ONTOLOGY_READ, Permission.CLINICAL_READ, Permission.METRICS_READ}
_ANALYST = _READER | {Permission.QUERY_EXECUTE, Permission.AGENT_RUN, Permission.AGENT_EVAL}
_APPROVER = (_ANALYST - {Permission.AGENT_EVAL}) | {Permission.AGENT_APPROVE}
_ADMIN = _ANALYST | {
    Permission.AGENT_APPROVE, Permission.ONTOLOGY_WRITE, Permission.GRAPH_WRITE, Permission.WORKFLOW_RUN,
    Permission.ADMIN,
}

# The trusted server-side mapping from role to permissions.
ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "viewer": set(_READER),
    "analyst": set(_ANALYST),
    "approver": set(_APPROVER),
    "admin": set(_ADMIN),
    "platform_admin": set(_ADMIN) | {Permission.PLATFORM_ADMIN},
}

LEAST_PRIVILEGE_ROLE = "viewer"


@dataclass
class Principal:
    """An Identity plus the permissions the server grants it."""

    subject: str
    role: str = LEAST_PRIVILEGE_ROLE
    tenant_id: str = ""
    permissions: set[Permission] = field(default_factory=set)
    display_name: str = ""

    def has(self, perm: Permission) -> bool:
        if Permission.ADMIN in self.permissions and perm not in (Permission.PLATFORM_ADMIN,):
            return True
        return perm in self.permissions


def principal_for(identity: Identity) -> Principal:
    role = identity.role if identity.role in ROLE_PERMISSIONS else LEAST_PRIVILEGE_ROLE
    if role != identity.role:
        logger.warning("unknown role %r for %s: granted %s", identity.role, identity.subject, role)
    return Principal(
        subject=identity.subject,
        role=role,
        tenant_id=identity.tenant_id,
        permissions=set(ROLE_PERMISSIONS[role]),
        display_name=identity.display_name,
    )


def get_principal(identity: Identity = Depends(authenticate_request)) -> Principal:
    return principal_for(identity)


def _authorization_enforced() -> bool:
    """RBAC can be switched off only in development/testing. In any other environment it is always on.
    The rule lives in core/security_policy.py."""
    from core.security import current_decision

    return current_decision().authorization_enforced


def require_permission(perm: Permission):
    def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        if not _authorization_enforced():
            return principal
        if not principal.has(perm):
            logger.warning("permission denied: %s lacks %s (role=%s tenant=%s)",
                           principal.subject, perm.value, principal.role, principal.tenant_id)
            raise HTTPException(
                status_code=403,
                detail=f"Role '{principal.role}' lacks permission {perm.value}",
            )
        return principal

    return _dep
