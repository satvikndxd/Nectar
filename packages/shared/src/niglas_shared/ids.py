"""Time-sortable identifiers (UUIDv7, RFC 9562 section 5.7).

Niglas uses UUIDv7 for every generated primary key. The first 48 bits are the Unix
timestamp in milliseconds, so ids sort by creation time. That gives B-tree-friendly
inserts for the append-heavy tables (events, audit) without a separate sequence, and
lets a support engineer read a creation time straight off an id.

The random bits come from an injected ``random.Random`` so that the synthetic data
generator can produce byte-identical datasets from a seed.
"""

import os
import random
from datetime import UTC, datetime
from uuid import UUID

_UNIX_TS_MS_BITS = 48
_RAND_A_BITS = 12
_RAND_B_BITS = 62
_VERSION = 7
_VARIANT = 0b10
_MAX_UNIX_TS_MS = (1 << _UNIX_TS_MS_BITS) - 1


class _SystemRandomBits:
    """Adapter giving :func:`uuid7` cryptographic randomness by default."""

    @staticmethod
    def getrandbits(k: int) -> int:
        return int.from_bytes(os.urandom((k + 7) // 8), "big") >> (-k % 8)


def uuid7(timestamp: datetime, rng: random.Random | None = None) -> UUID:
    """Build a UUIDv7 for ``timestamp``.

    Args:
        timestamp: Timezone-aware instant to encode. Converted to UTC.
        rng: Source of the 74 random bits. Defaults to :func:`os.urandom`. Pass a
            seeded ``random.Random`` for reproducible datasets.

    Raises:
        ValueError: If ``timestamp`` is naive or outside the representable range
            (1970-01-01 .. 10889-08-02).
    """
    if timestamp.tzinfo is None:
        raise ValueError("uuid7 requires a timezone-aware datetime")
    unix_ts_ms = int(timestamp.astimezone(UTC).timestamp() * 1000)
    if not 0 <= unix_ts_ms <= _MAX_UNIX_TS_MS:
        raise ValueError(f"timestamp {timestamp!r} is outside the UUIDv7 range")

    source: random.Random | type[_SystemRandomBits] = rng if rng is not None else _SystemRandomBits
    rand_a = source.getrandbits(_RAND_A_BITS)
    rand_b = source.getrandbits(_RAND_B_BITS)

    value = unix_ts_ms << (128 - _UNIX_TS_MS_BITS)
    value |= _VERSION << 76
    value |= rand_a << 64
    value |= _VARIANT << 62
    value |= rand_b
    return UUID(int=value)


def uuid7_timestamp(value: UUID) -> datetime:
    """Read the creation timestamp back out of a UUIDv7.

    Raises:
        ValueError: If ``value`` is not version 7.
    """
    if value.version != _VERSION:
        raise ValueError(f"expected a UUIDv7, got version {value.version}")
    unix_ts_ms = value.int >> (128 - _UNIX_TS_MS_BITS)
    return datetime.fromtimestamp(unix_ts_ms / 1000, tz=UTC)
