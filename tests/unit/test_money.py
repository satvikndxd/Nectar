"""Money must be exact: a rounding drift is indistinguishable from a revenue signal."""

from decimal import Decimal

import pytest

from niglas_schemas.enums import Currency
from niglas_shared.errors import DomainError
from niglas_shared.money import Money, sum_money


def test_from_major_converts_to_minor_units():
    assert Money.from_major("12.34", Currency.USD) == Money(1234, Currency.USD)
    assert Money.from_major("12", Currency.JPY) == Money(12, Currency.JPY)


def test_from_major_rejects_excess_precision():
    with pytest.raises(DomainError, match="more precision"):
        Money.from_major("12.345", Currency.USD)
    with pytest.raises(DomainError, match="more precision"):
        Money.from_major("12.5", Currency.JPY)


def test_to_major_round_trips():
    assert Money(1234, Currency.USD).to_major() == Decimal("12.34")
    assert Money(-500, Currency.EUR).to_major() == Decimal("-5.00")


def test_addition_and_subtraction():
    assert Money(1000, Currency.USD) + Money(250, Currency.USD) == Money(1250, Currency.USD)
    assert Money(1000, Currency.USD) - Money(250, Currency.USD) == Money(750, Currency.USD)
    assert -Money(1000, Currency.USD) == Money(-1000, Currency.USD)


def test_mixed_currency_arithmetic_raises_rather_than_converting():
    with pytest.raises(DomainError, match="exchange rate"):
        Money(1000, Currency.USD) + Money(1000, Currency.EUR)
    with pytest.raises(DomainError, match="exchange rate"):
        _ = Money(1000, Currency.USD) < Money(1000, Currency.EUR)


def test_times_requires_an_integer():
    assert Money(2900, Currency.USD).times(3) == Money(8700, Currency.USD)
    with pytest.raises(DomainError, match="requires an int"):
        Money(2900, Currency.USD).times(1.5)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("amount", "factor", "expected"),
    [
        (1000, "0.155", 155),
        (101, "0.5", 50),  # 50.5 -> 50 (half to even)
        (103, "0.5", 52),  # 51.5 -> 52 (half to even)
        (1000, "1.0", 1000),
    ],
)
def test_scaled_rounds_half_to_even(amount, factor, expected):
    assert Money(amount, Currency.USD).scaled(factor) == Money(expected, Currency.USD)


def test_float_amounts_are_rejected():
    with pytest.raises(DomainError, match="minor units"):
        Money(12.34, Currency.USD)  # type: ignore[arg-type]


def test_sum_money_of_empty_list_keeps_a_currency():
    assert sum_money([], Currency.GBP) == Money(0, Currency.GBP)


def test_sum_money_rejects_a_foreign_element():
    with pytest.raises(DomainError):
        sum_money([Money(1, Currency.USD), Money(1, Currency.EUR)], Currency.USD)
