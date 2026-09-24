"""Framework-free domain logic shared across Niglas services.

Nothing in this package imports FastAPI, SQLAlchemy, an HTTP client or an LLM SDK.
That constraint is enforced in CI by import-linter (see ``.importlinter``) and is what
makes the rules here - money arithmetic, time windows, permissions - testable in
isolation and reusable by the API, the workers and the agent tool layer alike.
"""

from niglas_shared.clock import Clock, FixedClock, SystemClock
from niglas_shared.errors import AuthorizationError, DomainError, NiglasError
from niglas_shared.ids import uuid7, uuid7_timestamp
from niglas_shared.money import Money, sum_money
from niglas_shared.rbac import ROLE_PERMISSIONS, Permission, Principal, permissions_for
from niglas_shared.timewindow import TimeWindow

__all__ = [
    "ROLE_PERMISSIONS",
    "AuthorizationError",
    "Clock",
    "DomainError",
    "FixedClock",
    "Money",
    "NiglasError",
    "Permission",
    "Principal",
    "SystemClock",
    "TimeWindow",
    "permissions_for",
    "sum_money",
    "uuid7",
    "uuid7_timestamp",
]
