"""Event ingestion storage contract and local implementation."""

from collections.abc import Sequence
from dataclasses import dataclass
from threading import Lock
from uuid import UUID

from niglas_schemas.events import EventEnvelope

IdempotencyKey = tuple[UUID, str]


class IdempotencyConflictError(Exception):
    """An idempotency key was reused for a different event envelope."""


@dataclass(frozen=True, slots=True)
class EventIngestResult:
    accepted_count: int
    duplicate_count: int


class InMemoryEventStore:
    """Process-local event store used until durable database storage is wired in."""

    def __init__(self) -> None:
        self._events: dict[IdempotencyKey, EventEnvelope] = {}
        self._lock = Lock()

    def ingest(self, events: Sequence[EventEnvelope]) -> EventIngestResult:
        accepted_count = 0
        duplicate_count = 0
        with self._lock:
            for event in events:
                key = (event.organization_id, event.idempotency_key)
                existing = self._events.get(key)
                if existing is None:
                    self._events[key] = event
                    accepted_count += 1
                    continue
                if existing != event:
                    raise IdempotencyConflictError(
                        f"idempotency key {event.idempotency_key!r} already exists"
                    )
                duplicate_count += 1
        return EventIngestResult(
            accepted_count=accepted_count,
            duplicate_count=duplicate_count,
        )

    def list_events(self, organization_id: UUID) -> tuple[EventEnvelope, ...]:
        """Return stored events for tests and future read APIs."""
        with self._lock:
            return tuple(
                event
                for (stored_org_id, _), event in self._events.items()
                if stored_org_id == organization_id
            )
