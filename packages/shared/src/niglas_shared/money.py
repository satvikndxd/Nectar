"""Money arithmetic in integer minor units.

Every monetary value in Niglas is an integer count of the currency's minor unit
(cents for USD, yen for JPY) plus an explicit currency. Floating point is never used:
a 0.1% rounding drift is indistinguishable from a real revenue signal, and the impact
engine's whole job is to be trusted about revenue.

Mixed-currency arithmetic raises rather than converting, because a conversion needs a
rate, a rate needs a timestamp, and silently picking either would be a fabricated
number.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from niglas_schemas.enums import Currency
from niglas_shared.errors import DomainError


@dataclass(frozen=True, slots=True, order=False)
class Money:
    """An exact monetary amount. ``amount_minor`` may be negative (e.g. a delta)."""

    amount_minor: int
    currency: Currency

    def __post_init__(self) -> None:
        if not isinstance(self.amount_minor, int) or isinstance(self.amount_minor, bool):
            raise DomainError("Money.amount_minor must be an int in minor units")

    @classmethod
    def zero(cls, currency: Currency) -> "Money":
        return cls(0, currency)

    @classmethod
    def from_major(cls, amount: Decimal | str | int, currency: Currency) -> "Money":
        """Build from a major-unit amount (``"12.34"`` USD -> 1234 cents).

        Raises:
            DomainError: If ``amount`` has more precision than the currency allows.
        """
        value = Decimal(amount)
        scaled = value.scaleb(currency.minor_unit_exponent)
        if scaled != scaled.to_integral_value():
            raise DomainError(f"{value} has more precision than {currency.value} minor units allow")
        return cls(int(scaled), currency)

    def to_major(self) -> Decimal:
        """Major-unit value, exact. For display and reporting only."""
        return Decimal(self.amount_minor).scaleb(-self.currency.minor_unit_exponent)

    def _check_currency(self, other: "Money") -> None:
        if self.currency is not other.currency:
            raise DomainError(
                f"cannot combine {self.currency.value} and {other.currency.value} "
                "without an explicit exchange rate"
            )

    def __add__(self, other: "Money") -> "Money":
        self._check_currency(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._check_currency(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.amount_minor, self.currency)

    def times(self, factor: int) -> "Money":
        """Exact multiplication by a whole number (e.g. quantity)."""
        if not isinstance(factor, int) or isinstance(factor, bool):
            raise DomainError("Money.times requires an int; use scaled() for fractions")
        return Money(self.amount_minor * factor, self.currency)

    def scaled(self, factor: Decimal | str) -> "Money":
        """Multiply by a fraction, rounding half-to-even to the minor unit.

        Half-to-even is used because impact estimates sum many scaled terms, and
        half-up would bias the total upward.
        """
        result = (Decimal(self.amount_minor) * Decimal(factor)).quantize(
            Decimal(1), rounding=ROUND_HALF_EVEN
        )
        return Money(int(result), self.currency)

    def __lt__(self, other: "Money") -> bool:
        self._check_currency(other)
        return self.amount_minor < other.amount_minor

    def __le__(self, other: "Money") -> bool:
        self._check_currency(other)
        return self.amount_minor <= other.amount_minor

    def __gt__(self, other: "Money") -> bool:
        self._check_currency(other)
        return self.amount_minor > other.amount_minor

    def __ge__(self, other: "Money") -> bool:
        self._check_currency(other)
        return self.amount_minor >= other.amount_minor

    def __str__(self) -> str:
        return f"{self.to_major()} {self.currency.value}"


def sum_money(amounts: list[Money], currency: Currency) -> Money:
    """Sum ``amounts``, requiring every element to be in ``currency``.

    ``currency`` is explicit so that summing an empty list still has a currency.
    """
    total = Money.zero(currency)
    for amount in amounts:
        total = total + amount
    return total
