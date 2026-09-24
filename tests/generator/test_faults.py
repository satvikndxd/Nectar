"""Fault semantics: scope, ramp and effect composition."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from niglas_generator.dimensions import SessionDimensions
from niglas_generator.faults import (
    NO_EFFECT,
    DimensionFilter,
    Fault,
    FunnelEffect,
    RootCauseCategory,
    payment_failure_spike,
)
from niglas_schemas.enums import PaymentMethod, PlanTier, Platform, Region

START = datetime(2026, 9, 2, 12, tzinfo=UTC)
END = START + timedelta(hours=6)

ANDROID_VISA = SessionDimensions(
    platform=Platform.ANDROID,
    region=Region.EU,
    plan_tier=PlanTier.PRO,
    payment_method=PaymentMethod.VISA,
    app_version="2.8.0",
)
IOS_VISA = replace(ANDROID_VISA, platform=Platform.IOS)
ANDROID_AMEX = replace(ANDROID_VISA, payment_method=PaymentMethod.AMEX)


def spike(**overrides: object) -> Fault:
    defaults: dict[str, object] = {
        "fault_id": "f1",
        "starts_at": START,
        "ends_at": END,
        "success_drop": 0.3,
        "failure_code": "sdk_tokenization_error",
        "targets": DimensionFilter(
            platforms=(Platform.ANDROID,), payment_methods=(PaymentMethod.VISA,)
        ),
    }
    return payment_failure_spike(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_effect_applies_only_inside_the_window():
    fault = spike()
    assert fault.effect_at(START, ANDROID_VISA).payment_success_delta == pytest.approx(-0.3)
    assert fault.effect_at(START - timedelta(seconds=1), ANDROID_VISA) is NO_EFFECT
    assert fault.effect_at(END, ANDROID_VISA) is NO_EFFECT


def test_open_ended_fault_never_stops():
    fault = spike(ends_at=None)
    assert fault.effect_at(START + timedelta(days=365), ANDROID_VISA).payment_success_delta < 0


def test_dimension_filters_intersect_across_axes():
    fault = spike()
    assert fault.effect_at(START, ANDROID_VISA) is not NO_EFFECT
    assert fault.effect_at(START, IOS_VISA) is NO_EFFECT
    assert fault.effect_at(START, ANDROID_AMEX) is NO_EFFECT


def test_an_empty_filter_matches_everything():
    fault = spike(targets=DimensionFilter())
    assert fault.effect_at(START, IOS_VISA) is not NO_EFFECT
    assert fault.effect_at(START, ANDROID_AMEX) is not NO_EFFECT


def test_ramp_grows_the_effect_linearly_to_full_strength():
    fault = spike(ramp_minutes=60.0)
    at_start = fault.effect_at(START, ANDROID_VISA).payment_success_delta
    halfway = fault.effect_at(START + timedelta(minutes=30), ANDROID_VISA).payment_success_delta
    full = fault.effect_at(START + timedelta(minutes=90), ANDROID_VISA).payment_success_delta
    assert at_start == pytest.approx(0.0)
    assert halfway == pytest.approx(-0.15)
    assert full == pytest.approx(-0.3)


def test_effects_compose_multiplicatively_and_additively():
    first = FunnelEffect(checkout_rate_multiplier=0.8, payment_success_delta=-0.1)
    second = FunnelEffect(checkout_rate_multiplier=0.5, payment_success_delta=-0.2)
    combined = first.combined_with(second)
    assert combined.checkout_rate_multiplier == pytest.approx(0.4)
    assert combined.payment_success_delta == pytest.approx(-0.3)


def test_the_first_failure_code_wins_so_faults_do_not_relabel_each_other():
    first = FunnelEffect(failure_code="sdk_tokenization_error")
    second = FunnelEffect(failure_code="processor_timeout")
    assert first.combined_with(second).failure_code == "sdk_tokenization_error"
    assert NO_EFFECT.combined_with(second).failure_code == "processor_timeout"


@pytest.mark.parametrize("drop", [0.0, -0.1, 1.5])
def test_success_drop_must_be_a_usable_probability(drop):
    with pytest.raises(ValueError, match="success_drop"):
        spike(success_drop=drop)


def test_a_window_that_ends_before_it_starts_is_rejected():
    with pytest.raises(ValueError, match="after starts_at"):
        spike(ends_at=START - timedelta(hours=1))


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        spike(starts_at=datetime(2026, 9, 2, 12))  # noqa: DTZ001


def test_targets_serialise_only_the_axes_that_are_constrained():
    fault = spike()
    assert fault.targets.as_dict() == {"platform": ["android"], "payment_method": ["visa"]}
    assert DimensionFilter().as_dict() == {}


def test_default_cause_is_a_deployment_regression():
    assert spike().root_cause_category is RootCauseCategory.DEPLOYMENT_REGRESSION
