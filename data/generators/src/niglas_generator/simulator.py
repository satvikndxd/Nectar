"""The synthetic business simulator.

One call to :func:`simulate` produces a complete world: sessions arriving under
seasonality and noise, progressing through a checkout funnel, attempting payments that
may fail, and producing orders. Injected faults perturb funnel probabilities only.

Determinism contract
--------------------
For a fixed ``seed`` and ``GENERATOR_VERSION``:

* the same config produces identical output, and
* adding a fault changes only the outcomes of sessions the fault matches.

The second property holds because every session draws a *fixed number* of random
values from its own stream, in a fixed order, before any fault is consulted. A fault
can change which branch a draw selects, but never how many draws happen - so no
session's random sequence can shift because of another session's fault.
"""

import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from random import Random
from uuid import UUID

from niglas_generator.config import GENERATOR_VERSION, WorldConfig
from niglas_generator.dimensions import SessionDimensions
from niglas_generator.faults import NO_EFFECT, Fault, FunnelEffect
from niglas_generator.outcomes import (
    DeploymentOutcome,
    OrderLineOutcome,
    PaymentAttempt,
    SessionOutcome,
    SimulationResult,
)
from niglas_generator.rng import (
    StreamRandom,
    clamp_probability,
    lognormal_amount,
    poisson,
    weighted_choice,
)
from niglas_schemas.enums import Platform
from niglas_shared.ids import uuid7

MAX_PAYMENT_ATTEMPTS = 2
"""A first attempt plus at most one retry. Fixed so draw counts stay fault-independent."""

BASELINE_FAILURE_CODES: tuple[tuple[str, float], ...] = (
    ("insufficient_funds", 0.45),
    ("do_not_honor", 0.28),
    ("expired_card", 0.15),
    ("processor_timeout", 0.12),
)
"""Failure reasons in the absence of any fault, with relative weights."""

_MEDIAN_SESSION_SECONDS = 210.0
_SESSION_DURATION_SIGMA = 0.8
_PAYMENT_RETRY_DELAY = timedelta(seconds=75)


def simulate(config: WorldConfig, faults: Sequence[Fault] = ()) -> SimulationResult:
    """Run the simulation.

    Args:
        config: The world to simulate.
        faults: Faults to inject. Pass ``()`` to produce the counterfactual run used
            for ground-truth impact.
    """
    streams = StreamRandom(config.seed, GENERATOR_VERSION)
    deployments = _build_deployments(config)
    version_timeline = _version_timeline(config, deployments)

    sessions: list[SessionOutcome] = []
    for hour_index in range(config.duration_hours):
        hour_start = config.start + timedelta(hours=hour_index)
        arrivals = _arrivals_in_hour(config, streams, hour_index, hour_start)
        for session_index in range(arrivals):
            sessions.append(
                _simulate_session(
                    config=config,
                    streams=streams,
                    faults=faults,
                    hour_index=hour_index,
                    hour_start=hour_start,
                    session_index=session_index,
                    version_timeline=version_timeline,
                )
            )

    sessions.sort(key=lambda session: (session.started_at, session.session_id))
    return SimulationResult(sessions=tuple(sessions), deployments=deployments)


def _arrivals_in_hour(
    config: WorldConfig, streams: StreamRandom, hour_index: int, hour_start: datetime
) -> int:
    """Expected sessions for the hour, seasonally adjusted, drawn as a Poisson count.

    Keyed only by the hour, never by faults, so arrival counts are identical between a
    faulted run and its counterfactual.
    """
    traffic = config.traffic
    day_index = hour_index // 24
    expected = (
        traffic.base_sessions_per_hour
        * traffic.hour_of_day_factors[hour_start.hour]
        * traffic.day_of_week_factors[hour_start.weekday()]
        * math.pow(1.0 + traffic.daily_growth_rate, day_index)
    )
    return poisson(streams.stream("arrivals", hour_index), expected)


def _simulate_session(
    *,
    config: WorldConfig,
    streams: StreamRandom,
    faults: Sequence[Fault],
    hour_index: int,
    hour_start: datetime,
    session_index: int,
    version_timeline: dict[Platform, list[tuple[datetime, str]]],
) -> SessionOutcome:
    rng = streams.stream("session", hour_index, session_index)

    # --- Fixed-order, fixed-count draws. Do not add a conditional draw below. ---
    platform = weighted_choice(rng, tuple(config.mix.platform.items()))
    region = weighted_choice(rng, tuple(config.mix.region.items()))
    plan_tier = weighted_choice(rng, tuple(config.mix.plan_tier.items()))
    payment_method = weighted_choice(rng, tuple(config.mix.payment_method.items()))
    second_offset = rng.random() * 3600.0
    duration_seconds = lognormal_amount(rng, _MEDIAN_SESSION_SECONDS, _SESSION_DURATION_SIGMA)
    customer_index = rng.randrange(config.customer_pool_size)
    checkout_draw = rng.random()
    payment_draw = rng.random()
    attempt_draws = [rng.random() for _ in range(MAX_PAYMENT_ATTEMPTS)]
    retry_draw = rng.random()
    failure_code_draws = [rng.random() for _ in range(MAX_PAYMENT_ATTEMPTS)]
    order_draws = _draw_order(config, rng)
    session_id = uuid7(hour_start, rng)
    payment_ids = [uuid7(hour_start, rng) for _ in range(MAX_PAYMENT_ATTEMPTS)]
    order_id = uuid7(hour_start, rng)
    # --- End of fixed draws. ---

    started_at = hour_start + timedelta(seconds=second_offset)
    dimensions = SessionDimensions(
        platform=platform,
        region=region,
        plan_tier=plan_tier,
        payment_method=payment_method,
        app_version=_version_at(
            version_timeline, platform, started_at, config.baseline_app_version
        ),
    )
    effect = _effect_at(faults, started_at, dimensions)

    reached_checkout = checkout_draw < _checkout_probability(config, dimensions, effect)
    reached_payment = reached_checkout and payment_draw < _payment_probability(
        config, dimensions, effect
    )
    attempts = (
        _simulate_payments(
            config=config,
            dimensions=dimensions,
            effect=effect,
            started_at=started_at,
            attempt_draws=attempt_draws,
            retry_draw=retry_draw,
            failure_code_draws=failure_code_draws,
            payment_ids=payment_ids,
        )
        if reached_payment
        else ()
    )
    converted = any(attempt.succeeded for attempt in attempts)

    return SessionOutcome(
        session_id=session_id,
        customer_id=_customer_id(config, streams, customer_index),
        started_at=started_at,
        duration_ms=int(duration_seconds * 1000),
        dimensions=dimensions,
        reached_checkout=reached_checkout,
        reached_payment=reached_payment,
        attempts=attempts,
        basket=order_draws,
        order_id=order_id if converted else None,
    )


def _effect_at(
    faults: Sequence[Fault], moment: datetime, dimensions: SessionDimensions
) -> FunnelEffect:
    effect = NO_EFFECT
    for fault in faults:
        effect = effect.combined_with(fault.effect_at(moment, dimensions))
    return effect


def _checkout_probability(
    config: WorldConfig, dimensions: SessionDimensions, effect: FunnelEffect
) -> float:
    base = config.funnel.checkout_rate * config.funnel.platform_checkout_multiplier.get(
        dimensions.platform, 1.0
    )
    return clamp_probability(base * effect.checkout_rate_multiplier)


def _payment_probability(
    config: WorldConfig, dimensions: SessionDimensions, effect: FunnelEffect
) -> float:
    base = config.funnel.payment_rate * config.funnel.plan_tier_payment_multiplier.get(
        dimensions.plan_tier, 1.0
    )
    return clamp_probability(base * effect.payment_rate_multiplier)


def _payment_success_probability(
    config: WorldConfig, dimensions: SessionDimensions, effect: FunnelEffect
) -> float:
    base = config.funnel.payment_success_rate + config.funnel.method_success_delta.get(
        dimensions.payment_method, 0.0
    )
    return clamp_probability(base + effect.payment_success_delta)


def _simulate_payments(
    *,
    config: WorldConfig,
    dimensions: SessionDimensions,
    effect: FunnelEffect,
    started_at: datetime,
    attempt_draws: list[float],
    retry_draw: float,
    failure_code_draws: list[float],
    payment_ids: list[UUID],
) -> tuple[PaymentAttempt, ...]:
    """Run up to one retry after a failure.

    The retry decision uses a draw taken unconditionally in the caller, so a fault that
    turns a success into a failure does not shift any later draw.
    """
    success_probability = _payment_success_probability(config, dimensions, effect)
    attempts: list[PaymentAttempt] = []
    for attempt_number in range(1, MAX_PAYMENT_ATTEMPTS + 1):
        index = attempt_number - 1
        succeeded = attempt_draws[index] < success_probability
        attempts.append(
            PaymentAttempt(
                payment_id=payment_ids[index],
                attempt_number=attempt_number,
                attempted_at=started_at + _PAYMENT_RETRY_DELAY * index,
                succeeded=succeeded,
                failure_code=None
                if succeeded
                else _failure_code(effect, failure_code_draws[index]),
            )
        )
        if succeeded or retry_draw >= config.funnel.retry_probability:
            break
    return tuple(attempts)


def _failure_code(effect: FunnelEffect, draw: float) -> str:
    """Faulted failures carry the fault's code; baseline failures use the usual mix.

    The skew this creates in failure-code distribution is a primary piece of evidence
    for an investigation, which is why the fault's code is not blended with the others.
    """
    if effect.failure_code is not None:
        return effect.failure_code
    total = sum(weight for _, weight in BASELINE_FAILURE_CODES)
    threshold = draw * total
    cumulative = 0.0
    for code, weight in BASELINE_FAILURE_CODES:
        cumulative += weight
        if threshold < cumulative:
            return code
    return BASELINE_FAILURE_CODES[-1][0]


def _draw_order(config: WorldConfig, rng: Random) -> tuple[OrderLineOutcome, ...]:
    """Draw an order's lines.

    Drawn for every session, converted or not, so that draw counts do not depend on the
    outcome. Unconverted sessions simply discard the result.
    """
    catalog = tuple((item, item.weight) for item in config.orders.catalog)
    line_count = 1 + int(rng.random() * config.orders.max_lines)
    lines: list[OrderLineOutcome] = []
    for _ in range(config.orders.max_lines):
        item = weighted_choice(rng, catalog)
        quantity = 1 + poisson(rng, config.orders.quantity_lambda)
        lines.append(
            OrderLineOutcome(
                sku=item.sku, quantity=quantity, unit_amount_minor=item.unit_amount_minor
            )
        )
    return tuple(lines[:line_count])


def _customer_id(config: WorldConfig, streams: StreamRandom, customer_index: int) -> UUID:
    """Stable id for a member of the customer pool."""
    return uuid7(config.start, streams.stream("customer", customer_index))


def _build_deployments(config: WorldConfig) -> tuple[DeploymentOutcome, ...]:
    streams = StreamRandom(config.seed, GENERATOR_VERSION)
    return tuple(
        DeploymentOutcome(
            deployment_id=uuid7(
                spec.deployed_at, streams.stream("deployment", spec.service, spec.version)
            ),
            service=spec.service,
            version=spec.version,
            deployed_at=spec.deployed_at,
            status=str(spec.status),
            commit_sha=spec.commit_sha,
            description=spec.description,
        )
        for spec in sorted(config.deployments, key=lambda spec: spec.deployed_at)
    )


def _version_timeline(
    config: WorldConfig, deployments: tuple[DeploymentOutcome, ...]
) -> dict[Platform, list[tuple[datetime, str]]]:
    """When each platform started reporting each client version."""
    timeline: dict[Platform, list[tuple[datetime, str]]] = {platform: [] for platform in Platform}
    by_key = {(spec.service, spec.version): spec for spec in config.deployments}
    for deployment in deployments:
        spec = by_key[(deployment.service, deployment.version)]
        for platform in spec.client_platforms:
            timeline[platform].append((deployment.deployed_at, deployment.version))
    for entries in timeline.values():
        entries.sort(key=lambda entry: entry[0])
    return timeline


def _version_at(
    timeline: dict[Platform, list[tuple[datetime, str]]],
    platform: Platform,
    moment: datetime,
    baseline_version: str,
) -> str:
    version = baseline_version
    for deployed_at, deployed_version in timeline[platform]:
        if deployed_at <= moment:
            version = deployed_version
        else:
            break
    return version


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Small helper for building UTC instants in configs and tests."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


__all__ = ["BASELINE_FAILURE_CODES", "MAX_PAYMENT_ATTEMPTS", "simulate", "utc"]
