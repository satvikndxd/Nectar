from datetime import UTC, datetime
from uuid import UUID, uuid4

from niglas_api.metrics import compute_funnel_metrics
from niglas_schemas.enums import (
    Currency,
    PaymentMethod,
    PaymentStatus,
    PlanTier,
    Platform,
    Region,
)
from niglas_schemas.events import (
    EventEnvelope,
    OrderEventPayload,
    OrderLine,
    PaymentEventPayload,
    SessionEventPayload,
)

ORG_ID = uuid4()
OCCURRED_AT = datetime(2026, 9, 24, 12, tzinfo=UTC)


def envelope(payload: object, organization_id: UUID = ORG_ID) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid4(),
        organization_id=organization_id,
        event_type=payload.event_type,  # type: ignore[attr-defined]
        occurred_at=OCCURRED_AT,
        idempotency_key=f"{payload.event_type}:{uuid4()}",  # type: ignore[attr-defined]
        payload=payload,
    )


def session_payload(*, reached_payment: bool, converted: bool) -> SessionEventPayload:
    return SessionEventPayload(
        session_id=uuid4(),
        customer_id=uuid4(),
        platform=Platform.ANDROID,
        region=Region.EU,
        plan_tier=PlanTier.PRO,
        app_version="2.8.0",
        started_at=OCCURRED_AT,
        duration_ms=1200,
        reached_checkout=True,
        reached_payment=reached_payment,
        converted=converted,
    )


def test_compute_funnel_metrics_counts_sessions_payments_and_revenue() -> None:
    customer_id = uuid4()
    session_id = uuid4()
    order_id = uuid4()
    events = [
        envelope(session_payload(reached_payment=True, converted=True)),
        envelope(session_payload(reached_payment=False, converted=False)),
        envelope(
            PaymentEventPayload(
                payment_id=uuid4(),
                order_id=order_id,
                session_id=session_id,
                customer_id=customer_id,
                method=PaymentMethod.VISA,
                status=PaymentStatus.SUCCEEDED,
                amount_minor=7900,
                currency=Currency.USD,
                attempt_number=1,
                platform=Platform.ANDROID,
                app_version="2.8.0",
            )
        ),
        envelope(
            PaymentEventPayload(
                payment_id=uuid4(),
                order_id=None,
                session_id=session_id,
                customer_id=customer_id,
                method=PaymentMethod.VISA,
                status=PaymentStatus.FAILED,
                failure_code="do_not_honor",
                amount_minor=7900,
                currency=Currency.USD,
                attempt_number=2,
                platform=Platform.ANDROID,
                app_version="2.8.0",
            )
        ),
        envelope(
            OrderEventPayload(
                order_id=order_id,
                session_id=session_id,
                customer_id=customer_id,
                currency=Currency.USD,
                total_amount_minor=7900,
                lines=[
                    OrderLine(
                        product_sku="team-seat",
                        quantity=1,
                        unit_amount_minor=7900,
                    )
                ],
            )
        ),
    ]

    metrics = compute_funnel_metrics(events)

    assert metrics.total_sessions == 2
    assert metrics.checkout_sessions == 2
    assert metrics.payment_sessions == 1
    assert metrics.converted_sessions == 1
    assert metrics.payment_attempts == 2
    assert metrics.failed_payments == 1
    assert metrics.revenue_minor == 7900
    assert metrics.conversion_rate == 0.5
    assert metrics.payment_failure_rate == 0.5


def test_empty_funnel_metrics_have_zero_rates() -> None:
    metrics = compute_funnel_metrics([])

    assert metrics.total_sessions == 0
    assert metrics.checkout_rate == 0.0
    assert metrics.payment_rate == 0.0
    assert metrics.conversion_rate == 0.0
    assert metrics.payment_failure_rate == 0.0
