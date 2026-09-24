"""Small, fast worlds for generator tests.

Tests use a low traffic level and a short window so the whole suite stays in
seconds; determinism properties do not depend on scale.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from niglas_generator.config import DeploymentSpec, TrafficConfig, WorldConfig
from niglas_generator.faults import DimensionFilter, Fault, payment_failure_spike
from niglas_schemas.enums import PaymentMethod, Platform

ORG_ID = UUID("018f2d3c-0000-7000-8000-0000000000aa")
START = datetime(2026, 9, 1, tzinfo=UTC)
DEPLOYED_AT = START + timedelta(days=1, hours=6)


@pytest.fixture
def config() -> WorldConfig:
    return WorldConfig(
        organization_id=ORG_ID,
        seed=1234,
        start=START,
        duration_hours=48,
        customer_pool_size=500,
        traffic=TrafficConfig(base_sessions_per_hour=40.0),
        deployments=(
            DeploymentSpec(
                service="checkout-android",
                version="2.8.0",
                deployed_at=DEPLOYED_AT,
                commit_sha="abc1234def",
                description="Android payment SDK upgrade",
                client_platforms=(Platform.ANDROID,),
            ),
        ),
    )


@pytest.fixture
def android_visa_fault() -> Fault:
    return payment_failure_spike(
        fault_id="android-visa",
        starts_at=DEPLOYED_AT,
        ends_at=None,
        success_drop=0.30,
        failure_code="sdk_tokenization_error",
        targets=DimensionFilter(
            platforms=(Platform.ANDROID,), payment_methods=(PaymentMethod.VISA,)
        ),
        root_cause_detail="Android client 2.8.0 fails Visa tokenization",
        linked_deployment_version="2.8.0",
    )
