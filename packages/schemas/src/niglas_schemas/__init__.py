"""Versioned cross-layer data contracts for Niglas.

Every payload that crosses a layer boundary (ingestion -> storage, storage -> API,
API -> web) is defined here so that producers and consumers share one definition.

Versioning policy
-----------------
``SCHEMA_VERSION`` is the version of the *event envelope*. Individual payload
models carry their own ``payload_version``. Additive, optional fields are a minor
change and do not bump a version; removing or re-typing a field does.
"""

from niglas_schemas.enums import (
    AuditAction,
    Currency,
    DeploymentStatus,
    EventType,
    OperatingStage,
    PaymentMethod,
    PaymentStatus,
    PlanTier,
    Platform,
    Region,
    Role,
    Severity,
)
from niglas_schemas.events import (
    SCHEMA_VERSION,
    DeploymentEventPayload,
    EventEnvelope,
    EventPayload,
    OrderEventPayload,
    OrderLine,
    PaymentEventPayload,
    ProductEventPayload,
    SessionEventPayload,
)

__all__ = [
    "SCHEMA_VERSION",
    "AuditAction",
    "Currency",
    "DeploymentEventPayload",
    "DeploymentStatus",
    "EventEnvelope",
    "EventPayload",
    "EventType",
    "OperatingStage",
    "OrderEventPayload",
    "OrderLine",
    "PaymentEventPayload",
    "PaymentMethod",
    "PaymentStatus",
    "PlanTier",
    "Platform",
    "ProductEventPayload",
    "Region",
    "Role",
    "SessionEventPayload",
    "Severity",
]
