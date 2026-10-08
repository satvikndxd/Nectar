from datetime import UTC, datetime
from uuid import uuid4

import pytest

from niglas_api.event_store import IdempotencyConflictError, InMemoryEventStore
from niglas_schemas.enums import EventType, PlanTier, Platform, Region
from niglas_schemas.events import EventEnvelope, SessionEventPayload

OCCURRED_AT = datetime(2026, 9, 24, 12, tzinfo=UTC)


def session_event(idempotency_key: str = "session:one") -> EventEnvelope:
    payload = SessionEventPayload(
        session_id=uuid4(),
        customer_id=uuid4(),
        platform=Platform.ANDROID,
        region=Region.EU,
        plan_tier=PlanTier.PRO,
        app_version="2.8.0",
        started_at=OCCURRED_AT,
        duration_ms=1200,
        reached_checkout=True,
        reached_payment=False,
        converted=False,
    )
    return EventEnvelope(
        event_id=uuid4(),
        organization_id=uuid4(),
        event_type=EventType.SESSION,
        occurred_at=OCCURRED_AT,
        idempotency_key=idempotency_key,
        payload=payload,
    )


def test_ingest_counts_new_events_and_exact_duplicates() -> None:
    store = InMemoryEventStore()
    event = session_event()

    first = store.ingest([event])
    second = store.ingest([event])

    assert first.accepted_count == 1
    assert first.duplicate_count == 0
    assert second.accepted_count == 0
    assert second.duplicate_count == 1


def test_reusing_an_idempotency_key_for_a_different_event_is_rejected() -> None:
    store = InMemoryEventStore()
    event = session_event()
    conflicting = event.model_copy(update={"event_id": uuid4()})

    store.ingest([event])
    with pytest.raises(IdempotencyConflictError):
        store.ingest([conflicting])


def test_list_events_is_scoped_to_one_organization() -> None:
    store = InMemoryEventStore()
    first = session_event("session:first")
    second = session_event("session:second")
    store.ingest([first, second])

    assert store.list_events(first.organization_id) == (first,)
