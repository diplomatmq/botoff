from __future__ import annotations

from decimal import Decimal

from app.enums import PositionStatus
from app.services.pricing import (
    PricingLimits,
    competitor_target,
    compute_target,
    effective_cap,
    is_price_step_reached,
)

QUANTUM = Decimal("0.00001")
MIN_OFFER = Decimal("0.5")


def limits(
    floor: str,
    discount: str = "0",
    max_price: str | None = None,
    step: str = "0.00001",
    max_price_percent: str | None = None,
) -> PricingLimits:
    return PricingLimits(
        floor_price=Decimal(floor),
        discount_percent=Decimal(discount),
        min_step=Decimal(step),
        min_offer_amount=MIN_OFFER,
        quantum=QUANTUM,
        max_price_per_offer=Decimal(max_price) if max_price else None,
        max_price_percent=Decimal(max_price_percent) if max_price_percent else None,
    )


def test_effective_cap_applies_discount():
    assert effective_cap(limits("10", "5")) == Decimal("9.50000")


def test_effective_cap_is_clamped_by_max_price_per_offer():
    assert effective_cap(limits("10", "0", max_price="7.5")) == Decimal("7.50000")


def test_cap_below_api_minimum_is_not_executable():
    outcome = compute_target(
        limits("0.4"),
        fixed_price=None,
        hold_first_place=True,
        competitor_amount=None,
        competitor_unknown=False,
    )
    assert outcome.executable is False
    assert outcome.status == PositionStatus.LIMIT_REACHED.value


def test_fixed_price_above_cap_is_limit_reached():
    outcome = compute_target(
        limits("10", "10"),
        fixed_price=Decimal("20"),
        hold_first_place=False,
        competitor_amount=None,
        competitor_unknown=False,
    )
    assert outcome.executable is False
    assert outcome.reason == "FIXED_PRICE_ABOVE_CAP"


def test_hold_first_place_raises_above_competitor_by_min_step():
    outcome = compute_target(
        limits("10", step="0.001"),
        fixed_price=None,
        hold_first_place=True,
        competitor_amount=Decimal("9"),
        competitor_unknown=False,
    )
    assert outcome.executable is True
    assert outcome.target_price == Decimal("9.00100")
    assert outcome.status == PositionStatus.OUTBID.value


def test_hold_first_place_uses_percentage_cap_without_rebid_limit():
    limits_95 = limits("100", max_price_percent="95", step="1")

    below_cap = compute_target(
        limits_95,
        fixed_price=None,
        hold_first_place=True,
        competitor_amount=Decimal("30"),
        competitor_unknown=False,
    )
    assert below_cap.target_price == Decimal("31.00000")
    assert below_cap.status == PositionStatus.OUTBID.value

    at_cap = compute_target(
        limits_95,
        fixed_price=None,
        hold_first_place=True,
        competitor_amount=Decimal("94"),
        competitor_unknown=False,
    )
    assert at_cap.target_price == Decimal("95.00000")
    assert at_cap.status == PositionStatus.OUTBID.value

    above_cap = compute_target(
        limits_95,
        fixed_price=None,
        hold_first_place=True,
        competitor_amount=Decimal("95"),
        competitor_unknown=False,
    )
    assert above_cap.executable is False
    assert above_cap.reason == "COMPETITOR_ABOVE_CAP"


def test_hold_first_place_without_competitor_uses_floor_percentage_cap():
    outcome = compute_target(
        limits("3.91837", max_price_percent="98"),
        fixed_price=None,
        hold_first_place=True,
        competitor_amount=None,
        competitor_unknown=False,
    )
    assert outcome.target_price == Decimal("3.84000")


def test_competitor_above_cap_is_limit_reached():
    outcome = compute_target(
        limits("10", "5"),
        fixed_price=None,
        hold_first_place=True,
        competitor_amount=Decimal("9.8"),
        competitor_unknown=False,
    )
    assert outcome.executable is False
    assert outcome.reason == "COMPETITOR_ABOVE_CAP"


def test_competitor_target_never_exceeds_cap():
    cap = Decimal("9.5")
    assert competitor_target(cap, Decimal("9.49999"), Decimal("0.01"), QUANTUM) == cap


def test_unknown_competitor_marks_data_incomplete():
    outcome = compute_target(
        limits("10"),
        fixed_price=None,
        hold_first_place=True,
        competitor_amount=None,
        competitor_unknown=True,
    )
    assert outcome.status == PositionStatus.DATA_INCOMPLETE.value
    assert outcome.executable is True


def test_floor_relative_uses_full_cap():
    outcome = compute_target(
        limits("10", "20"),
        fixed_price=None,
        hold_first_place=False,
        competitor_amount=Decimal("1"),
        competitor_unknown=False,
    )
    assert outcome.target_price == Decimal("8.00000")


def test_is_price_step_reached_compares_quantized_values():
    assert is_price_step_reached(Decimal("1.000004"), Decimal("1.0000045"), QUANTUM) is True
    assert is_price_step_reached(Decimal("1.00000"), Decimal("1.00002"), QUANTUM) is False
