"""The simulator's internal record of what happened to each session.

These objects are the unit of comparison between a faulted run and its counterfactual,
so they carry every outcome a ground-truth calculation needs. They are converted to
:mod:`niglas_schemas` event envelopes only at the boundary.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from niglas_generator.dimensions import SessionDimensions


@dataclass(frozen=True, slots=True)
class PaymentAttempt:
    payment_id: UUID
    attempt_number: int
    attempted_at: datetime
    succeeded: bool
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class OrderLineOutcome:
    sku: str
    quantity: int
    unit_amount_minor: int

    @property
    def amount_minor(self) -> int:
        return self.quantity * self.unit_amount_minor


@dataclass(frozen=True, slots=True)
class SessionOutcome:
    """One simulated session, start to finish.

    The ``basket`` is drawn for every session, converted or not: a failed payment
    attempt still has a real amount behind it, and that amount is exactly what the
    revenue-at-risk calculation needs. ``order_id`` is set only when a payment
    succeeded, so ``converted`` and ``revenue_minor`` stay unambiguous.
    """

    session_id: UUID
    customer_id: UUID
    started_at: datetime
    duration_ms: int
    dimensions: SessionDimensions
    reached_checkout: bool
    reached_payment: bool
    attempts: tuple[PaymentAttempt, ...]
    basket: tuple[OrderLineOutcome, ...]
    order_id: UUID | None

    @property
    def converted(self) -> bool:
        return self.order_id is not None

    @property
    def basket_amount_minor(self) -> int:
        return sum(line.amount_minor for line in self.basket)

    @property
    def revenue_minor(self) -> int:
        """Realised revenue: the basket amount if the session converted, else zero."""
        return self.basket_amount_minor if self.converted else 0


@dataclass(frozen=True, slots=True)
class DeploymentOutcome:
    deployment_id: UUID
    service: str
    version: str
    deployed_at: datetime
    status: str
    commit_sha: str
    description: str


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Everything one run produced, before conversion to events."""

    sessions: tuple[SessionOutcome, ...]
    deployments: tuple[DeploymentOutcome, ...]
