"""Reusable field types for Niglas contracts."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, Field, StringConstraints


def _require_utc(value: datetime) -> datetime:
    """Normalise an aware datetime to UTC.

    Niglas stores and compares every timestamp in UTC (see ``docs/ARCHITECTURE.md``).
    Naive datetimes are rejected by :class:`~pydantic.AwareDatetime` before this runs;
    offsets other than UTC are converted rather than rejected so that well-formed
    producers in other timezones are accepted without silently mixing clocks.
    """
    return value.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_require_utc)]
"""An aware datetime, always normalised to UTC."""

IdempotencyKey = Annotated[
    str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)
]
"""Producer-supplied key that makes an ingestion write safe to retry."""

ShortName = Annotated[str, StringConstraints(min_length=1, max_length=120, strip_whitespace=True)]

AmountMinor = Annotated[int, Field(ge=0)]
"""A money amount in the currency's minor units (e.g. cents). Never a float."""
