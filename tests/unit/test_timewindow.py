"""Windows are half-open so consecutive windows tile a timeline without overlap."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from niglas_shared.errors import DomainError
from niglas_shared.timewindow import TimeWindow

START = datetime(2026, 9, 24, 10, tzinfo=UTC)
HOUR = timedelta(hours=1)


def test_boundaries_are_half_open():
    window = TimeWindow.of_length(START, HOUR)
    assert window.contains(START)
    assert window.contains(START + timedelta(minutes=59, seconds=59))
    assert not window.contains(START + HOUR)


def test_consecutive_windows_do_not_overlap():
    first = TimeWindow.of_length(START, HOUR)
    second = TimeWindow.of_length(START + HOUR, HOUR)
    assert not first.overlaps(second)
    assert first.overlaps(TimeWindow.of_length(START + timedelta(minutes=30), HOUR))


def test_non_utc_input_is_normalised_not_rejected():
    tokyo = timezone(timedelta(hours=9))
    window = TimeWindow(START.astimezone(tokyo), (START + HOUR).astimezone(tokyo))
    assert window.start == START
    assert window.start.tzinfo is UTC


def test_previous_period_abuts_the_window():
    window = TimeWindow.of_length(START, HOUR)
    previous = window.previous_period()
    assert previous.end == window.start
    assert previous.duration == window.duration


def test_empty_or_inverted_windows_are_rejected():
    with pytest.raises(DomainError, match="before end"):
        TimeWindow(START, START)
    with pytest.raises(DomainError, match="before end"):
        TimeWindow(START + HOUR, START)


def test_naive_datetimes_are_rejected():
    with pytest.raises(DomainError, match="timezone-aware"):
        TimeWindow(datetime(2026, 9, 24), datetime(2026, 9, 25))  # noqa: DTZ001
    with pytest.raises(DomainError, match="timezone-aware"):
        TimeWindow.of_length(START, HOUR).contains(datetime(2026, 9, 24, 10, 30))  # noqa: DTZ001
