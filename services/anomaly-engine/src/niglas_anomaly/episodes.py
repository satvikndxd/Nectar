"""Merge per-bucket anomalies into episodes by explicit, deterministic rules.

Two anomalies belong to the same episode when they share metric, filters and
detection method, and the later one starts no more than ``max_gap`` after the earlier
one ends. Cross-metric merging into incidents is a separate, later concern.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from niglas_anomaly.detectors import Anomaly


@dataclass(frozen=True, slots=True)
class Episode:
    anomalies: tuple[Anomaly, ...]

    @property
    def first(self) -> Anomaly:
        return self.anomalies[0]

    @property
    def peak(self) -> Anomaly:
        return max(self.anomalies, key=lambda a: a.score)

    @property
    def start(self) -> datetime:
        return min(a.window_start for a in self.anomalies)

    @property
    def end(self) -> datetime:
        return max(a.window_end for a in self.anomalies)

    @property
    def first_detected_at(self) -> datetime:
        return min(a.detected_at for a in self.anomalies)


def merge_episodes(
    anomalies: Iterable[Anomaly], *, max_gap: timedelta = timedelta(hours=2)
) -> list[Episode]:
    """Group anomalies into episodes, ordered by start time."""

    def group_key(a: Anomaly) -> tuple[str, tuple[tuple[str, str], ...], str]:
        return (a.metric.value, tuple(sorted(a.filters.items())), a.detection_method)

    ordered = sorted(anomalies, key=lambda a: (group_key(a), a.window_start))
    episodes: list[list[Anomaly]] = []
    for anomaly in ordered:
        current = episodes[-1] if episodes else None
        if (
            current is not None
            and group_key(current[-1]) == group_key(anomaly)
            and anomaly.window_start - max(a.window_end for a in current) <= max_gap
        ):
            current.append(anomaly)
        else:
            episodes.append([anomaly])
    result = [Episode(tuple(group)) for group in episodes]
    result.sort(key=lambda e: e.start)
    return result
