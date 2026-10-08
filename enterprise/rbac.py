"""RBAC - compatibility import path. The implementation lives in core/authz.py.

Roles are NOT read from the request. They come from the server-side credential record that
core/security.py resolved for the caller. See docs/security-architecture.md.
"""

from __future__ import annotations

from core.authz import (  # noqa: F401
    LEAST_PRIVILEGE_ROLE,
    ROLE_PERMISSIONS,
    Permission,
    Principal,
    get_principal,
    principal_for,
    require_permission,
)
