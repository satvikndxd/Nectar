"""Known-input -> known-output tests for series building and detectors.

Expected z-scores were derived by hand from the textbook formulas:
two-proportion z = (p1 - p0) / sqrt(p(1-p)(1/n1 + 1/n0)) with pooled p, and
robust z = (x - median) / (1.4826 * MAD).
"""

from datetime import UTC, datetime, timedelta

import pytest

from niglas_anomaly.detectors import (
    Direction,
    ProportionShiftDetector,
    RobustZScoreDetector,
)
from niglas_anomaly.series import (
    RateBucket,
    RateMetric,
    RateObservation,
    RateSeries,
    build_rate_series,
)
from niglas_shared.errors import DomainError

T0 = datetime(2026, 9, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
M = RateMetric.PAYMENT_FAILURE_RATE


def series(counts: list[tuple[int, int]]) -> RateSeries:
    return RateSeries(
        metric=M,
        bucket=HOUR,
        filters={},
        buckets=tuple(RateBucket(T0 + i * HOUR, n, d) for i, (n, d) in enumerate(counts)),
    )


def obs(minute: int, hit: bool, **dims: str) -> RateObservation:
    return RateObservation(T0 + timedelta(minutes=minute), hit, dims)


class TestBuildRateSeries:
    def test_buckets_are_half_open_and_empty_buckets_are_kept(self):
        observed = [obs(0, True), obs(59, False), obs(60, True), obs(179, False)]
        result = build_rate_series(M, observed, start=T0, end=T0 + 3 * HOUR)
        assert [(b.numerator, b.denominator) for b in result.buckets] == [(1, 2), (1, 1), (0, 1)]
        empty = build_rate_series(M, [], start=T0, end=T0 + HOUR)
        assert empty.buckets[0].rate is None

    def test_filters_select_matching_observations(self):
        observed = [obs(0, True, platform="android"), obs(1, False, platform="ios")]
        result = build_rate_series(
            M, observed, start=T0, end=T0 + HOUR, filters={"platform": "android"}
        )
        assert result.buckets[0].numerator == 1
        assert result.buckets[0].denominator == 1

    @pytest.mark.parametrize(
        ("start", "end", "filters"),
        [
            (T0.replace(tzinfo=None), T0 + HOUR, {}),
            (T0, T0, {}),
            (T0, T0 + timedelta(minutes=90), {}),
            (T0, T0 + HOUR, {"region": "eu"}),  # region is not a payment dimension
        ],
    )
    def test_invalid_requests_are_rejected(self, start, end, filters):
        with pytest.raises(DomainError):
            build_rate_series(M, [], start=start, end=end, filters=filters)


class TestProportionShiftDetector:
    def test_known_shift_produces_the_hand_computed_z_score(self):
        counts = [(3, 100)] * 72 + [(15, 100)] * 6
        run = ProportionShiftDetector().detect(series(counts))
        assert run.scored_buckets == 1
        (anomaly,) = run.anomalies
        assert anomaly.score == pytest.approx(14.546, abs=1e-3)
        assert anomaly.baseline_value == pytest.approx(0.03)
        assert anomaly.observed_value == pytest.approx(0.15)
        assert anomaly.deviation_rel == pytest.approx(4.0)
        assert anomaly.window_start == T0 + 72 * HOUR
        assert anomaly.detected_at == T0 + 78 * HOUR
        assert anomaly.baseline_start == T0
        assert anomaly.detection_method == "proportion_shift_ztest"

    def test_stable_series_is_not_flagged(self):
        run = ProportionShiftDetector().detect(series([(3, 100)] * 120))
        assert run.anomalies == ()
        assert run.scored_buckets == 120 - 78 + 1

    def test_low_volume_windows_are_suppressed_not_scored(self):
        run = ProportionShiftDetector().detect(series([(0, 4)] * 72 + [(4, 4)] * 6))
        assert run.anomalies == ()
        assert run.suppressed_buckets == 1
        assert run.scored_buckets == 0

    def test_statistically_significant_but_tiny_shift_is_ignored(self):
        # 3.0% -> 3.6% on huge volume is "significant" but below the 25% floor.
        counts = [(30_000, 1_000_000)] * 72 + [(36_000, 1_000_000)] * 6
        assert ProportionShiftDetector().detect(series(counts)).anomalies == ()

    def test_direction_controls_which_shifts_count(self):
        counts = [(15, 100)] * 72 + [(3, 100)] * 6
        assert ProportionShiftDetector().detect(series(counts)).anomalies == ()
        down = ProportionShiftDetector(direction=Direction.DECREASE).detect(series(counts))
        assert len(down.anomalies) == 1

    def test_detection_uses_no_future_data(self):
        counts = [(3, 100)] * 77 + [(90, 100)] * 10
        run = ProportionShiftDetector().detect(series(counts))
        assert run.anomalies
        assert all(a.window_end <= T0 + 87 * HOUR for a in run.anomalies)
        # The first window that can contain the spike is the first flagged one.
        assert run.anomalies[0].window_end == T0 + 78 * HOUR


class TestRobustZScoreDetector:
    def test_known_outlier_produces_the_hand_computed_z_score(self):
        baseline = [(3, 100), (5, 100)] * 36  # median 0.04, MAD 0.01
        run = RobustZScoreDetector().detect(series([*baseline, (20, 100)]))
        (anomaly,) = run.anomalies
        assert anomaly.score == pytest.approx(10.7919, abs=1e-3)
        assert anomaly.baseline_value == pytest.approx(0.04)

    def test_small_deviation_is_not_flagged(self):
        baseline = [(3, 100), (5, 100)] * 36
        assert RobustZScoreDetector().detect(series([*baseline, (6, 100)])).anomalies == ()

    def test_flat_baseline_uses_the_sigma_floor(self):
        # MAD is 0; without the floor any change would score infinity.
        flat = [(3, 100)] * 72
        assert RobustZScoreDetector().detect(series([*flat, (4, 100)])).anomalies == ()
        assert len(RobustZScoreDetector().detect(series([*flat, (7, 100)])).anomalies) == 1

    def test_outliers_in_the_baseline_do_not_mask_a_new_outlier(self):
        # median 0.05, MAD 0.02 -> z = (0.30 - 0.05) / 0.029652 = 8.43
        baseline = [(3, 100), (5, 100)] * 35 + [(90, 100), (90, 100)]
        run = RobustZScoreDetector().detect(series([*baseline, (30, 100)]))
        assert len(run.anomalies) == 1
