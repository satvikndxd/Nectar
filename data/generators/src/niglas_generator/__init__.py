"""Deterministic synthetic business simulator.

Niglas has no real customers, so the quality of its detection, investigation and
impact estimation can only be measured against data whose truth is known by
construction. This package generates that data: a business that behaves plausibly,
faults that are injected deliberately, and ground truth computed by differencing a
faulted run against its fault-free counterfactual.

All data produced here is synthetic and is labelled as such wherever it is displayed.
"""

from niglas_generator.config import GENERATOR_VERSION, WorldConfig
from niglas_generator.dataset import GeneratedDataset, generate
from niglas_generator.dimensions import SessionDimensions
from niglas_generator.faults import (
    DimensionFilter,
    Fault,
    FunnelEffect,
    RootCauseCategory,
    payment_failure_spike,
)
from niglas_generator.groundtruth import GroundTruth, WindowMetrics, compute_ground_truth
from niglas_generator.scenarios import ScenarioSpec, load_scenario, load_scenarios
from niglas_generator.simulator import simulate

__all__ = [
    "GENERATOR_VERSION",
    "DimensionFilter",
    "Fault",
    "FunnelEffect",
    "GeneratedDataset",
    "GroundTruth",
    "RootCauseCategory",
    "ScenarioSpec",
    "SessionDimensions",
    "WindowMetrics",
    "WorldConfig",
    "compute_ground_truth",
    "generate",
    "load_scenario",
    "load_scenarios",
    "payment_failure_spike",
    "simulate",
]
