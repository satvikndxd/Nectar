"""Scenario files are the benchmark's source of truth; they must stay loadable."""

from pathlib import Path

import pytest

from niglas_generator.config import GENERATOR_VERSION
from niglas_generator.scenarios import (
    ScenarioSpec,
    ScenarioVersionError,
    dump_scenario,
    load_scenario,
    load_scenarios,
)

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "data" / "scenarios"


def all_scenarios() -> list[ScenarioSpec]:
    return load_scenarios(SCENARIO_DIR)


def test_the_scenario_directory_is_not_empty():
    assert all_scenarios()


@pytest.mark.parametrize("spec", all_scenarios(), ids=lambda spec: spec.scenario_id)
def test_every_scenario_generates_and_declares_its_truth(spec: ScenarioSpec):
    dataset = spec.generate()
    truth = dataset.ground_truth
    assert dataset.events
    assert truth.scenario_id == spec.scenario_id
    assert truth.generator_version == GENERATOR_VERSION
    assert truth.has_incident == bool(spec.faults)
    if spec.faults:
        assert truth.lost_orders > 0
        assert truth.true_revenue_loss_minor > 0
        assert truth.expected_evidence
        assert truth.acceptable_recommendations


def test_the_reference_scenario_matches_the_documented_shape():
    """The canonical demo: an Android/Visa payment regression tied to a deployment."""
    spec = load_scenario(SCENARIO_DIR / "ref-001-android-visa-payment-regression.json")
    dataset = spec.generate()
    truth = dataset.ground_truth

    assert truth.affected_dimensions == {"platform": ["android"], "payment_method": ["visa"]}
    assert truth.linked_deployment_version == "2.8.0"
    assert truth.actual_window is not None and truth.counterfactual_window is not None
    assert truth.actual_window.payment_failure_rate > (
        truth.counterfactual_window.payment_failure_rate * 1.5
    )
    assert truth.actual_window.conversion_rate < truth.counterfactual_window.conversion_rate
    # The distractor deployment must be present but uninvolved in the cause.
    versions = {spec_.version for spec_ in spec.world.deployments}
    assert versions == {"2.7.4", "2.8.0"}
    assert "roll back deployment checkout-web 2.7.4" in spec.unacceptable_recommendations


def test_a_scenario_from_another_generator_version_is_rejected(tmp_path: Path):
    spec = all_scenarios()[0]
    stale = spec.model_copy(update={"generator_version": "0.0.1-archived"})
    path = tmp_path / "stale.json"
    dump_scenario(stale, path)
    with pytest.raises(ScenarioVersionError, match="not reproducible"):
        load_scenario(path)
    assert load_scenario(path, require_current_version=False).scenario_id == spec.scenario_id


def test_scenarios_round_trip_through_disk(tmp_path: Path):
    spec = all_scenarios()[0]
    path = tmp_path / "round-trip.json"
    dump_scenario(spec, path)
    assert load_scenario(path) == spec


def test_a_fault_that_does_nothing_is_rejected(tmp_path: Path):
    spec = all_scenarios()[0]
    broken = spec.model_dump(mode="json")
    broken["faults"][0]["payment_success_drop"] = 0.0
    (tmp_path / "broken.json").write_text(__import__("json").dumps(broken), encoding="utf-8")
    with pytest.raises(ValueError, match="declares no effect"):
        load_scenario(tmp_path / "broken.json")
