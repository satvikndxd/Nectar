"""Injected faults and the ground truth they carry.

A fault is a *declared* deviation from normal behaviour, scoped to a time window and
a set of dimensions. Faults change only funnel probabilities - never how many sessions
occur or what dimensions they have - which is what keeps the counterfactual run
comparable session-for-session (see :mod:`niglas_generator.rng`).

Each fault also declares its own ground truth: the root cause a correct investigation
should land on, and the dimensions a correct localisation should name. That declaration
is what makes detection and root-cause accuracy measurable instead of eyeballed.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from niglas_generator.dimensions import SessionDimensions
from niglas_schemas.enums import PaymentMethod, PlanTier, Platform, Region


class RootCauseCategory(StrEnum):
    """Coarse cause taxonomy that root-cause accuracy is scored against."""

    DEPLOYMENT_REGRESSION = "deployment_regression"
    PAYMENT_PROVIDER_DEGRADATION = "payment_provider_degradation"
    INFRASTRUCTURE_INCIDENT = "infrastructure_incident"
    PRICING_OR_PRODUCT_CHANGE = "pricing_or_product_change"
    EXTERNAL_DEMAND_SHIFT = "external_demand_shift"
    NO_INCIDENT = "no_incident"


@dataclass(frozen=True, slots=True)
class DimensionFilter:
    """Which sessions a fault applies to. An empty tuple means "any value".

    Filters are intersected across axes: ``platforms=(ANDROID,)`` with
    ``payment_methods=(VISA,)`` matches only Android+Visa sessions, which is how
    segment-specific failures are expressed.
    """

    platforms: tuple[Platform, ...] = ()
    regions: tuple[Region, ...] = ()
    plan_tiers: tuple[PlanTier, ...] = ()
    payment_methods: tuple[PaymentMethod, ...] = ()
    app_versions: tuple[str, ...] = ()

    def matches(self, dimensions: SessionDimensions) -> bool:
        return (
            (not self.platforms or dimensions.platform in self.platforms)
            and (not self.regions or dimensions.region in self.regions)
            and (not self.plan_tiers or dimensions.plan_tier in self.plan_tiers)
            and (not self.payment_methods or dimensions.payment_method in self.payment_methods)
            and (not self.app_versions or dimensions.app_version in self.app_versions)
        )

    def as_dict(self) -> dict[str, list[str]]:
        """Serialisable form, used when writing ground truth."""
        return {
            axis: [str(value) for value in values]
            for axis, values in (
                ("platform", self.platforms),
                ("region", self.regions),
                ("plan_tier", self.plan_tiers),
                ("payment_method", self.payment_methods),
                ("app_version", self.app_versions),
            )
            if values
        }


@dataclass(frozen=True, slots=True)
class FunnelEffect:
    """A multiplicative/additive adjustment to one session's funnel probabilities."""

    checkout_rate_multiplier: float = 1.0
    payment_rate_multiplier: float = 1.0
    payment_success_delta: float = 0.0
    failure_code: str | None = None

    def combined_with(self, other: "FunnelEffect") -> "FunnelEffect":
        """Compose two effects. Multipliers multiply, deltas add.

        The first effect to name a ``failure_code`` wins, so overlapping faults do not
        silently relabel each other's failures.
        """
        return FunnelEffect(
            checkout_rate_multiplier=self.checkout_rate_multiplier * other.checkout_rate_multiplier,
            payment_rate_multiplier=self.payment_rate_multiplier * other.payment_rate_multiplier,
            payment_success_delta=self.payment_success_delta + other.payment_success_delta,
            failure_code=self.failure_code or other.failure_code,
        )


NO_EFFECT = FunnelEffect()


@dataclass(frozen=True, slots=True)
class Fault:
    """A scoped deviation with declared ground truth.

    Args:
        fault_id: Stable identifier, referenced by ground truth and scenario files.
        starts_at: When the deviation begins (inclusive).
        ends_at: When it stops, or ``None`` for "still active at the end of the run".
        effect: The effect at full strength.
        targets: Which sessions are affected.
        ramp: How long the effect takes to reach full strength. ``0`` is a step change
            (a deploy regression); a non-zero ramp models gradual degradation
            (a leaking resource), which detectors find much harder.
        root_cause_category: Coarse cause, scored top-1 against the agent's answer.
        root_cause_detail: Human-readable specific cause.
        linked_deployment_version: Deployment a correct investigation should cite, if any.
    """

    fault_id: str
    starts_at: datetime
    ends_at: datetime | None
    effect: FunnelEffect
    targets: DimensionFilter = field(default_factory=DimensionFilter)
    ramp_minutes: float = 0.0
    root_cause_category: RootCauseCategory = RootCauseCategory.DEPLOYMENT_REGRESSION
    root_cause_detail: str = ""
    linked_deployment_version: str | None = None

    def __post_init__(self) -> None:
        if self.starts_at.tzinfo is None:
            raise ValueError("fault starts_at must be timezone-aware")
        if self.ends_at is not None:
            if self.ends_at.tzinfo is None:
                raise ValueError("fault ends_at must be timezone-aware")
            if self.ends_at <= self.starts_at:
                raise ValueError("fault ends_at must be after starts_at")
        if self.ramp_minutes < 0:
            raise ValueError("ramp_minutes must be non-negative")

    def effect_at(self, moment: datetime, dimensions: SessionDimensions) -> FunnelEffect:
        """The effect on a session at ``moment``, or :data:`NO_EFFECT`."""
        if moment < self.starts_at or (self.ends_at is not None and moment >= self.ends_at):
            return NO_EFFECT
        if not self.targets.matches(dimensions):
            return NO_EFFECT
        strength = self._strength_at(moment)
        if strength >= 1.0:
            return self.effect
        return FunnelEffect(
            checkout_rate_multiplier=1.0 + (self.effect.checkout_rate_multiplier - 1.0) * strength,
            payment_rate_multiplier=1.0 + (self.effect.payment_rate_multiplier - 1.0) * strength,
            payment_success_delta=self.effect.payment_success_delta * strength,
            failure_code=self.effect.failure_code,
        )

    def _strength_at(self, moment: datetime) -> float:
        if self.ramp_minutes <= 0:
            return 1.0
        elapsed_minutes = (moment - self.starts_at).total_seconds() / 60.0
        return min(1.0, elapsed_minutes / self.ramp_minutes)


def payment_failure_spike(
    *,
    fault_id: str,
    starts_at: datetime,
    ends_at: datetime | None,
    success_drop: float,
    failure_code: str,
    targets: DimensionFilter,
    root_cause_category: RootCauseCategory = RootCauseCategory.DEPLOYMENT_REGRESSION,
    root_cause_detail: str = "",
    linked_deployment_version: str | None = None,
    ramp_minutes: float = 0.0,
) -> Fault:
    """Build the most common fault shape: payment success drops for a segment.

    Args:
        success_drop: Absolute reduction in payment success probability, e.g. ``0.25``
            turns a 96.5% success rate into 71.5% for matching sessions.
    """
    if not 0 < success_drop <= 1:
        raise ValueError("success_drop must be in (0, 1]")
    return Fault(
        fault_id=fault_id,
        starts_at=starts_at,
        ends_at=ends_at,
        effect=FunnelEffect(payment_success_delta=-success_drop, failure_code=failure_code),
        targets=targets,
        ramp_minutes=ramp_minutes,
        root_cause_category=root_cause_category,
        root_cause_detail=root_cause_detail,
        linked_deployment_version=linked_deployment_version,
    )
