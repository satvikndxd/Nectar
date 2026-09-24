"""Ground truth derived by differencing a faulted run against its counterfactual.

Niglas's own impact engine will later *estimate* revenue loss from observed metrics.
To score that estimate we need the true answer, and the only way to know it is to run
the same world twice - once with the fault, once without - and compare session by
session. Because the generator's randomness is stream-keyed, the two runs contain the
same sessions with the same dimensions and the same order values, so the difference is
attributable to the fault alone rather than to sampling noise.

Nothing here is an estimate. ``lost_orders`` is a count of sessions that converted in
the counterfactual and did not convert with the fault present.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from niglas_generator.config import GENERATOR_VERSION, WorldConfig
from niglas_generator.faults import Fault, RootCauseCategory
from niglas_generator.outcomes import SessionOutcome, SimulationResult
from niglas_schemas.enums import Currency


@dataclass(frozen=True, slots=True)
class WindowMetrics:
    """Observable funnel metrics for one run inside the incident window."""

    sessions: int
    checkouts: int
    payment_sessions: int
    payment_attempts: int
    payment_failures: int
    conversions: int
    revenue_minor: int

    @property
    def conversion_rate(self) -> float:
        return self.conversions / self.sessions if self.sessions else 0.0

    @property
    def payment_failure_rate(self) -> float:
        return self.payment_failures / self.payment_attempts if self.payment_attempts else 0.0


@dataclass(frozen=True, slots=True)
class GroundTruth:
    """The declared and measured truth about a generated dataset."""

    scenario_id: str
    seed: int
    generator_version: str
    has_incident: bool
    incident_start: datetime | None
    incident_end: datetime | None
    root_cause_category: RootCauseCategory
    root_cause_detail: str
    linked_deployment_version: str | None
    affected_dimensions: dict[str, list[str]]
    currency: Currency
    lost_orders: int
    """Sessions that converted without the fault and did not convert with it."""
    gained_orders: int
    """Sessions that converted only with the fault present (random churn, not a benefit)."""
    true_revenue_loss_minor: int
    """Counterfactual revenue minus actual revenue, over the whole run."""
    affected_customers: int
    """Distinct customers who lost a conversion or saw a fault-attributed failure."""
    actual_window: WindowMetrics | None
    counterfactual_window: WindowMetrics | None
    expected_evidence: tuple[str, ...] = ()
    """Findings a competent investigation should surface; scored in Phase 4 evals."""
    acceptable_recommendations: tuple[str, ...] = ()
    unacceptable_recommendations: tuple[str, ...] = ()
    difficulty_tags: tuple[str, ...] = field(default_factory=tuple)


class CounterfactualMismatchError(RuntimeError):
    """Raised when the two runs are not comparable session-for-session.

    This means the determinism contract in :mod:`niglas_generator.simulator` has been
    broken - typically by adding a draw that only happens on one branch - and any
    ground truth computed from the pair would be silently wrong.
    """


def compute_ground_truth(
    *,
    scenario_id: str,
    config: WorldConfig,
    faults: Sequence[Fault],
    actual: SimulationResult,
    counterfactual: SimulationResult,
    expected_evidence: Sequence[str] = (),
    acceptable_recommendations: Sequence[str] = (),
    unacceptable_recommendations: Sequence[str] = (),
    difficulty_tags: Sequence[str] = (),
) -> GroundTruth:
    """Difference two runs of the same world into a :class:`GroundTruth`.

    Raises:
        CounterfactualMismatchError: If the runs do not contain the same sessions.
    """
    actual_by_id = {session.session_id: session for session in actual.sessions}
    counterfactual_by_id = {session.session_id: session for session in counterfactual.sessions}
    if actual_by_id.keys() != counterfactual_by_id.keys():
        raise CounterfactualMismatchError(
            f"faulted run has {len(actual_by_id)} sessions, counterfactual has "
            f"{len(counterfactual_by_id)}; the runs are not comparable"
        )

    lost_orders = 0
    gained_orders = 0
    revenue_delta_minor = 0
    affected_customers: set[object] = set()
    for session_id, actual_session in actual_by_id.items():
        baseline_session = counterfactual_by_id[session_id]
        revenue_delta_minor += baseline_session.revenue_minor - actual_session.revenue_minor
        if baseline_session.converted and not actual_session.converted:
            lost_orders += 1
            affected_customers.add(actual_session.customer_id)
        elif actual_session.converted and not baseline_session.converted:
            gained_orders += 1

    window = _incident_window(config, faults)
    return GroundTruth(
        scenario_id=scenario_id,
        seed=config.seed,
        generator_version=GENERATOR_VERSION,
        has_incident=bool(faults),
        incident_start=window[0] if window else None,
        incident_end=window[1] if window else None,
        root_cause_category=(
            faults[0].root_cause_category if faults else RootCauseCategory.NO_INCIDENT
        ),
        root_cause_detail=faults[0].root_cause_detail if faults else "",
        linked_deployment_version=faults[0].linked_deployment_version if faults else None,
        affected_dimensions=_merged_targets(faults),
        currency=config.orders.currency,
        lost_orders=lost_orders,
        gained_orders=gained_orders,
        true_revenue_loss_minor=revenue_delta_minor,
        affected_customers=len(affected_customers),
        actual_window=window_metrics(actual.sessions, window) if window else None,
        counterfactual_window=(window_metrics(counterfactual.sessions, window) if window else None),
        expected_evidence=tuple(expected_evidence),
        acceptable_recommendations=tuple(acceptable_recommendations),
        unacceptable_recommendations=tuple(unacceptable_recommendations),
        difficulty_tags=tuple(difficulty_tags),
    )


def window_metrics(
    sessions: Sequence[SessionOutcome], window: tuple[datetime, datetime]
) -> WindowMetrics:
    """Aggregate observable funnel metrics over ``window`` (half-open)."""
    start, end = window
    selected = [session for session in sessions if start <= session.started_at < end]
    attempts = [attempt for session in selected for attempt in session.attempts]
    return WindowMetrics(
        sessions=len(selected),
        checkouts=sum(1 for session in selected if session.reached_checkout),
        payment_sessions=sum(1 for session in selected if session.reached_payment),
        payment_attempts=len(attempts),
        payment_failures=sum(1 for attempt in attempts if not attempt.succeeded),
        conversions=sum(1 for session in selected if session.converted),
        revenue_minor=sum(session.revenue_minor for session in selected),
    )


def _incident_window(
    config: WorldConfig, faults: Sequence[Fault]
) -> tuple[datetime, datetime] | None:
    if not faults:
        return None
    run_end = config.start + timedelta(hours=config.duration_hours)
    start = min(fault.starts_at for fault in faults)
    end = max((fault.ends_at or run_end) for fault in faults)
    return start, min(end, run_end)


def _merged_targets(faults: Sequence[Fault]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for fault in faults:
        for axis, values in fault.targets.as_dict().items():
            existing = merged.setdefault(axis, [])
            for value in values:
                if value not in existing:
                    existing.append(value)
    return merged


__all__ = [
    "CounterfactualMismatchError",
    "GroundTruth",
    "WindowMetrics",
    "compute_ground_truth",
    "window_metrics",
]
