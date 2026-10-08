"""Metric calculations over ingested event envelopes."""

from collections.abc import Sequence
from dataclasses import dataclass

from niglas_schemas.enums import EventType, PaymentStatus
from niglas_schemas.events import (
    EventEnvelope,
    OrderEventPayload,
    PaymentEventPayload,
    SessionEventPayload,
)


@dataclass(frozen=True, slots=True)
class FunnelMetrics:
    total_sessions: int
    checkout_sessions: int
    payment_sessions: int
    converted_sessions: int
    payment_attempts: int
    failed_payments: int
    revenue_minor: int

    @property
    def checkout_rate(self) -> float:
        return _ratio(self.checkout_sessions, self.total_sessions)

    @property
    def payment_rate(self) -> float:
        return _ratio(self.payment_sessions, self.checkout_sessions)

    @property
    def conversion_rate(self) -> float:
        return _ratio(self.converted_sessions, self.total_sessions)

    @property
    def payment_failure_rate(self) -> float:
        return _ratio(self.failed_payments, self.payment_attempts)


def _ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def compute_funnel_metrics(events: Sequence[EventEnvelope]) -> FunnelMetrics:
    """Compute high-level funnel health from raw ingestion events."""
    total_sessions = 0
    checkout_sessions = 0
    payment_sessions = 0
    converted_sessions = 0
    payment_attempts = 0
    failed_payments = 0
    revenue_minor = 0

    for event in events:
        if event.event_type is EventType.SESSION:
            payload = event.payload
            if not isinstance(payload, SessionEventPayload):
                continue
            total_sessions += 1
            checkout_sessions += int(payload.reached_checkout)
            payment_sessions += int(payload.reached_payment)
            converted_sessions += int(payload.converted)
        elif event.event_type is EventType.PAYMENT:
            payload = event.payload
            if not isinstance(payload, PaymentEventPayload):
                continue
            payment_attempts += 1
            failed_payments += int(payload.status is PaymentStatus.FAILED)
        elif event.event_type is EventType.ORDER:
            payload = event.payload
            if not isinstance(payload, OrderEventPayload):
                continue
            revenue_minor += payload.total_amount_minor

    return FunnelMetrics(
        total_sessions=total_sessions,
        checkout_sessions=checkout_sessions,
        payment_sessions=payment_sessions,
        converted_sessions=converted_sessions,
        payment_attempts=payment_attempts,
        failed_payments=failed_payments,
        revenue_minor=revenue_minor,
    )
