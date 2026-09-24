"""Role-based access control.

The permission matrix lives here, in framework-free code, for two reasons:

1. It is enforced twice - once by the HTTP API and later (Phase 4) again by the agent
   tool layer - and both must consult one definition, not two copies.
2. It is exhaustively unit-testable without a web server or a database.

Roles are *not* a simple hierarchy: an ``OPERATOR`` may execute an approved action but
may not approve one, and an ``APPROVER`` may approve but not execute. That separation
is the point of the human-in-the-loop design, so the matrix is written out explicitly
rather than derived from an ordering.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from niglas_schemas.enums import Role
from niglas_shared.errors import AuthorizationError


class Permission(StrEnum):
    """A single capability checked at a boundary."""

    METRICS_READ = "metrics:read"
    INCIDENTS_READ = "incidents:read"
    EVENTS_INGEST = "events:ingest"
    INVESTIGATION_RUN = "investigation:run"
    RECOMMENDATION_CREATE = "recommendation:create"
    APPROVAL_DECIDE = "approval:decide"
    ACTION_EXECUTE = "action:execute"
    AUDIT_READ = "audit:read"
    ORG_MANAGE = "org:manage"


_VIEWER: frozenset[Permission] = frozenset({Permission.METRICS_READ, Permission.INCIDENTS_READ})
_ANALYST: frozenset[Permission] = _VIEWER | {
    Permission.INVESTIGATION_RUN,
    Permission.RECOMMENDATION_CREATE,
}
_OPERATOR: frozenset[Permission] = _ANALYST | {
    Permission.ACTION_EXECUTE,
    Permission.EVENTS_INGEST,
}
_APPROVER: frozenset[Permission] = _ANALYST | {
    Permission.APPROVAL_DECIDE,
    Permission.AUDIT_READ,
}
_ADMIN: frozenset[Permission] = frozenset(Permission)

ROLE_PERMISSIONS: MappingProxyType[Role, frozenset[Permission]] = MappingProxyType(
    {
        Role.VIEWER: _VIEWER,
        Role.ANALYST: _ANALYST,
        Role.OPERATOR: _OPERATOR,
        Role.APPROVER: _APPROVER,
        Role.ADMIN: _ADMIN,
    }
)


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is acting, in which tenant, with which roles.

    ``organization_id`` is the *only* tenant scope any request may touch; the storage
    layer takes it from here rather than from a request body or query string, so a
    caller cannot ask for another tenant's data by editing a parameter.
    """

    subject_id: UUID
    organization_id: UUID
    roles: frozenset[Role] = field(default_factory=frozenset)
    is_service_account: bool = False

    @property
    def permissions(self) -> frozenset[Permission]:
        granted: frozenset[Permission] = frozenset()
        for role in self.roles:
            granted |= ROLE_PERMISSIONS[role]
        return granted

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions

    def require(self, permission: Permission) -> None:
        """Raise :class:`AuthorizationError` unless the principal holds ``permission``."""
        if not self.has(permission):
            raise AuthorizationError(
                f"principal {self.subject_id} lacks permission {permission.value}"
            )


def permissions_for(roles: Iterable[Role]) -> frozenset[Permission]:
    """Union of the permissions granted by ``roles``."""
    granted: frozenset[Permission] = frozenset()
    for role in roles:
        granted |= ROLE_PERMISSIONS[role]
    return granted
