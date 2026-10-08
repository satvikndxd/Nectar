"""Shared FastAPI dependencies."""

from typing import Annotated, cast

from fastapi import Depends, Request

from niglas_api.event_store import InMemoryEventStore
from niglas_api.settings import Settings, get_settings


def get_event_store(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> InMemoryEventStore:
    """Return the configured event store for the app process."""
    del settings
    return cast(InMemoryEventStore, request.app.state.event_store)
