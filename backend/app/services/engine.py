from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.enums import PositionStatus, RuleState, Strategy
from app.money import ZERO, quantize
from app.services.pricing import PricingLimits, compute_target


@dataclass(frozen=True, slots=True)
class RuleSnapshot:
    id: str
    state: str
    strategy: str
    hold_first_place: bool
    pause_on_uncertainty: bool
    discount_percent: Decimal
    fixed_price: Decimal | None
    min_step: Decimal
    max_price_per_offer: Decimal | None
    max_budget: Decimal | None
    max_active_offers: int
    max_nfts: int
    on_limit_behavior: str
    quantum: Decimal
    min_offer_amount: Decimal
    uses_attributes: bool = False
    scope_guard: bool = True
    max_price_percent: Decimal | None = None


@dataclass(frozen=True, slots=True)
class MarketView:
    floor_price: Decimal | None
    own_amount: Decimal | None
    own_rank: int | None
    competitor_amount: Decimal | None
    competitor_unknown: bool
    total_offers: int
    data_stale: bool = False


@dataclass(frozen=True, slots=True)
class AccountView:
    available: Decimal | None
    reserved: Decimal = ZERO
    rule_committed: Decimal = ZERO
    active_offers_for_rule: int = 0
    mode_live: bool = False
    automation_enabled: bool = False
    emergency_stop: bool = False
    attribute_offers_unavailable: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    action: str
    position_status: str
    reason: str
    target_price: Decimal | None = None
    cap: Decimal | None = None
    details: dict[str, Any] = field(default_factory=dict)


NOOP = "noop"
CREATE = "create"
UPDATE = "update"
CANCEL = "cancel"
PAUSE = "pause"


def _limit_decision(rule: RuleSnapshot, status: str, reason: str, cap: Decimal | None) -> Decision:
    behavior = rule.on_limit_behavior
    if behavior == "cancel":
        return Decision(CANCEL, status, reason, cap=cap)
    if behavior == "pause":
        return Decision(PAUSE, status, reason, cap=cap)
    return Decision(NOOP, status, reason, cap=cap)


def resolve_position(market: MarketView) -> str:
    if market.own_amount is None:
        return PositionStatus.UNKNOWN.value
    if market.own_rank == 0:
        return PositionStatus.FIRST_CONFIRMED.value
    if market.competitor_unknown:
        return PositionStatus.DATA_INCOMPLETE.value
    if market.competitor_amount is not None and market.competitor_amount >= market.own_amount:
        return PositionStatus.OUTBID.value
    if market.competitor_amount is not None:
        return PositionStatus.FIRST_CONFIRMED.value
    if market.total_offers > 1:
        return PositionStatus.DATA_INCOMPLETE.value
    return PositionStatus.FIRST_CONFIRMED.value


def decide(rule: RuleSnapshot, market: MarketView, account: AccountView) -> Decision:
    if account.emergency_stop:
        return Decision(NOOP, PositionStatus.UNKNOWN.value, "EMERGENCY_STOP")

    if not account.automation_enabled:
        return Decision(NOOP, PositionStatus.UNKNOWN.value, "AUTOMATION_DISABLED")

    if rule.state in (RuleState.DISABLED.value, RuleState.PAUSED.value, RuleState.ERROR.value):
        return Decision(NOOP, PositionStatus.UNKNOWN.value, "RULE_INACTIVE")

    if rule.uses_attributes and account.attribute_offers_unavailable:
        return Decision(
            PAUSE if rule.pause_on_uncertainty else NOOP,
            PositionStatus.ATTRIBUTE_OFFERS_UNAVAILABLE.value,
            "ATTRIBUTE_OFFERS_UNAVAILABLE",
        )

    if market.data_stale:
        return Decision(
            PAUSE if rule.pause_on_uncertainty else NOOP,
            PositionStatus.STALE_DATA.value,
            "STALE_MARKET_DATA",
        )

    position = resolve_position(market)

    if market.floor_price is None:
        return Decision(
            NOOP,
            PositionStatus.DATA_INCOMPLETE.value,
            "FLOOR_PRICE_UNAVAILABLE",
        )

    limits = PricingLimits(
        floor_price=market.floor_price,
        discount_percent=rule.discount_percent,
        min_step=rule.min_step,
        min_offer_amount=rule.min_offer_amount,
        quantum=rule.quantum,
        max_price_per_offer=rule.max_price_per_offer,
        max_price_percent=rule.max_price_percent,
    )
    fixed_price = rule.fixed_price if rule.strategy == Strategy.FIXED.value else None
    outcome = compute_target(
        limits,
        fixed_price=fixed_price,
        hold_first_place=(
            rule.hold_first_place
            or rule.strategy == Strategy.HOLD_FIRST_PLACE.value
        ),
        competitor_amount=market.competitor_amount,
        competitor_unknown=market.competitor_unknown,
    )

    if not outcome.executable:
        return _limit_decision(rule, outcome.status, outcome.reason, outcome.cap)

    target = outcome.target_price
    assert target is not None

    max_nfts = max(1, rule.max_nfts)
    required_total = target * max_nfts
    own_committed = (market.own_amount or ZERO) * max_nfts
    incremental = required_total - own_committed
    if incremental < ZERO:
        incremental = ZERO

    if rule.max_budget is not None:
        projected = account.rule_committed - own_committed + required_total
        if projected > rule.max_budget:
            return _limit_decision(rule, PositionStatus.LIMIT_REACHED.value, "RULE_BUDGET_EXCEEDED", outcome.cap)

    if account.available is None:
        return Decision(NOOP, PositionStatus.UNKNOWN.value, "BALANCE_UNKNOWN", cap=outcome.cap)

    spendable = account.available - account.reserved
    if incremental > spendable:
        return Decision(
            NOOP,
            PositionStatus.INSUFFICIENT_FUNDS.value,
            "INSUFFICIENT_FUNDS",
            target_price=target,
            cap=outcome.cap,
            details={
                "required": str(incremental),
                "spendable": str(spendable),
                "available": str(account.available),
                "reserved": str(account.reserved),
                "own_committed": str(own_committed),
                "max_nfts": max_nfts,
            },
        )

    if market.own_amount is None:
        if account.active_offers_for_rule >= max(1, rule.max_active_offers):
            return _limit_decision(
                rule, PositionStatus.LIMIT_REACHED.value, "MAX_ACTIVE_OFFERS", outcome.cap
            )
        return Decision(
            CREATE,
            outcome.status if outcome.status != PositionStatus.UNKNOWN.value else position,
            outcome.reason,
            target_price=target,
            cap=outcome.cap,
        )

    if quantize(market.own_amount, rule.quantum) == quantize(target, rule.quantum):
        status = position if outcome.status == PositionStatus.UNKNOWN.value else outcome.status
        return Decision(NOOP, status, "PRICE_ALREADY_OPTIMAL", target_price=target, cap=outcome.cap)

    if market.own_amount > target:
        return Decision(
            UPDATE,
            position,
            "PRICE_OPTIMIZED",
            target_price=target,
            cap=outcome.cap,
        )

    status = position if outcome.status == PositionStatus.UNKNOWN.value else outcome.status
    return Decision(UPDATE, status, "RAISE_TO_OUTBID", target_price=target, cap=outcome.cap)
