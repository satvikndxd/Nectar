"""Dimensional monitoring: run a detector over the metric and each single-value slice.

A fault confined to one segment is diluted at the metric level (in the reference
scenario, android x visa is ~14% of payment attempts). Scoring each single-dimension
slice against its own history recovers that signal. The cost is more hypotheses per
run, which the detector's threshold must absorb; that tradeoff is measured, not
assumed (docs/EVALUATION.md).

Slices with no history (for example an app version released inside the window) have
no baseline of their own and are reported as suppressed rather than scored.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from niglas_anomaly.detectors import DetectionRun, Detector, ProportionShiftDetector
from niglas_anomaly.series import (
    METRIC_DIMENSIONS,
    DimensionValues,
    RateMetric,
    RateObservation,
    build_rate_series,
)


@dataclass(frozen=True, slots=True)
class SliceResult:
    filters: DimensionValues
    run: DetectionRun


def slices(metric: RateMetric, observed: Sequence[RateObservation]) -> list[DimensionValues]:
    """The whole metric (``{}``) followed by every observed single-dimension value."""
    values = sorted(
        {(dim, obs.dimensions[dim]) for obs in observed for dim in METRIC_DIMENSIONS[metric]}
    )
    return [{}, *({dim: value} for dim, value in values)]


def monitor(
    metric: RateMetric,
    observed: Sequence[RateObservation],
    *,
    start: datetime,
    end: datetime,
    bucket: timedelta = timedelta(hours=1),
    detector: Detector | None = None,
) -> list[SliceResult]:
    """Run ``detector`` over every slice of ``metric``. Deterministic in input order."""
    chosen = detector if detector is not None else ProportionShiftDetector()
    return [
        SliceResult(
            filters=filters,
            run=chosen.detect(
                build_rate_series(
                    metric, observed, start=start, end=end, bucket=bucket, filters=filters
                )
            ),
        )
        for filters in slices(metric, observed)
    ]
