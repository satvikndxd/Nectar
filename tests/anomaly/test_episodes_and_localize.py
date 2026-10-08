from datetime import UTC, datetime, timedelta

import pytest

from niglas_anomaly.detectors import Anomaly
from niglas_anomaly.episodes import merge_episodes
from niglas_anomaly.localize import localize
from niglas_anomaly.series import RateMetric, RateObservation
from niglas_shared.errors import DomainError

T0 = datetime(2026, 9, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
M = RateMetric.PAYMENT_FAILURE_RATE


def anomaly(hour: int, score: float = 6.0, **filters: str) -> Anomaly:
    start = T0 + hour * HOUR
    return Anomaly(
        metric=M,
        filters=filters,
        detection_method="test",
        method_version="0",
        threshold=5.0,
        score=score,
        baseline_value=0.03,
        baseline_description="test",
        baseline_start=T0,
        baseline_end=start,
        observed_value=0.1,
        window_start=start,
        window_end=start + HOUR,
        observed_numerator=10,
        observed_denominator=100,
        confidence=0.99,
    )


class TestMergeEpisodes:
    def test_close_anomalies_merge_and_distant_ones_split(self):
        episodes = merge_episodes([anomaly(10), anomaly(11, score=9.0), anomaly(13), anomaly(20)])
        assert [len(e.anomalies) for e in episodes] == [3, 1]
        first = episodes[0]
        assert (first.start, first.end) == (T0 + 10 * HOUR, T0 + 14 * HOUR)
        assert first.peak.score == 9.0
        assert first.first_detected_at == T0 + 11 * HOUR

    def test_different_slices_never_merge(self):
        episodes = merge_episodes([anomaly(10, platform="android"), anomaly(10, platform="ios")])
        assert len(episodes) == 2


def make(hits: int, total: int, minute: int, **dims: str) -> list[RateObservation]:
    at = T0 + timedelta(minutes=minute)
    return [RateObservation(at, i < hits, dims) for i in range(total)]


BASELINE = (T0, T0 + HOUR)
INCIDENT = (T0 + HOUR, T0 + 2 * HOUR)


class TestLocalize:
    def test_concentrated_fault_is_attributed_to_its_segment(self):
        observed = [
            *make(2, 100, 0, platform="android"),
            *make(2, 100, 0, platform="ios"),
            *make(22, 100, 60, platform="android"),
            *make(2, 100, 60, platform="ios"),
        ]
        result = localize(M, observed, baseline=BASELINE, incident=INCIDENT)
        assert result.total_excess_hits == pytest.approx(20.0)
        top = result.top(1)[0]
        assert top.segment == (("platform", "android"),)
        assert top.excess_hits == pytest.approx(20.0)
        assert top.share_of_excess == pytest.approx(1.0)
        ios = next(s for s in result.segments if s.segment == (("platform", "ios"),))
        assert ios.excess_hits == pytest.approx(0.0)

    def test_pure_mix_shift_is_not_attributed_to_any_segment(self):
        # Segment rates are unchanged (10% and 1%); only traffic mix moves towards
        # the high-rate segment, so the metric rate rises from 5.5% to 9.1%.
        observed = [
            *make(10, 100, 0, platform="android"),
            *make(1, 100, 0, platform="ios"),
            *make(18, 180, 60, platform="android"),
            *make(0, 20, 60, platform="ios"),
        ]
        result = localize(M, observed, baseline=BASELINE, incident=INCIDENT)
        assert result.total_excess_hits == pytest.approx(18 - 200 * 0.055)
        assert all(abs(s.excess_hits) < 0.5 for s in result.segments)

    def test_overlapping_windows_are_rejected(self):
        with pytest.raises(DomainError):
            localize(M, make(1, 10, 0), baseline=(T0, T0 + 2 * HOUR), incident=INCIDENT)
