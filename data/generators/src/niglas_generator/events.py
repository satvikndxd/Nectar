"""Conversion from simulation outcomes to ingestion event envelopes.

This is the generator's only coupling to the wire format. Keeping it in one module
means a schema change touches one file, and the simulator stays a pure model of a
business rather than a producer of JSON.
"""

from collections.abc import Iterator
from datetime import datetime
from uuid import UUID

from niglas_generator.outcomes import DeploymentOutcome, SessionOutcome, SimulationResult
from niglas_generator.rng import StreamRandom
from niglas_schemas.enums import Currency, DeploymentStatus, EventType, PaymentStatus
from niglas_schemas.events import (
    DeploymentEventPayload,
    EventEnvelope,
    EventPayload,
    OrderEventPayload,
    OrderLine,
    PaymentEventPayload,
    ProductEventPayload,
    SessionEventPayload,
)
from niglas_shared.ids import uuid7


def to_events(
    result: SimulationResult, *, organization_id: UUID, currency: Currency, streams: StreamRandom
) -> list[EventEnvelope]:
    """Flatten a simulation into envelopes, ordered by ``occurred_at``.

    Event ids are derived from the idempotency key, so regenerating a dataset produces
    the same ids and re-ingesting it is a no-op rather than a duplicate.
    """
    events: list[EventEnvelope] = []
    for deployment in result.deployments:
        events.append(_deployment_event(deployment, organization_id, streams))
    for session in result.sessions:
        events.extend(_session_events(session, organization_id, currency, streams))
    events.sort(key=lambda event: (event.occurred_at, event.idempotency_key))
    return events


def _envelope(
    *,
    organization_id: UUID,
    occurred_at: datetime,
    idempotency_key: str,
    payload: EventPayload,
    streams: StreamRandom,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid7(occurred_at, streams.stream("event", idempotency_key)),
        organization_id=organization_id,
        event_type=EventType(payload.event_type),
        occurred_at=occurred_at,
        idempotency_key=idempotency_key,
        payload=payload,
    )


def _deployment_event(
    deployment: DeploymentOutcome, organization_id: UUID, streams: StreamRandom
) -> EventEnvelope:
    return _envelope(
        organization_id=organization_id,
        occurred_at=deployment.deployed_at,
        idempotency_key=f"deployment:{deployment.deployment_id}",
        payload=DeploymentEventPayload(
            deployment_id=deployment.deployment_id,
            service=deployment.service,
            version=deployment.version,
            status=DeploymentStatus(deployment.status),
            commit_sha=deployment.commit_sha,
            description=deployment.description,
        ),
        streams=streams,
    )


def _session_events(
    session: SessionOutcome, organization_id: UUID, currency: Currency, streams: StreamRandom
) -> Iterator[EventEnvelope]:
    dimensions = session.dimensions
    yield _envelope(
        organization_id=organization_id,
        occurred_at=session.started_at,
        idempotency_key=f"session:{session.session_id}",
        payload=SessionEventPayload(
            session_id=session.session_id,
            customer_id=session.customer_id,
            platform=dimensions.platform,
            region=dimensions.region,
            plan_tier=dimensions.plan_tier,
            app_version=dimensions.app_version,
            started_at=session.started_at,
            duration_ms=session.duration_ms,
            reached_checkout=session.reached_checkout,
            reached_payment=session.reached_payment,
            converted=session.converted,
        ),
        streams=streams,
    )

    for name, happened in (
        ("checkout_started", session.reached_checkout),
        ("payment_submitted", session.reached_payment),
    ):
        if happened:
            yield _envelope(
                organization_id=organization_id,
                occurred_at=session.started_at,
                idempotency_key=f"product_event:{session.session_id}:{name}",
                payload=ProductEventPayload(
                    session_id=session.session_id,
                    customer_id=session.customer_id,
                    name=name,
                    platform=dimensions.platform,
                    properties={"app_version": dimensions.app_version},
                ),
                streams=streams,
            )

    basket_amount_minor = session.basket_amount_minor
    for attempt in session.attempts:
        yield _envelope(
            organization_id=organization_id,
            occurred_at=attempt.attempted_at,
            idempotency_key=f"payment:{attempt.payment_id}",
            payload=PaymentEventPayload(
                payment_id=attempt.payment_id,
                order_id=session.order_id if attempt.succeeded else None,
                session_id=session.session_id,
                customer_id=session.customer_id,
                method=dimensions.payment_method,
                status=PaymentStatus.SUCCEEDED if attempt.succeeded else PaymentStatus.FAILED,
                failure_code=attempt.failure_code,
                amount_minor=basket_amount_minor,
                currency=currency,
                attempt_number=attempt.attempt_number,
                platform=dimensions.platform,
                app_version=dimensions.app_version,
            ),
            streams=streams,
        )

    if session.order_id is not None:
        last_attempt = session.attempts[-1]
        yield _envelope(
            organization_id=organization_id,
            occurred_at=last_attempt.attempted_at,
            idempotency_key=f"order:{session.order_id}",
            payload=OrderEventPayload(
                order_id=session.order_id,
                session_id=session.session_id,
                customer_id=session.customer_id,
                currency=currency,
                total_amount_minor=basket_amount_minor,
                lines=[
                    OrderLine(
                        product_sku=line.sku,
                        quantity=line.quantity,
                        unit_amount_minor=line.unit_amount_minor,
                    )
                    for line in session.basket
                ],
            ),
            streams=streams,
        )
