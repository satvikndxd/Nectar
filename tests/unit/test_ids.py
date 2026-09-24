"""UUIDv7 must encode a readable, sortable timestamp and stay reproducible."""

from datetime import UTC, datetime, timedelta
from random import Random

import pytest

from niglas_shared.ids import uuid7, uuid7_timestamp

MOMENT = datetime(2026, 9, 24, 12, 34, 56, 789000, tzinfo=UTC)


def test_version_and_variant_are_rfc_9562_compliant():
    value = uuid7(MOMENT, Random(1))
    assert value.version == 7
    assert (value.int >> 62) & 0b11 == 0b10


def test_timestamp_round_trips_to_the_millisecond():
    assert uuid7_timestamp(uuid7(MOMENT, Random(1))) == MOMENT


def test_ids_sort_in_time_order():
    moments = [MOMENT + timedelta(seconds=offset) for offset in range(20)]
    ids = [uuid7(moment, Random(offset)) for offset, moment in enumerate(moments)]
    assert ids == sorted(ids)


def test_same_seed_gives_the_same_id():
    assert uuid7(MOMENT, Random(7)) == uuid7(MOMENT, Random(7))
    assert uuid7(MOMENT, Random(7)) != uuid7(MOMENT, Random(8))


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        uuid7(datetime(2026, 9, 24))  # noqa: DTZ001 - deliberately naive


def test_non_v7_uuid_has_no_timestamp():
    from uuid import uuid4

    with pytest.raises(ValueError, match="version"):
        uuid7_timestamp(uuid4())


def test_timestamps_outside_the_representable_range_are_rejected():
    with pytest.raises(ValueError, match="outside the UUIDv7 range"):
        uuid7(datetime(1969, 12, 31, tzinfo=UTC))


def test_default_randomness_does_not_need_an_rng():
    first, second = uuid7(MOMENT), uuid7(MOMENT)
    assert first != second
    assert uuid7_timestamp(first) == MOMENT
