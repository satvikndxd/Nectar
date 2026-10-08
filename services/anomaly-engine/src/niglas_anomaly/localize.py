"""Localise a metric-level shift to the dimension segments that explain it.

For each segment (a single dimension value, or a pair of values from two dimensions)
we compare the segment's rate during the incident window with *the same segment's*
rate during the baseline window, and compute its **excess hits**:

    excess = observed_hits - observed_total * segment_baseline_rate

Using each segment's own baseline (rather than the global one) means a pure traffic
mix shift towards a naturally high-rate segment produces little excess, which guards
against the most common Simpson's-paradox style misattribution.

``share_of_excess`` is the segment's excess divided by the metric-level excess. It is
a decomposition of *where* the change happened, not evidence of *why*: correlation
with a segment is not causation, and downstream evidence must say so.
"""

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from niglas_anomaly.series import METRIC_DIMENSIONS, RateMetric, RateObservation
from niglas_shared.errors import DomainError


@dataclass(frozen=True, slots=True)
class SegmentShift:
    segment: tuple[tuple[str, str], ...]
    """Sorted (dimension, value) pairs; length 1 or 2."""
    baseline_hits: int
    baseline_total: int
    observed_hits: int
    observed_total: int
    excess_hits: float
    share_of_excess: float | None
    """``None`` when the metric-level excess is not positive (nothing to explain)."""
    z_score: float | None
    """Two-proportion z of observed vs. baseline for this segment; ``None`` if undefined."""

    @property
    def baseline_rate(self) -> float | None:
        return None if self.baseline_total == 0 else self.baseline_hits / self.baseline_total

    @property
    def observed_rate(self) -> float | None:
        return None if self.observed_total == 0 else self.observed_hits / self.observed_total


@dataclass(frozen=True, slots=True)
class Localization:
    metric: RateMetric
    total_excess_hits: float
    segments: tuple[SegmentShift, ...]
    """Ranked by excess hits, descending."""

    def top(self, size: int) -> list[SegmentShift]:
        """Top segments with exactly ``size`` dimensions."""
        return [s for s in self.segments if len(s.segment) == size]


def _counts(
    observed: Sequence[RateObservation], start: datetime, end: datetime
) -> dict[tuple[tuple[str, str], ...], list[int]]:
    """(hits, total) per segment key, including the empty key for the whole metric."""
    counts: dict[tuple[tuple[str, str], ...], list[int]] = {}
    for obs in observed:
        if not (start <= obs.occurred_at < end):
            continue
        items = sorted(obs.dimensions.items())
        keys = [()] + [(i,) for i in items] + list(itertools.combinations(items, 2))
        for key in keys:
            entry = counts.setdefault(key, [0, 0])
            entry[0] += int(obs.hit)
            entry[1] += 1
    return counts


def _z(hits_a: int, total_a: int, hits_b: int, total_b: int) -> float | None:
    if total_a == 0 or total_b == 0:
        return None
    pooled = (hits_a + hits_b) / (total_a + total_b)
    variance = pooled * (1 - pooled) * (1 / total_a + 1 / total_b)
    if variance == 0:
        return None
    return (hits_a / total_a - hits_b / total_b) / math.sqrt(variance)


def localize(
    metric: RateMetric,
    observed: Sequence[RateObservation],
    *,
    baseline: tuple[datetime, datetime],
    incident: tuple[datetime, datetime],
    min_observed_total: int = 20,
) -> Localization:
    """Rank segments by how much of the incident-window excess they account for.

    Segments with fewer than ``min_observed_total`` incident-window observations, or
    with no baseline observations (no own baseline to compare against), are omitted.
    """
    if baseline[1] > incident[0]:
        raise DomainError("baseline window must end before the incident window starts")
    allowed = set(METRIC_DIMENSIONS[metric])
    base = _counts(observed, *baseline)
    cur = _counts(observed, *incident)
    base_all = base.get((), [0, 0])
    cur_all = cur.get((), [0, 0])
    if base_all[1] == 0 or cur_all[1] == 0:
        raise DomainError("both windows need observations to localise")
    total_excess = cur_all[0] - cur_all[1] * base_all[0] / base_all[1]

    shifts: list[SegmentShift] = []
    for key, (hits, total) in cur.items():
        if not key or total < min_observed_total or any(d not in allowed for d, _ in key):
            continue
        b_hits, b_total = base.get(key, [0, 0])
        if b_total == 0:
            continue
        excess = hits - total * b_hits / b_total
        shifts.append(
            SegmentShift(
                segment=key,
                baseline_hits=b_hits,
                baseline_total=b_total,
                observed_hits=hits,
                observed_total=total,
                excess_hits=excess,
                share_of_excess=excess / total_excess if total_excess > 0 else None,
                z_score=_z(hits, total, b_hits, b_total),
            )
        )
    shifts.sort(key=lambda s: (-s.excess_hits, s.segment))
    return Localization(metric=metric, total_excess_hits=total_excess, segments=tuple(shifts))
