from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.enums import PositionStatus
from app.money import ZERO, discounted_max_price, increase_by_step, quantize


@dataclass(frozen=True, slots=True)
class PricingLimits:
    floor_price: Decimal
    discount_percent: Decimal
    min_step: Decimal
    min_offer_amount: Decimal
    quantum: Decimal
    max_price_per_offer: Decimal | None = None
    max_price_percent: Decimal | None = None


@dataclass(frozen=True, slots=True)
class PricingOutcome:
    target_price: Decimal | None
    cap: Decimal
    status: str
    reason: str

    @property
    def executable(self) -> bool:
        return self.target_price is not None


def effective_cap(limits: PricingLimits) -> Decimal:
    discount = limits.discount_percent
    if limits.max_price_percent is not None:
        discount = Decimal("100") - limits.max_price_percent
    cap = discounted_max_price(limits.floor_price, discount, limits.quantum)
    if limits.max_price_per_offer is not None and limits.max_price_per_offer < cap:
        cap = quantize(limits.max_price_per_offer, limits.quantum)
    return cap


def competitor_target(cap: Decimal, competitor_amount: Decimal, min_step: Decimal, quantum: Decimal) -> Decimal | None:
    if competitor_amount >= cap:
        return None
    candidate = increase_by_step(competitor_amount, min_step, quantum)
    return candidate if candidate <= cap else cap


def compute_target(
    limits: PricingLimits,
    *,
    fixed_price: Decimal | None,
    hold_first_place: bool,
    competitor_amount: Decimal | None,
    competitor_unknown: bool,
) -> PricingOutcome:
    cap = effective_cap(limits)
    if cap < ZERO:
        cap = ZERO

    if cap < limits.min_offer_amount:
        return PricingOutcome(None, cap, PositionStatus.LIMIT_REACHED.value, "MIN_PRICE_BELOW_API_MINIMUM")

    if fixed_price is not None:
        price = quantize(fixed_price, limits.quantum)
        if price < limits.min_offer_amount:
            return PricingOutcome(None, cap, PositionStatus.LIMIT_REACHED.value, "FIXED_PRICE_BELOW_API_MINIMUM")
        if price > cap:
            return PricingOutcome(None, cap, PositionStatus.LIMIT_REACHED.value, "FIXED_PRICE_ABOVE_CAP")
        return PricingOutcome(price, cap, PositionStatus.UNKNOWN.value, "FIXED_PRICE")

    if not hold_first_place:
        return PricingOutcome(cap, cap, PositionStatus.UNKNOWN.value, "FLOOR_RELATIVE")

    if competitor_unknown:
        return PricingOutcome(cap, cap, PositionStatus.DATA_INCOMPLETE.value, "COMPETITOR_WINDOW_INCOMPLETE")

    if competitor_amount is None:
        return PricingOutcome(cap, cap, PositionStatus.FIRST_CONFIRMED.value, "NO_COMPETITORS")

    target = competitor_target(cap, competitor_amount, limits.min_step, limits.quantum)
    if target is None:
        return PricingOutcome(None, cap, PositionStatus.LIMIT_REACHED.value, "COMPETITOR_ABOVE_CAP")
    if target < limits.min_offer_amount:
        return PricingOutcome(None, cap, PositionStatus.LIMIT_REACHED.value, "MIN_PRICE_BELOW_API_MINIMUM")
    return PricingOutcome(target, cap, PositionStatus.OUTBID.value, "OUTBID_COMPETITOR")


def is_price_step_reached(current: Decimal, target: Decimal, quantum: Decimal) -> bool:
    return quantize(current, quantum) == quantize(target, quantum)
