"""Per-bucket anomaly detectors over rate series.

Both detectors compare a *current* window ending at each bucket against a *trailing
baseline* window that ends where the current window starts, so a detection at bucket
``t`` uses only data up to ``t`` (no look-ahead; the same code works online).

* :class:`ProportionShiftDetector` pools counts and runs a two-proportion z-test.
  It is the right tool for rates built from counts: it knows that 1 failure in 20
  attempts is weak evidence and 100 in 2,000 is strong.
* :class:`RobustZScoreDetector` scores the current bucket's rate against the
  median/MAD of the baseline buckets' rates. It ignores volume but is resistant to
  outliers in the baseline, and serves as a simple, explainable comparison method.

Buckets whose current window has fewer than ``min_denominator`` observations are
not scored at all (they are counted as ``suppressed``) rather than alerted on.
"""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from niglas_anomaly.series import DimensionValues, RateBucket, RateMetric, RateSeries
from niglas_shared.errors import DomainError

MAD_TO_SIGMA = 1.4826
"""Scales the median absolute deviation to a standard deviation under normality."""


class Direction(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class Anomaly:
    """One flagged bucket, carrying everything needed to reproduce the decision."""

    metric: RateMetric
    filters: DimensionValues
    detection_method: str
    method_version: str
    threshold: float
    score: float
    baseline_value: float
    baseline_description: str
    baseline_start: datetime
    baseline_end: datetime
    observed_value: float
    window_start: datetime
    window_end: datetime
    observed_numerator: int
    observed_denominator: int
    confidence: float
    """Detector-specific, in [0, 1]. For the z-test, 1 - one-sided p-value."""

    @property
    def detected_at(self) -> datetime:
        """The earliest moment the detection could have been made."""
        return self.window_end

    @property
    def deviation_abs(self) -> float:
        return self.observed_value - self.baseline_value

    @property
    def deviation_rel(self) -> float | None:
        if self.baseline_value == 0:
            return None
        return self.deviation_abs / self.baseline_value


@dataclass(frozen=True, slots=True)
class DetectionRun:
    anomalies: tuple[Anomaly, ...]
    scored_buckets: int
    suppressed_buckets: int
    """Buckets skipped for insufficient data. Reported, never silently dropped."""


class Detector(Protocol):
    name: str
    version: str

    def detect(self, series: RateSeries) -> DetectionRun: ...


def _pooled(buckets: Sequence[RateBucket]) -> tuple[int, int]:
    return sum(b.numerator for b in buckets), sum(b.denominator for b in buckets)


def _normal_sf(z: float) -> float:
    """Upper-tail probability of the standard normal."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def _signed(score: float, direction: Direction) -> float:
    """Score in the direction of interest, so that 'bigger is more anomalous'."""
    if direction is Direction.INCREASE:
        return score
    if direction is Direction.DECREASE:
        return -score
    return abs(score)


def _windows(
    series: RateSeries, current: int, baseline: int
) -> list[tuple[int, Sequence[RateBucket], Sequence[RateBucket]]]:
    if current < 1 or baseline < 1:
        raise DomainError("window sizes must be at least one bucket")
    buckets = series.buckets
    return [
        (end, buckets[end - current : end], buckets[end - current - baseline : end - current])
        for end in range(current + baseline, len(buckets) + 1)
    ]


@dataclass(frozen=True, slots=True)
class ProportionShiftDetector:
    """Two-proportion z-test of the pooled current window vs. the pooled baseline."""

    current_buckets: int = 6
    baseline_buckets: int = 72
    z_threshold: float = 5.0
    """High on purpose: windows overlap, many slices are monitored, and payment
    retries make failures overdispersed relative to the binomial model. The value
    was chosen against clean synthetic runs; see docs/EVALUATION.md."""
    min_relative_change: float = 0.25
    """Practical-significance floor: huge volumes make tiny shifts 'significant'."""
    min_denominator: int = 30
    direction: Direction = Direction.INCREASE
    name: str = "proportion_shift_ztest"
    version: str = "1.0.0"

    def detect(self, series: RateSeries) -> DetectionRun:
        anomalies: list[Anomaly] = []
        scored = suppressed = 0
        for _, current, baseline in _windows(series, self.current_buckets, self.baseline_buckets):
            cur_hits, cur_total = _pooled(current)
            base_hits, base_total = _pooled(baseline)
            if cur_total < self.min_denominator or base_total < self.min_denominator:
                suppressed += 1
                continue
            scored += 1
            p_cur, p_base = cur_hits / cur_total, base_hits / base_total
            p_pool = (cur_hits + base_hits) / (cur_total + base_total)
            variance = p_pool * (1 - p_pool) * (1 / cur_total + 1 / base_total)
            if variance == 0:
                continue
            score = _signed((p_cur - p_base) / math.sqrt(variance), self.direction)
            relative = abs(p_cur - p_base) / p_base if p_base else math.inf
            if score < self.z_threshold or relative < self.min_relative_change:
                continue
            anomalies.append(
                Anomaly(
                    metric=series.metric,
                    filters=series.filters,
                    detection_method=self.name,
                    method_version=self.version,
                    threshold=self.z_threshold,
                    score=score,
                    baseline_value=p_base,
                    baseline_description=(
                        f"pooled rate over the preceding {len(baseline)} buckets"
                    ),
                    baseline_start=baseline[0].start,
                    baseline_end=current[0].start,
                    observed_value=p_cur,
                    window_start=current[0].start,
                    window_end=current[-1].start + series.bucket,
                    observed_numerator=cur_hits,
                    observed_denominator=cur_total,
                    confidence=1.0 - _normal_sf(score),
                )
            )
        return DetectionRun(tuple(anomalies), scored, suppressed)


@dataclass(frozen=True, slots=True)
class RobustZScoreDetector:
    """Current bucket rate vs. median/MAD of the baseline buckets' rates."""

    baseline_buckets: int = 72
    z_threshold: float = 6.0
    min_denominator: int = 20
    min_sigma: float = 0.005
    """Floor on the robust sigma (in rate units), so a flat baseline cannot make
    any wiggle infinitely anomalous."""
    direction: Direction = Direction.INCREASE
    name: str = "robust_zscore_mad"
    version: str = "1.0.0"

    def detect(self, series: RateSeries) -> DetectionRun:
        anomalies: list[Anomaly] = []
        scored = suppressed = 0
        for _, current, baseline in _windows(series, 1, self.baseline_buckets):
            bucket = current[0]
            history = [
                rate
                for b in baseline
                if b.denominator >= self.min_denominator and (rate := b.rate) is not None
            ]
            if bucket.denominator < self.min_denominator or len(history) < 3:
                suppressed += 1
                continue
            scored += 1
            observed = bucket.numerator / bucket.denominator
            median = statistics.median(history)
            mad = statistics.median(abs(rate - median) for rate in history)
            sigma = max(MAD_TO_SIGMA * mad, self.min_sigma)
            score = _signed((observed - median) / sigma, self.direction)
            if score < self.z_threshold:
                continue
            anomalies.append(
                Anomaly(
                    metric=series.metric,
                    filters=series.filters,
                    detection_method=self.name,
                    method_version=self.version,
                    threshold=self.z_threshold,
                    score=score,
                    baseline_value=median,
                    baseline_description=(
                        f"median of {len(history)} bucket rates (MAD-scaled sigma "
                        f"{sigma:.4f}) over the preceding {len(baseline)} buckets"
                    ),
                    baseline_start=baseline[0].start,
                    baseline_end=bucket.start,
                    observed_value=observed,
                    window_start=bucket.start,
                    window_end=bucket.start + series.bucket,
                    observed_numerator=bucket.numerator,
                    observed_denominator=bucket.denominator,
                    # A z-score on a robust scale has no exact tail probability; this
                    # is the normal approximation, flagged as such in the docs.
                    confidence=1.0 - _normal_sf(score),
                )
            )
        return DetectionRun(tuple(anomalies), scored, suppressed)


__all__ = [
    "Anomaly",
    "DetectionRun",
    "Detector",
    "Direction",
    "ProportionShiftDetector",
    "RobustZScoreDetector",
]
