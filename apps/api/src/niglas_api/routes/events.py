"""Event ingestion boundary."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from niglas_api.auth import require_permission
from niglas_api.dependencies import get_event_store
from niglas_api.event_store import IdempotencyConflictError, InMemoryEventStore
from niglas_api.settings import Settings, get_settings
from niglas_schemas.events import EventEnvelope
from niglas_shared.rbac import Permission, Principal

router = APIRouter(prefix="/v1/events", tags=["events"])


class EventBatchRequest(BaseModel):
    """A producer batch of already-versioned event envelopes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    events: list[EventEnvelope] = Field(min_length=1)


class EventBatchResponse(BaseModel):
    accepted_count: int
    duplicate_count: int = 0


@router.post("/batches", response_model=EventBatchResponse, status_code=status.HTTP_202_ACCEPTED)
def ingest_batch(
    request: EventBatchRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[Principal, Depends(require_permission(Permission.EVENTS_INGEST))],
    event_store: Annotated[InMemoryEventStore, Depends(get_event_store)],
) -> EventBatchResponse:
    """Validate a batch before handing it to durable storage."""
    if len(request.events) > settings.max_events_per_batch:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"batch exceeds limit of {settings.max_events_per_batch} events",
        )

    foreign_orgs = {
        event.organization_id
        for event in request.events
        if event.organization_id != principal.organization_id
    }
    if foreign_orgs:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="events must belong to the authenticated organization",
        )

    try:
        result = event_store.ingest(request.events)
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotency key already exists for a different event",
        ) from exc

    return EventBatchResponse(
        accepted_count=result.accepted_count,
        duplicate_count=result.duplicate_count,
    )


class PrincipalResponse(BaseModel):
    subject_id: UUID
    organization_id: UUID
    roles: list[str]
    permissions: list[str]
    is_service_account: bool


@router.get("/me", response_model=PrincipalResponse)
def whoami(
    principal: Annotated[Principal, Depends(require_permission(Permission.EVENTS_INGEST))],
) -> PrincipalResponse:
    return PrincipalResponse(
        subject_id=principal.subject_id,
        organization_id=principal.organization_id,
        roles=sorted(role.value for role in principal.roles),
        permissions=sorted(permission.value for permission in principal.permissions),
        is_service_account=principal.is_service_account,
    )
