"""Multi-tenancy context and tenant registry."""

from __future__ import annotations

import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import Header, HTTPException, Request

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
    """In-memory tenant catalog (swap for DB in production)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tenants: dict[str, TenantContext] = {
            "default": TenantContext(
                tenant_id="default",
                display_name="Default Healthcare Tenant",
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
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
) -> TenantContext:
    from core.config import get_settings

    tenant_id = x_tenant_id or request.query_params.get("tenant_id") or get_settings().get(
        "default_tenant_id", "default"
    )
    tenant = tenant_registry.get(tenant_id)
    if tenant is None or not tenant.active:
        raise HTTPException(status_code=404, detail=f"Unknown or inactive tenant: {tenant_id}")
    set_current_tenant(tenant)
    request.state.tenant = tenant
    return tenant
