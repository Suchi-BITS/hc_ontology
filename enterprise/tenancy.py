"""Tenant context: WHICH tenant's data the caller may touch.

The tenant is a property of the authenticated identity (core/security.py), never of the request. A
caller cannot select a tenant with a header or a query parameter. If a request names a tenant that is
not the caller's own (``X-Tenant-ID`` header or ``tenant_id`` query parameter), it is refused with 403
and logged, so a forged or confused client fails loudly instead of silently reading its own tenant.
"""

from __future__ import annotations

import logging
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request

from core.security import Identity, authenticate_request

logger = logging.getLogger("healthcare_ontology.security")

_tenant_ctx: ContextVar[Optional["TenantContext"]] = ContextVar("tenant_ctx", default=None)


@dataclass
class TenantContext:
    tenant_id: str
    display_name: str = ""
    ontology_ids: list[str] = field(default_factory=list)
    neo4j_database: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    active: bool = True


class TenantRegistry:
    """In-memory tenant catalog (swap for a database in production)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tenants: dict[str, TenantContext] = {
            "default": TenantContext(
                tenant_id="default",
                display_name="Default Healthcare Tenant",
                ontology_ids=["hc-core"],
            ),
            "abhigya-ai-lab": TenantContext(
                tenant_id="abhigya-ai-lab",
                display_name="Abhigya AI Lab",
                ontology_ids=["hc-core"],
            ),
            "clinic-a": TenantContext(
                tenant_id="clinic-a",
                display_name="Clinic A",
                ontology_ids=["hc-core", "hc-clinical-ext"],
            ),
            "research": TenantContext(
                tenant_id="research",
                display_name="Research Lab",
                ontology_ids=["hc-core", "hc-research"],
            ),
        }

    def get(self, tenant_id: str) -> TenantContext | None:
        with self._lock:
            return self._tenants.get(tenant_id)

    def list(self) -> list[TenantContext]:
        with self._lock:
            return list(self._tenants.values())

    def upsert(self, tenant: TenantContext) -> TenantContext:
        with self._lock:
            self._tenants[tenant.tenant_id] = tenant
            return tenant


tenant_registry = TenantRegistry()


def get_current_tenant() -> TenantContext | None:
    return _tenant_ctx.get()


def set_current_tenant(tenant: TenantContext | None):
    return _tenant_ctx.set(tenant)


def require_tenant(
    request: Request,
    identity: Identity = Depends(authenticate_request),
) -> TenantContext:
    """The caller's own tenant. A request that names another tenant is refused."""
    named = request.headers.get("x-tenant-id") or request.query_params.get("tenant_id")
    if named and named != identity.tenant_id:
        logger.warning("tenant mismatch refused: %s (tenant %s) asked for tenant %r on %s",
                       identity.subject, identity.tenant_id, named, request.url.path)
        raise HTTPException(
            status_code=403,
            detail="The requested tenant is not the tenant of the authenticated identity",
        )
    tenant = tenant_registry.get(identity.tenant_id)
    if tenant is None or not tenant.active:
        logger.warning("identity %s belongs to unknown or inactive tenant %s", identity.subject, identity.tenant_id)
        raise HTTPException(status_code=403, detail="The tenant of this identity is unknown or inactive")
    set_current_tenant(tenant)
    request.state.tenant = tenant
    return tenant
