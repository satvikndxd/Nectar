"""The anomaly engine against generated scenarios (synthetic data).

These are regression tests on fixed seeds, not accuracy claims: benchmark numbers
belong to the evaluation harness (docs/EVALUATION.md).
"""

from datetime import timedelta
from pathlib import Path

import pytest

from niglas_anomaly.episodes import merge_episodes
from niglas_anomaly.localize import localize
from niglas_anomaly.monitor import monitor
from niglas_anomaly.series import RateMetric, observations
from niglas_generator.dataset import GeneratedDataset, generate
from niglas_generator.scenarios import load_scenario

SCENARIO = (
    Path(__file__).resolve().parents[2]
    / "data/scenarios/ref-001-android-visa-payment-regression.json"
)
M = RateMetric.PAYMENT_FAILURE_RATE


@pytest.fixture(scope="module")
def dataset() -> GeneratedDataset:
    return load_scenario(SCENARIO).generate()


def run_monitor(ds: GeneratedDataset):
    cfg = ds.config
    observed = observations(M, ds.events)
    end = cfg.start + timedelta(hours=cfg.duration_hours)
    return observed, end, monitor(M, observed, start=cfg.start, end=end)


def test_the_regression_is_detected_on_an_affected_slice_soon_after_onset(dataset):
    _, _, results = run_monitor(dataset)
    episodes = merge_episodes(a for r in results for a in r.run.anomalies)
    assert episodes, "reference incident was not detected"
    first = min(episodes, key=lambda e: e.first_detected_at)
    onset = dataset.ground_truth.incident_start
    assert onset is not None
    assert onset <= first.first_detected_at <= onset + timedelta(hours=8)
    assert first.first.filters in ({"platform": "android"}, {"payment_method": "visa"})
    # Nothing fires before the fault exists (the web deploy is a benign distractor).
    assert all(e.first_detected_at > onset for e in episodes)


def test_localisation_ranks_android_visa_as_the_top_pair(dataset):
    observed, end, results = run_monitor(dataset)
    first = min(
        merge_episodes(a for r in results for a in r.run.anomalies),
        key=lambda e: e.first_detected_at,
    )
    result = localize(
        M,
        observed,
        baseline=(first.first.baseline_start, first.first.baseline_end),
        incident=(first.start, end),
    )
    assert result.top(2)[0].segment == (("payment_method", "visa"), ("platform", "android"))
    top_single = {s.segment[0] for s in result.top(1)[:2]}
    assert top_single == {("platform", "android"), ("payment_method", "visa")}


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_clean_worlds_produce_no_anomalies(seed):
    world = load_scenario(SCENARIO).world.model_copy(update={"seed": seed})
    _, _, results = run_monitor(generate(config=world))
    flagged = {tuple(r.filters.items()) for r in results if r.run.anomalies}
    assert flagged == set()
