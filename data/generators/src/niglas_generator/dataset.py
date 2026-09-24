"""One-call dataset generation: events plus the ground truth that scores them."""

from collections.abc import Sequence
from dataclasses import dataclass

from niglas_generator.config import GENERATOR_VERSION, WorldConfig
from niglas_generator.events import to_events
from niglas_generator.faults import Fault
from niglas_generator.groundtruth import GroundTruth, compute_ground_truth
from niglas_generator.outcomes import SimulationResult
from niglas_generator.rng import StreamRandom
from niglas_generator.simulator import simulate
from niglas_schemas.events import EventEnvelope


@dataclass(frozen=True, slots=True)
class GeneratedDataset:
    """Events to ingest, plus what really happened.

    ``events`` is what Niglas is allowed to see. ``ground_truth`` is what the
    evaluation harness compares Niglas's answers against, and must never be fed into
    detection, investigation or the agent.
    """

    scenario_id: str
    config: WorldConfig
    events: tuple[EventEnvelope, ...]
    ground_truth: GroundTruth
    result: SimulationResult
    counterfactual: SimulationResult


def generate(
    *,
    config: WorldConfig,
    faults: Sequence[Fault] = (),
    scenario_id: str = "ad-hoc",
    expected_evidence: Sequence[str] = (),
    acceptable_recommendations: Sequence[str] = (),
    unacceptable_recommendations: Sequence[str] = (),
    difficulty_tags: Sequence[str] = (),
) -> GeneratedDataset:
    """Simulate the faulted world and its counterfactual, and emit events.

    The counterfactual run is skipped when there are no faults: with nothing injected
    the two runs are identical by construction, and re-running would only cost time.
    """
    result = simulate(config, faults)
    counterfactual = simulate(config, ()) if faults else result
    ground_truth = compute_ground_truth(
        scenario_id=scenario_id,
        config=config,
        faults=faults,
        actual=result,
        counterfactual=counterfactual,
        expected_evidence=expected_evidence,
        acceptable_recommendations=acceptable_recommendations,
        unacceptable_recommendations=unacceptable_recommendations,
        difficulty_tags=difficulty_tags,
    )
    events = to_events(
        result,
        organization_id=config.organization_id,
        currency=config.orders.currency,
        streams=StreamRandom(config.seed, GENERATOR_VERSION),
    )
    return GeneratedDataset(
        scenario_id=scenario_id,
        config=config,
        events=tuple(events),
        ground_truth=ground_truth,
        result=result,
        counterfactual=counterfactual,
    )
