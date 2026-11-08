from __future__ import annotations

from decimal import Decimal

from app.money import (
    ZERO,
    discounted_max_price,
    increase_by_step,
    money_str,
    quantize,
    to_decimal,
)

QUANTUM = Decimal("0.00001")


def test_to_decimal_parses_strings_and_numbers():
    assert to_decimal("1.25") == Decimal("1.25")
    assert to_decimal(3) == Decimal("3")
    assert to_decimal(None) is None
    assert to_decimal("abc", Decimal("1")) == Decimal("1")


def test_quantize_rounds_down_to_quantum():
    assert quantize(Decimal("0.1234567"), QUANTUM) == Decimal("0.12345")
    assert quantize(Decimal("1.000009"), QUANTUM) == Decimal("1.00000")


def test_discounted_max_price_matches_spec_formula():
    assert discounted_max_price(Decimal("10"), Decimal("5"), QUANTUM) == Decimal("9.50000")
    assert discounted_max_price(Decimal("10"), Decimal("0"), QUANTUM) == Decimal("10.00000")
    assert discounted_max_price(Decimal("1"), Decimal("95"), QUANTUM) == Decimal("0.05000")


def test_discounted_max_price_is_decimal_exact():
    result = discounted_max_price(Decimal("0.3"), Decimal("10"), QUANTUM)
    assert result == Decimal("0.27000")
    assert str(result) != str(0.3 * 0.9)


def test_increase_by_step_quantizes():
    assert increase_by_step(Decimal("1.23456"), Decimal("0.00001"), QUANTUM) == Decimal("1.23457")


def test_money_str_trims_trailing_zeros():
    assert money_str(Decimal("1.50000")) == "1.5"
    assert money_str(Decimal("2.00000")) == "2"
    assert money_str(ZERO) == "0"
