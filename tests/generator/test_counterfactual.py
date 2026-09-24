"""The counterfactual contract.

Ground truth is only meaningful if the faulted run and the fault-free run differ
*solely* because of the fault. These tests pin that property down; if they fail, every
impact number derived from the generator is suspect.
"""

import pytest

from niglas_generator.dataset import generate
from niglas_generator.groundtruth import CounterfactualMismatchError, compute_ground_truth
from niglas_generator.outcomes import SimulationResult
from niglas_generator.simulator import simulate
from niglas_schemas.enums import PaymentMethod, Platform


def test_fault_does_not_change_which_sessions_occur(config, android_visa_fault):
    faulted = simulate(config, [android_visa_fault])
    clean = simulate(config, [])
    assert len(faulted.sessions) == len(clean.sessions)
    assert [s.session_id for s in faulted.sessions] == [s.session_id for s in clean.sessions]


def test_fault_does_not_change_session_dimensions_or_customers(config, android_visa_fault):
    faulted = {s.session_id: s for s in simulate(config, [android_visa_fault]).sessions}
    clean = {s.session_id: s for s in simulate(config, []).sessions}
    for session_id, faulted_session in faulted.items():
        clean_session = clean[session_id]
        assert faulted_session.dimensions == clean_session.dimensions
        assert faulted_session.customer_id == clean_session.customer_id
        assert faulted_session.started_at == clean_session.started_at
        assert faulted_session.basket == clean_session.basket


def test_sessions_outside_the_fault_target_are_bit_identical(config, android_visa_fault):
    """An Android+Visa fault must leave every other session completely untouched."""
    faulted = {s.session_id: s for s in simulate(config, [android_visa_fault]).sessions}
    clean = {s.session_id: s for s in simulate(config, []).sessions}
    untargeted = [
        session_id
        for session_id, session in clean.items()
        if not (
            session.dimensions.platform is Platform.ANDROID
            and session.dimensions.payment_method is PaymentMethod.VISA
        )
    ]
    assert untargeted, "fixture should leave some sessions untargeted"
    for session_id in untargeted:
        assert faulted[session_id] == clean[session_id]


def test_sessions_before_the_fault_window_are_bit_identical(config, android_visa_fault):
    faulted = {s.session_id: s for s in simulate(config, [android_visa_fault]).sessions}
    clean = {s.session_id: s for s in simulate(config, []).sessions}
    before = [sid for sid, s in clean.items() if s.started_at < android_visa_fault.starts_at]
    assert before, "fixture should include pre-incident sessions"
    for session_id in before:
        assert faulted[session_id] == clean[session_id]


def test_ground_truth_revenue_loss_equals_the_baskets_of_lost_conversions(
    config, android_visa_fault
):
    dataset = generate(config=config, faults=[android_visa_fault])
    faulted = {s.session_id: s for s in dataset.result.sessions}
    clean = {s.session_id: s for s in dataset.counterfactual.sessions}
    expected_loss = sum(
        clean[sid].basket_amount_minor
        for sid in clean
        if clean[sid].converted and not faulted[sid].converted
    ) - sum(
        faulted[sid].basket_amount_minor
        for sid in faulted
        if faulted[sid].converted and not clean[sid].converted
    )
    assert dataset.ground_truth.true_revenue_loss_minor == expected_loss
    assert dataset.ground_truth.lost_orders > 0


def test_ground_truth_reports_the_declared_cause(config, android_visa_fault):
    truth = generate(config=config, faults=[android_visa_fault]).ground_truth
    assert truth.has_incident
    assert truth.root_cause_category is android_visa_fault.root_cause_category
    assert truth.linked_deployment_version == "2.8.0"
    assert truth.affected_dimensions == {"platform": ["android"], "payment_method": ["visa"]}
    assert truth.incident_start == android_visa_fault.starts_at


def test_a_world_without_faults_has_no_incident_and_no_loss(config):
    truth = generate(config=config).ground_truth
    assert not truth.has_incident
    assert truth.lost_orders == 0
    assert truth.true_revenue_loss_minor == 0
    assert truth.incident_start is None
    assert truth.actual_window is None


def test_mismatched_runs_are_rejected_rather_than_silently_differenced(config):
    result = simulate(config, [])
    truncated = SimulationResult(sessions=result.sessions[:-1], deployments=result.deployments)
    with pytest.raises(CounterfactualMismatchError, match="not comparable"):
        compute_ground_truth(
            scenario_id="broken",
            config=config,
            faults=[],
            actual=result,
            counterfactual=truncated,
        )
