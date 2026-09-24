"""Declarative configuration for the synthetic business simulator.

Every knob that shapes a dataset lives here and is serialisable, so a scenario file
fully determines a run. Defaults describe a plausible mid-size e-commerce SaaS; they
are *assumptions*, documented in ``docs/EVALUATION.md``, not measurements of any real
business.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from niglas_schemas.enums import (
    Currency,
    DeploymentStatus,
    PaymentMethod,
    PlanTier,
    Platform,
    Region,
)
from niglas_schemas.types import ShortName, UtcDatetime

GENERATOR_VERSION = "1.0.0"
"""Bump on any change that alters generated output for an unchanged seed."""

# Relative traffic by hour of day (UTC), peaking in the evening of the largest market.
DEFAULT_HOUR_OF_DAY_FACTORS: tuple[float, ...] = (
    0.45,
    0.35,
    0.30,
    0.28,
    0.30,
    0.38,
    0.55,
    0.78,
    0.95,
    1.08,
    1.15,
    1.18,
    1.20,
    1.22,
    1.25,
    1.30,
    1.38,
    1.45,
    1.50,
    1.42,
    1.25,
    1.00,
    0.75,
    0.55,
)
# Relative traffic by weekday, Monday = index 0.
DEFAULT_DAY_OF_WEEK_FACTORS: tuple[float, ...] = (1.05, 1.08, 1.06, 1.04, 0.98, 0.82, 0.78)


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SegmentMix(_Config):
    """Relative weights for each dimension. Weights need not sum to 1."""

    platform: dict[Platform, float] = Field(
        default_factory=lambda: {Platform.IOS: 0.34, Platform.ANDROID: 0.31, Platform.WEB: 0.35}
    )
    region: dict[Region, float] = Field(
        default_factory=lambda: {
            Region.NA: 0.45,
            Region.EU: 0.30,
            Region.APAC: 0.17,
            Region.LATAM: 0.08,
        }
    )
    plan_tier: dict[PlanTier, float] = Field(
        default_factory=lambda: {PlanTier.FREE: 0.55, PlanTier.PRO: 0.35, PlanTier.ENTERPRISE: 0.10}
    )
    payment_method: dict[PaymentMethod, float] = Field(
        default_factory=lambda: {
            PaymentMethod.VISA: 0.46,
            PaymentMethod.MASTERCARD: 0.28,
            PaymentMethod.AMEX: 0.11,
            PaymentMethod.PAYPAL: 0.15,
        }
    )

    @model_validator(mode="after")
    def _weights_are_positive(self) -> "SegmentMix":
        for name in ("platform", "region", "plan_tier", "payment_method"):
            weights: dict[object, float] = getattr(self, name)
            if not weights:
                raise ValueError(f"{name} mix must not be empty")
            if any(weight <= 0 for weight in weights.values()):
                raise ValueError(f"{name} mix weights must be positive")
        return self


class TrafficConfig(_Config):
    """Session arrival process: level, seasonality, trend and noise."""

    base_sessions_per_hour: float = Field(default=120.0, gt=0)
    hour_of_day_factors: tuple[float, ...] = DEFAULT_HOUR_OF_DAY_FACTORS
    day_of_week_factors: tuple[float, ...] = DEFAULT_DAY_OF_WEEK_FACTORS
    daily_growth_rate: float = Field(default=0.0012, ge=-0.05, le=0.05)
    """Compounding day-over-day trend, e.g. 0.0012 = +0.12%/day."""

    @model_validator(mode="after")
    def _factor_lengths(self) -> "TrafficConfig":
        if len(self.hour_of_day_factors) != 24:
            raise ValueError("hour_of_day_factors must have 24 entries")
        if len(self.day_of_week_factors) != 7:
            raise ValueError("day_of_week_factors must have 7 entries")
        if any(factor <= 0 for factor in (*self.hour_of_day_factors, *self.day_of_week_factors)):
            raise ValueError("seasonality factors must be positive")
        return self


class FunnelConfig(_Config):
    """Baseline conversion funnel and the segment effects that modulate it."""

    checkout_rate: float = Field(default=0.42, gt=0, le=1)
    """P(session reaches checkout)."""
    payment_rate: float = Field(default=0.61, gt=0, le=1)
    """P(reaches payment | reached checkout)."""
    payment_success_rate: float = Field(default=0.965, gt=0, le=1)
    """P(a payment attempt succeeds) before any fault."""
    retry_probability: float = Field(default=0.55, ge=0, le=1)
    """P(customer retries once | first attempt failed)."""
    platform_checkout_multiplier: dict[Platform, float] = Field(
        default_factory=lambda: {Platform.IOS: 1.06, Platform.ANDROID: 0.97, Platform.WEB: 1.0}
    )
    plan_tier_payment_multiplier: dict[PlanTier, float] = Field(
        default_factory=lambda: {PlanTier.FREE: 0.86, PlanTier.PRO: 1.05, PlanTier.ENTERPRISE: 1.12}
    )
    method_success_delta: dict[PaymentMethod, float] = Field(
        default_factory=lambda: {
            PaymentMethod.VISA: 0.004,
            PaymentMethod.MASTERCARD: 0.002,
            PaymentMethod.AMEX: -0.010,
            PaymentMethod.PAYPAL: -0.004,
        }
    )
    """Additive adjustment to payment success probability, by method."""


class CatalogItem(_Config):
    sku: ShortName
    unit_amount_minor: int = Field(gt=0)
    weight: float = Field(default=1.0, gt=0)


class OrderConfig(_Config):
    """How an order's value is drawn once a payment succeeds."""

    currency: Currency = Currency.USD
    catalog: tuple[CatalogItem, ...] = (
        CatalogItem(sku="starter-seat", unit_amount_minor=2900, weight=0.40),
        CatalogItem(sku="team-seat", unit_amount_minor=7900, weight=0.32),
        CatalogItem(sku="growth-addon", unit_amount_minor=14900, weight=0.18),
        CatalogItem(sku="enterprise-seat", unit_amount_minor=39900, weight=0.10),
    )
    max_lines: int = Field(default=3, ge=1, le=10)
    quantity_lambda: float = Field(default=0.7, ge=0)
    """Mean of the Poisson draw added to a base quantity of 1."""

    @model_validator(mode="after")
    def _catalog_not_empty(self) -> "OrderConfig":
        if not self.catalog:
            raise ValueError("catalog must contain at least one item")
        return self


class DeploymentSpec(_Config):
    """A deployment to emit, and the client version it puts into the field.

    ``client_platforms`` is what links a deployment to sessions: a deployment of the
    Android client changes ``app_version`` only for Android sessions after
    ``deployed_at``, which is the signal the correlation engine is meant to find.
    """

    service: ShortName
    version: ShortName
    deployed_at: UtcDatetime
    status: DeploymentStatus = DeploymentStatus.SUCCEEDED
    commit_sha: str = Field(min_length=7, max_length=40)
    description: str = Field(default="", max_length=500)
    client_platforms: tuple[Platform, ...] = ()


class WorldConfig(_Config):
    """A complete, reproducible description of one synthetic world."""

    organization_id: UUID
    seed: int = Field(ge=0)
    start: UtcDatetime
    duration_hours: int = Field(gt=0, le=24 * 400)
    customer_pool_size: int = Field(default=20_000, gt=0)
    baseline_app_version: ShortName = "2.7.0"
    traffic: TrafficConfig = Field(default_factory=TrafficConfig)
    funnel: FunnelConfig = Field(default_factory=FunnelConfig)
    orders: OrderConfig = Field(default_factory=OrderConfig)
    mix: SegmentMix = Field(default_factory=SegmentMix)
    deployments: tuple[DeploymentSpec, ...] = ()

    @model_validator(mode="after")
    def _deployments_within_window(self) -> "WorldConfig":
        from datetime import timedelta

        end = self.start + timedelta(hours=self.duration_hours)
        for deployment in self.deployments:
            if not self.start <= deployment.deployed_at < end:
                raise ValueError(
                    f"deployment {deployment.service}@{deployment.version} at "
                    f"{deployment.deployed_at.isoformat()} falls outside the simulated window"
                )
        return self
