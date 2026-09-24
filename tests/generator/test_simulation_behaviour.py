"""The simulated world must behave like the business it claims to model.

These assertions are deliberately loose - the point is that seasonality, segment
effects and faults show up with the right sign and rough size, not that a particular
seed produces a particular number.
"""

from collections import Counter
from datetime import timedelta

import pytest

from niglas_generator.config import TrafficConfig
from niglas_generator.simulator import simulate
from niglas_schemas.enums import PaymentMethod, Platform


def failure_rate(sessions, predicate) -> float:
    attempts = [a for s in sessions if predicate(s) for a in s.attempts]
    if not attempts:
        return 0.0
    return sum(1 for a in attempts if not a.succeeded) / len(attempts)


def test_traffic_follows_the_configured_daily_seasonality(config):
    sessions = simulate(config.model_copy(update={"duration_hours": 24 * 6}), []).sessions
    by_hour = Counter(session.started_at.hour for session in sessions)
    peak_hour = max(by_hour, key=lambda hour: by_hour[hour])
    trough_hour = min(by_hour, key=lambda hour: by_hour[hour])
    factors = config.traffic.hour_of_day_factors
    assert factors[peak_hour] > factors[trough_hour]
    assert by_hour[peak_hour] > by_hour[trough_hour]


def test_funnel_is_monotonic_for_every_session(config):
    for session in simulate(config, []).sessions:
        assert session.reached_checkout or not session.reached_payment
        assert session.reached_payment or not session.attempts
        assert session.reached_payment or not session.converted


def test_a_session_converts_exactly_when_a_payment_succeeded(config):
    for session in simulate(config, []).sessions:
        assert session.converted == any(attempt.succeeded for attempt in session.attempts)
        assert session.revenue_minor == (session.basket_amount_minor if session.converted else 0)


def test_no_session_retries_more_than_once(config):
    for session in simulate(config, []).sessions:
        assert len(session.attempts) <= 2
        assert [a.attempt_number for a in session.attempts] == list(
            range(1, len(session.attempts) + 1)
        )
        # A retry only follows a failure.
        assert all(not attempt.succeeded for attempt in session.attempts[:-1])


def test_every_basket_has_a_positive_amount(config):
    for session in simulate(config, []).sessions:
        assert session.basket
        assert session.basket_amount_minor > 0
        assert all(line.quantity >= 1 for line in session.basket)


def test_the_fault_raises_failure_rate_in_the_targeted_segment_only(config, android_visa_fault):
    faulted = simulate(config, [android_visa_fault]).sessions
    clean = simulate(config, []).sessions
    after = android_visa_fault.starts_at

    def targeted(session) -> bool:
        return (
            session.started_at >= after
            and session.dimensions.platform is Platform.ANDROID
            and session.dimensions.payment_method is PaymentMethod.VISA
        )

    def untargeted(session) -> bool:
        return session.started_at >= after and not (
            session.dimensions.platform is Platform.ANDROID
            and session.dimensions.payment_method is PaymentMethod.VISA
        )

    assert failure_rate(faulted, targeted) > failure_rate(clean, targeted) + 0.10
    assert failure_rate(faulted, untargeted) == pytest.approx(
        failure_rate(clean, untargeted), abs=1e-9
    )


def test_faulted_failures_carry_the_fault_failure_code(config, android_visa_fault):
    sessions = simulate(config, [android_visa_fault]).sessions
    before = {
        attempt.failure_code
        for session in sessions
        if session.started_at < android_visa_fault.starts_at
        for attempt in session.attempts
        if not attempt.succeeded
    }
    after = {
        attempt.failure_code
        for session in sessions
        if session.started_at >= android_visa_fault.starts_at
        and session.dimensions.platform is Platform.ANDROID
        and session.dimensions.payment_method is PaymentMethod.VISA
        for attempt in session.attempts
        if not attempt.succeeded
    }
    assert "sdk_tokenization_error" not in before
    assert after == {"sdk_tokenization_error"}


def test_android_sessions_report_the_deployed_version_only_after_the_deployment(config):
    deployment = config.deployments[0]
    for session in simulate(config, []).sessions:
        if (
            session.dimensions.platform is not Platform.ANDROID
            or session.started_at < deployment.deployed_at
        ):
            assert session.dimensions.app_version == config.baseline_app_version
        else:
            assert session.dimensions.app_version == deployment.version


def test_growth_rate_lifts_later_days(config):
    growing = config.model_copy(
        update={
            "duration_hours": 24 * 10,
            "traffic": TrafficConfig(base_sessions_per_hour=60.0, daily_growth_rate=0.05),
        }
    )
    sessions = simulate(growing, []).sessions
    day_one_end = growing.start + timedelta(days=1)
    day_ten_start = growing.start + timedelta(days=9)
    first_day = sum(1 for s in sessions if s.started_at < day_one_end)
    last_day = sum(1 for s in sessions if s.started_at >= day_ten_start)
    assert last_day > first_day
