"""Rate metrics bucketed into a regular UTC time series.

A rate is kept as its numerator and denominator rather than a ratio, so that
detectors can weight buckets by volume and pool adjacent buckets correctly
(the mean of ratios is not the ratio of sums).
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from niglas_schemas.enums import PaymentStatus
from niglas_schemas.events import EventEnvelope, PaymentEventPayload, SessionEventPayload
from niglas_shared.errors import DomainError

DimensionValues = Mapping[str, str]
"""Dimension name -> value, e.g. ``{"platform": "android"}``."""


class RateMetric(StrEnum):
    """Rate metrics the engine can build from raw events."""

    PAYMENT_FAILURE_RATE = "payment_failure_rate"
    """Failed payment attempts / all payment attempts."""

    CONVERSION_RATE = "conversion_rate"
    """Converted sessions / all sessions."""


@dataclass(frozen=True, slots=True)
class RateObservation:
    """One event's contribution to a rate: its dimensions and whether it is a 'hit'."""

    occurred_at: datetime
    hit: bool
    dimensions: DimensionValues


@dataclass(frozen=True, slots=True)
class RateBucket:
    start: datetime
    numerator: int
    denominator: int

    @property
    def rate(self) -> float | None:
        """The rate, or ``None`` when the bucket is empty (not zero: zero is a value)."""
        return None if self.denominator == 0 else self.numerator / self.denominator


@dataclass(frozen=True, slots=True)
class RateSeries:
    metric: RateMetric
    bucket: timedelta
    filters: DimensionValues
    buckets: tuple[RateBucket, ...]


def _payment_observation(event: EventEnvelope) -> RateObservation | None:
    payload = event.payload
    if not isinstance(payload, PaymentEventPayload):
        return None
    return RateObservation(
        occurred_at=event.occurred_at,
        hit=payload.status is PaymentStatus.FAILED,
        dimensions={
            "platform": payload.platform.value,
            "payment_method": payload.method.value,
            "app_version": payload.app_version,
        },
    )


def _session_observation(event: EventEnvelope) -> RateObservation | None:
    payload = event.payload
    if not isinstance(payload, SessionEventPayload):
        return None
    return RateObservation(
        occurred_at=event.occurred_at,
        hit=payload.converted,
        dimensions={
            "platform": payload.platform.value,
            "region": payload.region.value,
            "plan_tier": payload.plan_tier.value,
            "app_version": payload.app_version,
        },
    )


_EXTRACTORS: dict[RateMetric, Callable[[EventEnvelope], RateObservation | None]] = {
    RateMetric.PAYMENT_FAILURE_RATE: _payment_observation,
    RateMetric.CONVERSION_RATE: _session_observation,
}

METRIC_DIMENSIONS: dict[RateMetric, tuple[str, ...]] = {
    RateMetric.PAYMENT_FAILURE_RATE: ("platform", "payment_method", "app_version"),
    RateMetric.CONVERSION_RATE: ("platform", "region", "plan_tier", "app_version"),
}
"""Dimensions each metric can be filtered and localised by. Doubles as an allow-list."""


def observations(metric: RateMetric, events: Iterable[EventEnvelope]) -> list[RateObservation]:
    """Extract the observations for ``metric``, sorted by time."""
    extract = _EXTRACTORS[metric]
    found = [obs for event in events if (obs := extract(event)) is not None]
    found.sort(key=lambda obs: obs.occurred_at)
    return found


def matches(observation: RateObservation, filters: DimensionValues) -> bool:
    return all(observation.dimensions.get(name) == value for name, value in filters.items())


def build_rate_series(
    metric: RateMetric,
    observed: Iterable[RateObservation],
    *,
    start: datetime,
    end: datetime,
    bucket: timedelta = timedelta(hours=1),
    filters: DimensionValues | None = None,
) -> RateSeries:
    """Bucket observations into ``[start, end)``; every bucket is present, even if empty.

    Raises:
        DomainError: On naive datetimes, a non-positive bucket, unknown filter
            dimensions, or a range that is not a whole number of buckets.
    """
    filters = dict(filters or {})
    if start.tzinfo is None or end.tzinfo is None:
        raise DomainError("series bounds must be timezone-aware")
    if bucket <= timedelta(0) or end <= start:
        raise DomainError("series needs a positive bucket and start < end")
    if (end - start) % bucket:
        raise DomainError("series range must be a whole number of buckets")
    unknown = set(filters) - set(METRIC_DIMENSIONS[metric])
    if unknown:
        raise DomainError(f"unknown dimensions for {metric}: {sorted(unknown)}")

    count = (end - start) // bucket
    numerators = [0] * count
    denominators = [0] * count
    for obs in observed:
        if not (start <= obs.occurred_at < end) or not matches(obs, filters):
            continue
        index = (obs.occurred_at - start) // bucket
        denominators[index] += 1
        numerators[index] += int(obs.hit)
    return RateSeries(
        metric=metric,
        bucket=bucket,
        filters=filters,
        buckets=tuple(
            RateBucket(start=start + i * bucket, numerator=n, denominator=d)
            for i, (n, d) in enumerate(zip(numerators, denominators, strict=True))
        ),
    )
