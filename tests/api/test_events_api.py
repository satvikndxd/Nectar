from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from niglas_api.auth import create_access_token
from niglas_api.main import create_app
from niglas_api.settings import Settings, get_settings
from niglas_schemas.enums import EventType, PlanTier, Platform, Region, Role
from niglas_schemas.events import EventEnvelope, SessionEventPayload
from niglas_shared.rbac import Principal

ORG_ID = uuid4()
SUBJECT_ID = uuid4()
OCCURRED_AT = datetime(2026, 9, 24, 12, tzinfo=UTC)


def override_settings() -> Settings:
    return Settings(
        environment="test",
        jwt_secret=SecretStr("unit-test-signing-key-32-bytes-ok"),
        jwt_issuer="niglas-test",
        max_events_per_batch=2,
    )


def client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = override_settings
    return TestClient(app)


def token(*roles: Role, org_id: UUID = ORG_ID) -> str:
    return create_access_token(
        Principal(
            subject_id=SUBJECT_ID,
            organization_id=org_id,
            roles=frozenset(roles),
        ),
        settings=override_settings(),
    )


def session_event(org_id: UUID = ORG_ID) -> dict[str, Any]:
    payload = SessionEventPayload(
        session_id=uuid4(),
        customer_id=uuid4(),
        platform=Platform.ANDROID,
        region=Region.EU,
        plan_tier=PlanTier.PRO,
        app_version="2.8.0",
        started_at=OCCURRED_AT,
        duration_ms=1200,
        reached_checkout=True,
        reached_payment=False,
        converted=False,
    )
    envelope = EventEnvelope(
        event_id=uuid4(),
        organization_id=org_id,
        event_type=EventType.SESSION,
        occurred_at=OCCURRED_AT,
        idempotency_key=f"session:{payload.session_id}",
        payload=payload,
    )
    return envelope.model_dump(mode="json")


def test_health_does_not_require_authentication() -> None:
    response = client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "test"}


def test_ingest_accepts_valid_events_for_the_authenticated_org() -> None:
    response = client().post(
        "/v1/events/batches",
        headers={"Authorization": f"Bearer {token(Role.OPERATOR)}"},
        json={"events": [session_event()]},
    )

    assert response.status_code == 202
    assert response.json() == {"accepted_count": 1, "duplicate_count": 0}


def test_ingest_counts_retried_events_as_duplicates() -> None:
    api = client()
    event = session_event()
    headers = {"Authorization": f"Bearer {token(Role.OPERATOR)}"}

    first = api.post("/v1/events/batches", headers=headers, json={"events": [event]})
    second = api.post("/v1/events/batches", headers=headers, json={"events": [event]})

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json() == {"accepted_count": 0, "duplicate_count": 1}


def test_metrics_endpoint_reads_ingested_events_for_the_authenticated_org() -> None:
    api = client()
    event = session_event()
    ingest_headers = {"Authorization": f"Bearer {token(Role.OPERATOR)}"}
    read_headers = {"Authorization": f"Bearer {token(Role.VIEWER)}"}

    ingest = api.post("/v1/events/batches", headers=ingest_headers, json={"events": [event]})
    metrics = api.get("/v1/metrics/funnel", headers=read_headers)

    assert ingest.status_code == 202
    assert metrics.status_code == 200
    assert metrics.json()["total_sessions"] == 1
    assert metrics.json()["checkout_sessions"] == 1


def test_ingest_rejects_idempotency_key_conflicts() -> None:
    api = client()
    event = session_event()
    conflicting = deepcopy(event)
    conflicting["event_id"] = str(uuid4())
    headers = {"Authorization": f"Bearer {token(Role.OPERATOR)}"}

    first = api.post("/v1/events/batches", headers=headers, json={"events": [event]})
    second = api.post("/v1/events/batches", headers=headers, json={"events": [conflicting]})

    assert first.status_code == 202
    assert second.status_code == 409


def test_ingest_requires_the_events_ingest_permission() -> None:
    response = client().post(
        "/v1/events/batches",
        headers={"Authorization": f"Bearer {token(Role.VIEWER)}"},
        json={"events": [session_event()]},
    )

    assert response.status_code == 403


def test_ingest_rejects_foreign_organization_events() -> None:
    response = client().post(
        "/v1/events/batches",
        headers={"Authorization": f"Bearer {token(Role.OPERATOR)}"},
        json={"events": [session_event(org_id=uuid4())]},
    )

    assert response.status_code == 403


def test_ingest_rejects_batches_over_the_configured_limit() -> None:
    response = client().post(
        "/v1/events/batches",
        headers={"Authorization": f"Bearer {token(Role.OPERATOR)}"},
        json={"events": [session_event(), session_event(), session_event()]},
    )

    assert response.status_code == 413
