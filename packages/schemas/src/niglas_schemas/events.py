"""Ingestion event contracts (envelope version 1).

An :class:`EventEnvelope` is the only shape the ingestion layer accepts. It carries
routing and idempotency metadata plus exactly one typed payload, discriminated by
``event_type``. Payloads are deliberately flat and dimension-rich: the analytics and
anomaly layers localise deviations by dimension (platform, payment method, region,
plan tier, app version), so those dimensions must be present on the raw event.
"""

from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from niglas_schemas.enums import (
    Currency,
    DeploymentStatus,
    EventType,
    PaymentMethod,
    PaymentStatus,
    PlanTier,
    Platform,
    Region,
)
from niglas_schemas.types import AmountMinor, IdempotencyKey, ShortName, UtcDatetime

SCHEMA_VERSION: Final[Literal[1]] = 1
"""Version of the event envelope itself."""


class _Contract(BaseModel):
    """Base for wire contracts: reject unknown fields, forbid mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SessionEventPayload(_Contract):
    """One user session and how far it progressed through the purchase funnel.

    The funnel flags are cumulative: ``converted`` implies ``reached_payment``, which
    implies ``reached_checkout``. This invariant is enforced here so that no
    downstream funnel calculation has to defend against impossible sessions.
    """

    event_type: Literal[EventType.SESSION] = EventType.SESSION
    payload_version: Literal[1] = 1
    session_id: UUID
    customer_id: UUID | None = None
    platform: Platform
    region: Region
    plan_tier: PlanTier
    app_version: ShortName
    started_at: UtcDatetime
    duration_ms: int = Field(ge=0)
    reached_checkout: bool
    reached_payment: bool
    converted: bool

    @model_validator(mode="after")
    def _funnel_is_monotonic(self) -> "SessionEventPayload":
        if self.converted and not self.reached_payment:
            raise ValueError("converted session must have reached_payment")
        if self.reached_payment and not self.reached_checkout:
            raise ValueError("session reaching payment must have reached_checkout")
        return self


class ProductEventPayload(_Contract):
    """A named in-product action, used for behavioural analysis and event sampling."""

    event_type: Literal[EventType.PRODUCT_EVENT] = EventType.PRODUCT_EVENT
    payload_version: Literal[1] = 1
    session_id: UUID
    customer_id: UUID | None = None
    name: ShortName
    platform: Platform
    properties: dict[str, str | int | float | bool] = Field(default_factory=dict)


class OrderLine(_Contract):
    product_sku: ShortName
    quantity: int = Field(ge=1)
    unit_amount_minor: AmountMinor


class OrderEventPayload(_Contract):
    """A placed order. ``total_amount_minor`` must equal the sum of its lines."""

    event_type: Literal[EventType.ORDER] = EventType.ORDER
    payload_version: Literal[1] = 1
    order_id: UUID
    session_id: UUID
    customer_id: UUID
    currency: Currency
    total_amount_minor: AmountMinor
    lines: list[OrderLine] = Field(min_length=1)

    @model_validator(mode="after")
    def _total_matches_lines(self) -> "OrderEventPayload":
        expected = sum(line.quantity * line.unit_amount_minor for line in self.lines)
        if expected != self.total_amount_minor:
            raise ValueError(
                f"total_amount_minor {self.total_amount_minor} does not match line sum {expected}"
            )
        return self


class PaymentEventPayload(_Contract):
    """One payment attempt. Failed attempts must carry a failure code.

    ``attempt_number`` starts at 1 and lets the impact engine distinguish a customer
    who retried successfully from one who abandoned.
    """

    event_type: Literal[EventType.PAYMENT] = EventType.PAYMENT
    payload_version: Literal[1] = 1
    payment_id: UUID
    order_id: UUID | None = None
    session_id: UUID
    customer_id: UUID
    method: PaymentMethod
    status: PaymentStatus
    failure_code: ShortName | None = None
    amount_minor: AmountMinor
    currency: Currency
    attempt_number: int = Field(ge=1)
    platform: Platform
    app_version: ShortName

    @model_validator(mode="after")
    def _failure_code_matches_status(self) -> "PaymentEventPayload":
        if self.status is PaymentStatus.FAILED and self.failure_code is None:
            raise ValueError("failed payment must carry a failure_code")
        if self.status is PaymentStatus.SUCCEEDED:
            if self.failure_code is not None:
                raise ValueError("succeeded payment must not carry a failure_code")
            if self.order_id is None:
                raise ValueError("succeeded payment must reference an order_id")
        return self


class DeploymentEventPayload(_Contract):
    """A code deployment, correlated against metric changes by the evidence layer."""

    event_type: Literal[EventType.DEPLOYMENT] = EventType.DEPLOYMENT
    payload_version: Literal[1] = 1
    deployment_id: UUID
    service: ShortName
    version: ShortName
    status: DeploymentStatus
    commit_sha: Annotated[str, Field(min_length=7, max_length=40)]
    description: str = Field(default="", max_length=500)


EventPayload = Annotated[
    SessionEventPayload
    | ProductEventPayload
    | OrderEventPayload
    | PaymentEventPayload
    | DeploymentEventPayload,
    Field(discriminator="event_type"),
]


class EventEnvelope(_Contract):
    """The single shape accepted by the ingestion layer.

    ``idempotency_key`` is unique per organization: re-submitting the same key is a
    no-op, which makes producer retries safe (see ``docs/ARCHITECTURE.md``).
    """

    schema_version: Literal[1] = SCHEMA_VERSION
    event_id: UUID
    organization_id: UUID
    event_type: EventType
    occurred_at: UtcDatetime
    idempotency_key: IdempotencyKey
    payload: EventPayload

    @model_validator(mode="after")
    def _payload_matches_event_type(self) -> "EventEnvelope":
        if self.payload.event_type is not self.event_type:
            raise ValueError(
                f"event_type {self.event_type} does not match payload "
                f"type {self.payload.event_type}"
            )
        return self
