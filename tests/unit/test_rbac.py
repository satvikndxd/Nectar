"""The permission matrix is the separation-of-duties guarantee; enumerate it."""

from uuid import uuid4

import pytest

from niglas_schemas.enums import Role
from niglas_shared.errors import AuthorizationError
from niglas_shared.rbac import ROLE_PERMISSIONS, Permission, Principal, permissions_for


def principal(*roles: Role) -> Principal:
    return Principal(subject_id=uuid4(), organization_id=uuid4(), roles=frozenset(roles))


def test_every_role_has_an_entry():
    assert set(ROLE_PERMISSIONS) == set(Role)


def test_viewer_can_only_read():
    viewer = principal(Role.VIEWER)
    assert viewer.has(Permission.METRICS_READ)
    assert viewer.has(Permission.INCIDENTS_READ)
    assert not viewer.has(Permission.INVESTIGATION_RUN)
    assert not viewer.has(Permission.EVENTS_INGEST)


def test_operator_may_execute_but_not_approve():
    operator = principal(Role.OPERATOR)
    assert operator.has(Permission.ACTION_EXECUTE)
    assert not operator.has(Permission.APPROVAL_DECIDE)


def test_approver_may_approve_but_not_execute():
    approver = principal(Role.APPROVER)
    assert approver.has(Permission.APPROVAL_DECIDE)
    assert not approver.has(Permission.ACTION_EXECUTE)


def test_separation_of_duties_holds_for_every_single_role():
    """No single role may both approve and execute; that pairing needs two people."""
    for role in Role:
        if role is Role.ADMIN:
            continue
        granted = ROLE_PERMISSIONS[role]
        assert not (
            Permission.APPROVAL_DECIDE in granted and Permission.ACTION_EXECUTE in granted
        ), f"role {role} can both approve and execute"


def test_admin_holds_every_permission():
    assert principal(Role.ADMIN).permissions == frozenset(Permission)


def test_roles_are_additive():
    combined = principal(Role.OPERATOR, Role.APPROVER)
    assert combined.has(Permission.ACTION_EXECUTE)
    assert combined.has(Permission.APPROVAL_DECIDE)
    assert combined.permissions == permissions_for([Role.OPERATOR, Role.APPROVER])


def test_principal_without_roles_has_nothing():
    assert principal().permissions == frozenset()


def test_require_raises_with_the_missing_permission_named():
    with pytest.raises(AuthorizationError, match="approval:decide"):
        principal(Role.VIEWER).require(Permission.APPROVAL_DECIDE)
