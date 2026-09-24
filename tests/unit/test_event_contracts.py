"""Ingestion contracts reject impossible events at the boundary, not downstream."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from niglas_schemas.enums import (
    Currency,
    EventType,
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

OCCURRED_AT = datetime(2026, 9, 24, 9, tzinfo=UTC)


def session_payload(**overrides: object) -> SessionEventPayload:
    defaults: dict[str, object] = {
        "session_id": uuid4(),
        "customer_id": uuid4(),
        "platform": Platform.ANDROID,
        "region": Region.EU,
        "plan_tier": PlanTier.PRO,
        "app_version": "2.8.0",
        "started_at": OCCURRED_AT,
        "duration_ms": 1000,
        "reached_checkout": True,
        "reached_payment": True,
        "converted": True,
    }
    return SessionEventPayload(**{**defaults, **overrides})  # type: ignore[arg-type]


def envelope(payload: object, **overrides: object) -> EventEnvelope:
    defaults: dict[str, object] = {
        "event_id": uuid4(),
        "organization_id": uuid4(),
        "event_type": payload.event_type,  # type: ignore[attr-defined]
        "occurred_at": OCCURRED_AT,
        "idempotency_key": "key-1",
        "payload": payload,
    }
    return EventEnvelope(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValidationError):
        session_payload(started_at=datetime(2026, 9, 24, 9))  # noqa: DTZ001


def test_non_utc_timestamps_are_normalised():
    tokyo = timezone(timedelta(hours=9))
    payload = session_payload(started_at=OCCURRED_AT.astimezone(tokyo))
    assert payload.started_at == OCCURRED_AT
    assert payload.started_at.tzinfo is UTC


def test_funnel_flags_must_be_monotonic():
    with pytest.raises(ValidationError, match="reached_payment"):
        session_payload(converted=True, reached_payment=False, reached_checkout=True)
    with pytest.raises(ValidationError, match="reached_checkout"):
        session_payload(converted=False, reached_payment=True, reached_checkout=False)


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        session_payload(sneaky_field="drop table")


def test_order_total_must_match_its_lines():
    lines = [OrderLine(product_sku="team-seat", quantity=2, unit_amount_minor=7900)]
    assert (
        OrderEventPayload(
            order_id=uuid4(),
            session_id=uuid4(),
            customer_id=uuid4(),
            currency=Currency.USD,
            total_amount_minor=15800,
            lines=lines,
        ).total_amount_minor
        == 15800
    )
    with pytest.raises(ValidationError, match="does not match line sum"):
        OrderEventPayload(
            order_id=uuid4(),
            session_id=uuid4(),
            customer_id=uuid4(),
            currency=Currency.USD,
            total_amount_minor=15799,
            lines=lines,
        )


def payment_payload(**overrides: object) -> PaymentEventPayload:
    defaults: dict[str, object] = {
        "payment_id": uuid4(),
        "order_id": uuid4(),
        "session_id": uuid4(),
        "customer_id": uuid4(),
        "method": PaymentMethod.VISA,
        "status": PaymentStatus.SUCCEEDED,
        "failure_code": None,
        "amount_minor": 7900,
        "currency": Currency.USD,
        "attempt_number": 1,
        "platform": Platform.ANDROID,
        "app_version": "2.8.0",
    }
    return PaymentEventPayload(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_failed_payment_must_explain_itself():
    with pytest.raises(ValidationError, match="failure_code"):
        payment_payload(status=PaymentStatus.FAILED, failure_code=None, order_id=None)
    assert (
        payment_payload(
            status=PaymentStatus.FAILED, failure_code="sdk_tokenization_error", order_id=None
        ).failure_code
        == "sdk_tokenization_error"
    )


def test_succeeded_payment_must_not_carry_a_failure_code_and_needs_an_order():
    with pytest.raises(ValidationError, match="must not carry"):
        payment_payload(failure_code="do_not_honor")
    with pytest.raises(ValidationError, match="order_id"):
        payment_payload(order_id=None)


def test_attempt_numbers_start_at_one():
    with pytest.raises(ValidationError):
        payment_payload(attempt_number=0)


def test_envelope_rejects_a_payload_of_another_type():
    with pytest.raises(ValidationError, match="does not match payload"):
        envelope(session_payload(), event_type=EventType.ORDER)


def test_envelope_round_trips_through_json():
    original = envelope(session_payload())
    assert EventEnvelope.model_validate_json(original.model_dump_json()) == original


def test_envelope_is_immutable():
    original = envelope(session_payload())
    with pytest.raises(ValidationError):
        original.idempotency_key = "other"  # type: ignore[misc]
