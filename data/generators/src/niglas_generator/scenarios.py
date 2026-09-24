"""Declarative scenario files.

A scenario is a JSON file that fully determines a dataset: the world, the faults, the
ground truth the faults imply, and the evidence and recommendations a competent
investigation should produce. Keeping scenarios as data rather than code is what lets
the benchmark grow to hundreds of cases without hundreds of bespoke scripts, and what
lets a reviewer read exactly what a case is testing.

``generator_version`` is recorded in every scenario and checked on load: a scenario is
only reproducible against the generator that produced its ground truth.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from niglas_generator.config import GENERATOR_VERSION, WorldConfig
from niglas_generator.dataset import GeneratedDataset, generate
from niglas_generator.faults import DimensionFilter, Fault, FunnelEffect, RootCauseCategory
from niglas_schemas.enums import PaymentMethod, PlanTier, Platform, Region
from niglas_schemas.types import UtcDatetime


class ScenarioVersionError(ValueError):
    """The scenario was authored against a different generator version."""


class TargetSpec(BaseModel):
    """Serialisable form of :class:`~niglas_generator.faults.DimensionFilter`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    platforms: tuple[Platform, ...] = ()
    regions: tuple[Region, ...] = ()
    plan_tiers: tuple[PlanTier, ...] = ()
    payment_methods: tuple[PaymentMethod, ...] = ()
    app_versions: tuple[str, ...] = ()

    def build(self) -> DimensionFilter:
        return DimensionFilter(
            platforms=self.platforms,
            regions=self.regions,
            plan_tiers=self.plan_tiers,
            payment_methods=self.payment_methods,
            app_versions=self.app_versions,
        )


class FaultSpec(BaseModel):
    """Serialisable form of :class:`~niglas_generator.faults.Fault`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fault_id: str = Field(min_length=1, max_length=120)
    starts_at: UtcDatetime
    ends_at: UtcDatetime | None = None
    ramp_minutes: float = Field(default=0.0, ge=0)
    payment_success_drop: float = Field(default=0.0, ge=0, le=1)
    checkout_rate_multiplier: float = Field(default=1.0, gt=0)
    payment_rate_multiplier: float = Field(default=1.0, gt=0)
    failure_code: str | None = None
    targets: TargetSpec = TargetSpec()
    root_cause_category: RootCauseCategory
    root_cause_detail: str = ""
    linked_deployment_version: str | None = None

    @model_validator(mode="after")
    def _effect_is_meaningful(self) -> "FaultSpec":
        if (
            self.payment_success_drop == 0.0
            and self.checkout_rate_multiplier == 1.0
            and self.payment_rate_multiplier == 1.0
        ):
            raise ValueError(f"fault {self.fault_id} declares no effect")
        if self.payment_success_drop > 0 and not self.failure_code:
            raise ValueError(
                f"fault {self.fault_id} drops payment success but names no failure_code"
            )
        return self

    def build(self) -> Fault:
        return Fault(
            fault_id=self.fault_id,
            starts_at=self.starts_at,
            ends_at=self.ends_at,
            effect=FunnelEffect(
                checkout_rate_multiplier=self.checkout_rate_multiplier,
                payment_rate_multiplier=self.payment_rate_multiplier,
                payment_success_delta=-self.payment_success_drop,
                failure_code=self.failure_code,
            ),
            targets=self.targets.build(),
            ramp_minutes=self.ramp_minutes,
            root_cause_category=self.root_cause_category,
            root_cause_detail=self.root_cause_detail,
            linked_deployment_version=self.linked_deployment_version,
        )


class ScenarioSpec(BaseModel):
    """A complete, reproducible benchmark case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    generator_version: str
    world: WorldConfig
    faults: tuple[FaultSpec, ...] = ()
    expected_evidence: tuple[str, ...] = ()
    acceptable_recommendations: tuple[str, ...] = ()
    unacceptable_recommendations: tuple[str, ...] = ()
    difficulty_tags: tuple[str, ...] = ()

    def generate(self) -> GeneratedDataset:
        """Produce this scenario's dataset and ground truth."""
        return generate(
            config=self.world,
            faults=tuple(spec.build() for spec in self.faults),
            scenario_id=self.scenario_id,
            expected_evidence=self.expected_evidence,
            acceptable_recommendations=self.acceptable_recommendations,
            unacceptable_recommendations=self.unacceptable_recommendations,
            difficulty_tags=self.difficulty_tags,
        )


def load_scenario(path: Path, *, require_current_version: bool = True) -> ScenarioSpec:
    """Load and validate a scenario file.

    Args:
        path: Path to the scenario JSON.
        require_current_version: Reject scenarios authored against another generator
            version. Set ``False`` only to inspect an archived scenario; its ground
            truth is not reproducible on this generator.

    Raises:
        ScenarioVersionError: On a generator version mismatch.
    """
    spec = ScenarioSpec.model_validate_json(path.read_text(encoding="utf-8"))
    if require_current_version and spec.generator_version != GENERATOR_VERSION:
        raise ScenarioVersionError(
            f"scenario {spec.scenario_id} was authored against generator "
            f"{spec.generator_version}, this is {GENERATOR_VERSION}; its ground truth "
            "is not reproducible here"
        )
    return spec


def load_scenarios(directory: Path, *, require_current_version: bool = True) -> list[ScenarioSpec]:
    """Load every ``*.json`` scenario in ``directory``, sorted by id."""
    specs = [
        load_scenario(path, require_current_version=require_current_version)
        for path in sorted(directory.glob("*.json"))
    ]
    duplicates = {
        spec.scenario_id
        for spec in specs
        if sum(1 for other in specs if other.scenario_id == spec.scenario_id) > 1
    }
    if duplicates:
        raise ValueError(f"duplicate scenario ids in {directory}: {sorted(duplicates)}")
    return specs


def dump_scenario(spec: ScenarioSpec, path: Path) -> None:
    """Write a scenario to disk in the canonical, diff-friendly form."""
    path.write_text(
        json.dumps(spec.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
