"""The dimensions a session carries through the funnel.

These are the axes the anomaly engine localises along ("failures are concentrated in
Visa transactions on Android"), so they are fixed on the session at creation time and
never re-drawn.
"""

from dataclasses import dataclass

from niglas_schemas.enums import PaymentMethod, PlanTier, Platform, Region


@dataclass(frozen=True, slots=True)
class SessionDimensions:
    platform: Platform
    region: Region
    plan_tier: PlanTier
    payment_method: PaymentMethod
    app_version: str
