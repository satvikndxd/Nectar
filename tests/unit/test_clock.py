"""Time-dependent code takes a clock so tests never race the wall clock."""

from datetime import UTC, datetime, timedelta

import pytest

from niglas_shared.clock import Clock, FixedClock, SystemClock

NOW = datetime(2026, 9, 24, 8, tzinfo=UTC)


def test_fixed_clock_does_not_move_on_its_own():
    clock = FixedClock(NOW)
    assert clock.now() == clock.now() == NOW


def test_fixed_clock_advances_only_when_told():
    clock = FixedClock(NOW)
    assert clock.advance(timedelta(minutes=30)) == NOW + timedelta(minutes=30)
    assert clock.now() == NOW + timedelta(minutes=30)


def test_fixed_clock_refuses_to_move_backwards():
    with pytest.raises(ValueError, match="backwards"):
        FixedClock(NOW).advance(timedelta(seconds=-1))


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        FixedClock(datetime(2026, 9, 24))  # noqa: DTZ001


def test_both_clocks_satisfy_the_protocol_and_return_utc():
    for clock in (SystemClock(), FixedClock(NOW)):
        assert isinstance(clock, Clock)
        assert clock.now().tzinfo is UTC
