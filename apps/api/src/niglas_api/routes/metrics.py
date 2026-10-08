"""Metric read endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from niglas_api.auth import require_permission
from niglas_api.dependencies import get_event_store
from niglas_api.event_store import InMemoryEventStore
from niglas_api.metrics import compute_funnel_metrics
from niglas_shared.rbac import Permission, Principal

router = APIRouter(prefix="/v1/metrics", tags=["metrics"])


class FunnelMetricsResponse(BaseModel):
    total_sessions: int
    checkout_sessions: int
    payment_sessions: int
    converted_sessions: int
    payment_attempts: int
    failed_payments: int
    revenue_minor: int
    checkout_rate: float
    payment_rate: float
    conversion_rate: float
    payment_failure_rate: float


@router.get("/funnel", response_model=FunnelMetricsResponse)
def funnel_metrics(
    principal: Annotated[Principal, Depends(require_permission(Permission.METRICS_READ))],
    event_store: Annotated[InMemoryEventStore, Depends(get_event_store)],
) -> FunnelMetricsResponse:
    metrics = compute_funnel_metrics(event_store.list_events(principal.organization_id))
    return FunnelMetricsResponse(
        total_sessions=metrics.total_sessions,
        checkout_sessions=metrics.checkout_sessions,
        payment_sessions=metrics.payment_sessions,
        converted_sessions=metrics.converted_sessions,
        payment_attempts=metrics.payment_attempts,
        failed_payments=metrics.failed_payments,
        revenue_minor=metrics.revenue_minor,
        checkout_rate=metrics.checkout_rate,
        payment_rate=metrics.payment_rate,
        conversion_rate=metrics.conversion_rate,
        payment_failure_rate=metrics.payment_failure_rate,
    )
