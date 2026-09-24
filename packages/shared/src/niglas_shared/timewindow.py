"""Half-open UTC time windows.

Every metric value, anomaly and evidence item is scoped to a window. Windows are
half-open (``start <= t < end``) so that consecutive windows tile a timeline without
double-counting an event that lands exactly on a boundary.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from niglas_shared.errors import DomainError


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """A half-open interval ``[start, end)`` in UTC."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise DomainError("TimeWindow requires timezone-aware datetimes")
        object.__setattr__(self, "start", self.start.astimezone(UTC))
        object.__setattr__(self, "end", self.end.astimezone(UTC))
        if self.start >= self.end:
            raise DomainError(f"TimeWindow start {self.start} must be before end {self.end}")

    @classmethod
    def of_length(cls, start: datetime, length: timedelta) -> "TimeWindow":
        return cls(start, start + length)

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def contains(self, moment: datetime) -> bool:
        if moment.tzinfo is None:
            raise DomainError("TimeWindow.contains requires a timezone-aware datetime")
        moment_utc = moment.astimezone(UTC)
        return self.start <= moment_utc < self.end

    def overlaps(self, other: "TimeWindow") -> bool:
        return self.start < other.end and other.start < self.end

    def shifted(self, delta: timedelta) -> "TimeWindow":
        """The same-length window moved by ``delta`` (for period-over-period compares)."""
        return TimeWindow(self.start + delta, self.end + delta)

    def previous_period(self) -> "TimeWindow":
        """The window of equal length immediately before this one."""
        return self.shifted(-self.duration)
