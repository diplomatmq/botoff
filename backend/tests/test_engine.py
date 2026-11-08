from __future__ import annotations

from decimal import Decimal

import pytest

from app.enums import PositionStatus, RuleState, Strategy
from app.services.engine import (
    CREATE,
    NOOP,
    PAUSE,
    UPDATE,
    AccountView,
    MarketView,
    RuleSnapshot,
    decide,
    resolve_position,
)

QUANTUM = Decimal("0.00001")


def rule(**overrides) -> RuleSnapshot:
    base = dict(
        id="rule-1",
        state=RuleState.ACTIVE.value,
        strategy=Strategy.HOLD_FIRST_PLACE.value,
        hold_first_place=True,
        pause_on_uncertainty=True,
        discount_percent=Decimal("0"),
        fixed_price=None,
        min_step=Decimal("0.00001"),
        max_price_per_offer=None,
        max_budget=None,
        max_active_offers=1,
        max_nfts=1,
        on_limit_behavior="keep",
        quantum=QUANTUM,
        min_offer_amount=Decimal("0.5"),
        uses_attributes=False,
        scope_guard=True,
    )
    base.update(overrides)
    return RuleSnapshot(**base)


def account(**overrides) -> AccountView:
    base = dict(
        available=Decimal("100"),
        reserved=Decimal("0"),
        rule_committed=Decimal("0"),
        active_offers_for_rule=0,
        mode_live=True,
        automation_enabled=True,
        emergency_stop=False,
        attribute_offers_unavailable=False,
    )
    base.update(overrides)
    return AccountView(**base)


def market(**overrides) -> MarketView:
    base = dict(
        floor_price=Decimal("10"),
        own_amount=None,
        own_rank=None,
        competitor_amount=None,
        competitor_unknown=False,
        total_offers=0,
        data_stale=False,
    )
    base.update(overrides)
    return MarketView(**base)


def test_emergency_stop_blocks_everything():
    decision = decide(rule(), market(), account(emergency_stop=True))
    assert decision.action == NOOP
    assert decision.reason == "EMERGENCY_STOP"


def test_automation_disabled_blocks_everything():
    decision = decide(rule(), market(), account(automation_enabled=False))
    assert decision.reason == "AUTOMATION_DISABLED"


def test_inactive_rule_does_not_trade():
    decision = decide(rule(state=RuleState.PAUSED.value), market(), account())
    assert decision.reason == "RULE_INACTIVE"


def test_attribute_offers_unavailable_pauses_attribute_rule():
    decision = decide(
        rule(uses_attributes=True),
        market(),
        account(attribute_offers_unavailable=True),
    )
    assert decision.action == PAUSE
    assert decision.position_status == PositionStatus.ATTRIBUTE_OFFERS_UNAVAILABLE.value


def test_create_when_no_own_offer():
    decision = decide(rule(), market(), account())
    assert decision.action == CREATE
    assert decision.target_price == Decimal("10.00000")


def test_noop_when_price_already_optimal():
    decision = decide(rule(), market(own_amount=Decimal("10.00000"), own_rank=0), account())
    assert decision.action == NOOP
    assert decision.reason == "PRICE_ALREADY_OPTIMAL"


def test_raise_to_outbid_competitor():
    decision = decide(
        rule(min_step=Decimal("0.001")),
        market(own_amount=Decimal("8"), own_rank=1, competitor_amount=Decimal("9")),
        account(),
    )
    assert decision.action == UPDATE
    assert decision.target_price == Decimal("9.00100")


def test_insufficient_funds_is_reported_without_action():
    decision = decide(
        rule(),
        market(),
        account(available=Decimal("0.4")),
    )
    assert decision.action == NOOP
    assert decision.position_status == PositionStatus.INSUFFICIENT_FUNDS.value


def test_rule_budget_limit_is_respected():
    decision = decide(
        rule(max_budget=Decimal("5")),
        market(),
        account(),
    )
    assert decision.position_status == PositionStatus.LIMIT_REACHED.value
    assert decision.reason == "RULE_BUDGET_EXCEEDED"


def test_on_limit_behavior_cancel_triggers_cancel():
    decision = decide(
        rule(max_budget=Decimal("5"), on_limit_behavior="cancel"),
        market(),
        account(),
    )
    assert decision.action == "cancel"


def test_resolve_position_confirms_first_place_only_with_data():
    assert resolve_position(market(own_amount=Decimal("10"), own_rank=0)) == PositionStatus.FIRST_CONFIRMED.value
    assert (
        resolve_position(
            market(own_amount=Decimal("10"), own_rank=1, competitor_amount=Decimal("11"))
        )
        == PositionStatus.OUTBID.value
    )
    assert (
        resolve_position(market(own_amount=Decimal("10"), own_rank=1, competitor_unknown=True))
        == PositionStatus.DATA_INCOMPLETE.value
    )


@pytest.mark.parametrize("stale", [True, False])
def test_stale_market_data_pauses(stale: bool):
    decision = decide(rule(), market(data_stale=stale), account())
    if stale:
        assert decision.action == PAUSE
        assert decision.position_status == PositionStatus.STALE_DATA.value
    else:
        assert decision.action == CREATE
