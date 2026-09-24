"""Injectable clocks.

Anything time-dependent takes a :class:`Clock` so that tests are deterministic and so
that "now" is never read from a global. Production wires :class:`SystemClock`; tests
wire :class:`FixedClock`.
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Source of the current time, always timezone-aware UTC."""

    def now(self) -> datetime:  # pragma: no cover - protocol definition
        ...


class SystemClock:
    """Reads the real wall clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """A clock that only moves when a test moves it."""

    def __init__(self, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._now = now.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        """Move the clock forward and return the new time."""
        if delta < timedelta(0):
            raise ValueError("FixedClock cannot move backwards")
        self._now += delta
        return self._now

    def set(self, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._now = now.astimezone(UTC)
