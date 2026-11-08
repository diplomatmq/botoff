from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import AuditAction, OfferStatus, OperationState, OperationType, PositionStatus, RuleState, Strategy
from app.models import ApiCredential, AutomationRule, ManagedOffer, OperationQueue
from app.money import ZERO, money_str, to_decimal
from app.notifications import service as notifications
from app.portals.client import PortalsGateway
from app.services import audit, operations_service
from app.services.engine import AccountView, Decision, MarketView, RuleSnapshot, decide
from app.services.offers_service import (
    build_market_snapshot,
    default_next_run,
    rule_active_offers,
    rule_attributes,
    rule_committed_amount,
    rule_scope_kind,
    sync_offer_row,
)
from app.services.pricing import is_price_step_reached

logger = logging.getLogger("portals.rule_cycle")


@dataclass(slots=True)
class CycleResult:
    rule_id: str
    action: str
    status: str
    reason: str
    target_price: Decimal | None
    enqueued: bool
    executed: bool
    detail: dict[str, Any]


def _scope_signature(rule: AutomationRule) -> str:
    payload = "|".join(
        [
            rule.collection_id,
            ",".join(sorted(rule.models or [])),
            ",".join(sorted(rule.backdrops or [])),
            ",".join(sorted(rule.symbols or [])),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def rule_snapshot(rule: AutomationRule) -> RuleSnapshot:
    from app.config import get_settings

    settings = get_settings()
    return RuleSnapshot(
        id=str(rule.id),
        state=rule.state,
        strategy=rule.strategy,
        hold_first_place=rule.hold_first_place,
        pause_on_uncertainty=rule.pause_on_uncertainty,
        discount_percent=Decimal(rule.discount_percent or 0),
        max_price_percent=rule.max_price_percent,
        fixed_price=rule.fixed_price,
        min_step=rule.min_step,
        max_price_per_offer=rule.max_price_per_offer,
        max_budget=rule.max_budget,
        max_active_offers=rule.max_active_offers,
        max_nfts=rule.max_nfts,
        on_limit_behavior=rule.on_limit_behavior,
        quantum=settings.price_quantum,
        min_offer_amount=settings.min_offer_amount,
        uses_attributes=bool(rule.models or rule.backdrops or rule.symbols),
        scope_guard=rule.scope_guard,
    )


async def run_rule_cycle(
    session: AsyncSession,
    *,
    rule: AutomationRule,
    gateway: PortalsGateway,
    credential: ApiCredential,
    mode_live: bool,
    automation_enabled: bool,
    emergency_stop: bool,
    available_balance: Decimal | None,
) -> CycleResult:
    snapshot = await build_market_snapshot(
        session, gateway, rule, credential_sender_id=credential.sender_id
    )

    if snapshot.own_offer is not None:
        await _adopt_remote_offer(session, rule, credential, snapshot.own_offer, snapshot.own_rank)

    own_rows = await rule_active_offers(session, rule.id)
    own_row = _pick_own_row(own_rows, snapshot.own_offer)

    if snapshot.own_offer is not None and own_row is not None:
        await sync_offer_row(session, own_row, snapshot.own_offer, rank=snapshot.own_rank)

    if snapshot.rate_limited:
        rule.last_position_status = PositionStatus.RATE_LIMITED.value
        rule.last_decision = {"status": PositionStatus.RATE_LIMITED.value, "reason": "RATE_LIMITED"}
        rule.next_run_at = default_next_run(rule, offset_seconds=5)
        await audit.record(
            session,
            action="rate_limited",
            message="Лимит запросов Portals: проверка отложена",
            actor="worker",
            user_id=rule.user_id,
            entity_type="rule",
            entity_id=rule.id,
            level="warning",
            details={"rule": rule.name},
        )
        return CycleResult(str(rule.id), "noop", PositionStatus.RATE_LIMITED.value, "RATE_LIMITED", None, False, False, {})

    if snapshot.error:
        rule.last_position_status = PositionStatus.API_ERROR.value
        rule.last_error = snapshot.error[:500]
        rule.last_decision = {"status": PositionStatus.API_ERROR.value, "reason": snapshot.error}
        rule.next_run_at = default_next_run(rule)
        await notifications.notify(
            session,
            user_id=rule.user_id,
            event="api_error",
            title="Ошибка API Portals",
            message=f"Правило «{rule.name}»: {snapshot.error}",
            level="error",
        )
        return CycleResult(str(rule.id), "noop", PositionStatus.API_ERROR.value, snapshot.error, None, False, False, {})

    committed = rule_committed_amount(own_rows)
    account = AccountView(
        available=available_balance,
        reserved=ZERO,
        rule_committed=committed,
        active_offers_for_rule=len([row for row in own_rows if row.status == OfferStatus.PENDING.value]),
        mode_live=mode_live,
        automation_enabled=automation_enabled,
        emergency_stop=emergency_stop,
        attribute_offers_unavailable=snapshot.attribute_offers_unavailable,
    )
    market = MarketView(
        floor_price=snapshot.floor_price,
        own_amount=own_row.amount if own_row is not None else None,
        own_rank=snapshot.own_rank,
        competitor_amount=snapshot.competitor_amount,
        competitor_unknown=snapshot.competitor_unknown,
        total_offers=snapshot.total_count,
        data_stale=False,
    )

    decision = decide(rule_snapshot(rule), market, account)
    rule.last_decision = {
        "action": decision.action,
        "status": decision.position_status,
        "reason": decision.reason,
        "target_price": money_str(decision.target_price) if decision.target_price is not None else None,
        "cap": money_str(decision.cap) if decision.cap is not None else None,
        "details": decision.details,
        "calculated_at": datetime.now(UTC).isoformat(),
    }
    rule.last_position_status = decision.position_status
    rule.next_run_at = default_next_run(rule)

    if decision.position_status != PositionStatus.API_ERROR.value:
        rule.last_error = None

    enqueued = False
    executed = False

    if not mode_live:
        executed = await _log_dry_run(session, rule, decision, snapshot)
    elif decision.action == "noop":
        # Если в LIVE режиме ничего не делаем, запишем причину, если она важна
        if decision.reason in ("BALANCE_UNKNOWN", "INSUFFICIENT_FUNDS", "FIXED_PRICE_ABOVE_CAP"):
            rule.last_error = f"Пропуск: {decision.reason}"
        else:
            rule.last_error = None
    elif decision.action == "pause":
        await _pause_rule(session, rule, decision.reason)
    elif decision.action == "create":
        enqueued = await _enqueue_create(session, rule, credential, decision, snapshot)
    elif decision.action == "update" and own_row is not None:
        if decision.target_price is None or not is_price_step_reached(
            own_row.amount, decision.target_price, rule_snapshot(rule).quantum
        ):
            enqueued = await _enqueue_update(session, rule, own_row, decision)
    elif decision.action == "cancel" and own_row is not None:
        enqueued = await _enqueue_cancel(session, rule, own_row, snapshot.scope_kind)

    await _emit_status_notifications(session, rule, decision, snapshot.floor_price)

    return CycleResult(
        rule_id=str(rule.id),
        action=decision.action,
        status=decision.position_status,
        reason=decision.reason,
        target_price=decision.target_price,
        enqueued=enqueued,
        executed=executed,
        detail=rule.last_decision or {},
    )


def _pick_own_row(own_rows: list[ManagedOffer], own_offer: dict[str, Any] | None) -> ManagedOffer | None:
    if own_offer is not None:
        offer_id = str(own_offer.get("id"))
        for row in own_rows:
            if row.external_offer_id == offer_id:
                return row
    if len(own_rows) == 1:
        return own_rows[0]
    return own_rows[0] if own_rows else None


async def _adopt_remote_offer(
    session: AsyncSession,
    rule: AutomationRule,
    credential: ApiCredential,
    offer: dict[str, Any],
    rank: int | None,
) -> ManagedOffer | None:
    external_id = str(offer.get("id") or "")
    if not external_id:
        return None

    row = (
        await session.execute(
            select(ManagedOffer).where(ManagedOffer.external_offer_id == external_id)
        )
    ).scalar_one_or_none()
    if row is not None and row.rule_id != rule.id:
        return None

    if row is None:
        scope = offer.get("scope") or {}
        row = ManagedOffer(
            user_id=rule.user_id,
            rule_id=rule.id,
            credential_id=credential.id,
            external_offer_id=external_id,
            collection_id=rule.collection_id,
            scope=scope,
            scope_kind=rule_scope_kind(rule),
            amount=to_decimal(offer.get("amount")) or ZERO,
            max_nfts=int(offer.get("max_nfts") or rule.max_nfts or 1),
            current_nfts=int(offer.get("current_nfts") or 0),
            status=OfferStatus.PENDING.value,
            position_status=PositionStatus.UNKNOWN.value,
            last_action="sync",
            last_action_at=datetime.now(UTC),
            raw=offer,
        )
        session.add(row)
    await sync_offer_row(session, row, offer, rank=rank)
    return row


async def _log_dry_run(
    session: AsyncSession,
    rule: AutomationRule,
    decision: Decision,
    snapshot,
) -> bool:
    message = f"DRY_RUN: {decision.action} — {decision.reason}"
    if decision.target_price is not None:
        message += f", целевая цена {money_str(decision.target_price)} GRAM"
    await audit.record(
        session,
        action="dry_run_decision",
        message=message,
        actor="worker",
        user_id=rule.user_id,
        entity_type="rule",
        entity_id=rule.id,
        details={
            "rule": rule.name,
            "status": decision.position_status,
            "action": decision.action,
            "target_price": money_str(decision.target_price) if decision.target_price else None,
            "floor_price": money_str(snapshot.floor_price) if snapshot.floor_price else None,
            "competitor_amount": money_str(snapshot.competitor_amount) if snapshot.competitor_amount else None,
        },
    )
    return True


async def _pause_rule(session: AsyncSession, rule: AutomationRule, reason: str) -> None:
    rule.state = RuleState.PAUSED.value
    rule.last_error = reason
    rule.enabled = False
    await audit.record(
        session,
        action=AuditAction.RULE_STATE_CHANGED.value,
        message=f"Правило «{rule.name}» приостановлено: {reason}",
        actor="worker",
        user_id=rule.user_id,
        entity_type="rule",
        entity_id=rule.id,
        level="warning",
    )
    await notifications.notify(
        session,
        user_id=rule.user_id,
        event="rule_paused",
        title="Правило приостановлено",
        message=f"«{rule.name}»: {reason}",
        level="warning",
    )


async def _enqueue_create(
    session: AsyncSession,
    rule: AutomationRule,
    credential: ApiCredential,
    decision: Decision,
    snapshot,
) -> bool:
    if decision.target_price is None:
        return False
    pending_create = await session.execute(
        select(OperationQueue.id)
        .where(
            OperationQueue.rule_id == rule.id,
            OperationQueue.operation_type == OperationType.CREATE_OFFER.value,
            OperationQueue.state.in_(
                (OperationState.PENDING.value, OperationState.RUNNING.value, OperationState.RETRY.value)
            ),
        )
        .limit(1)
    )
    if pending_create.scalar_one_or_none() is not None:
        return False

    active_offers = await session.execute(
        select(ManagedOffer.id)
        .where(
            ManagedOffer.rule_id == rule.id,
            ManagedOffer.status == OfferStatus.PENDING.value,
        )
        .limit(max(1, rule.max_active_offers))
    )
    if len(active_offers.scalars().all()) >= max(1, rule.max_active_offers):
        return False

    signature = _scope_signature(rule)
    attributes = rule_attributes(rule)
    dedupe_key = operations_service.make_dedupe_key(
        "create", rule.id, rule.collection_id, signature, money_str(decision.target_price), rule.max_nfts
    )
    operation = await operations_service.enqueue(
        session,
        dedupe_key=dedupe_key,
        operation_type=OperationType.CREATE_OFFER.value,
        user_id=rule.user_id,
        rule_id=rule.id,
        payload={
            "collection_id": rule.collection_id,
            "amount": money_str(decision.target_price),
            "cap": money_str(decision.cap) if decision.cap is not None else None,
            "max_nfts": rule.max_nfts,
            "attributes": attributes or None,
            "expiration_days": rule.expiration_days,
            "models": rule.models,
            "backdrops": rule.backdrops,
            "symbols": rule.symbols,
            "scope_kind": snapshot.scope_kind,
            "scope_signature": signature,
            "credential_id": str(credential.id),
        },
    )
    if operation is None:
        return False
    await audit.record(
        session,
        action="operation_scheduled",
        message=f"Запланировано создание оффера по правилу «{rule.name}» на {money_str(decision.target_price)} GRAM",
        actor="worker",
        user_id=rule.user_id,
        entity_type="rule",
        entity_id=rule.id,
        details={"operation_id": str(operation.id)},
    )
    return True


async def _enqueue_update(
    session: AsyncSession,
    rule: AutomationRule,
    row: ManagedOffer,
    decision: Decision,
) -> bool:
    if decision.target_price is None:
        return False
    dedupe_key = operations_service.make_dedupe_key(
        "update", row.id, money_str(decision.target_price)
    )
    operation = await operations_service.enqueue(
        session,
        dedupe_key=dedupe_key,
        operation_type=OperationType.UPDATE_OFFER.value,
        user_id=rule.user_id,
        rule_id=rule.id,
        offer_id=row.id,
        payload={
            "offer_row_id": str(row.id),
            "external_offer_id": row.external_offer_id,
            "amount": money_str(decision.target_price),
            "max_nfts": rule.max_nfts if rule.max_nfts > row.max_nfts else None,
            "scope_kind": row.scope_kind,
            "collection_id": row.collection_id,
            "credential_id": str(row.credential_id) if row.credential_id else None,
        },
    )
    if operation is None:
        return False
    await audit.record(
        session,
        action="operation_scheduled",
        message=(
            f"Запланировано повышение оффера {row.external_offer_id} "
            f"с {money_str(row.amount)} до {money_str(decision.target_price)} GRAM"
        ),
        actor="worker",
        user_id=rule.user_id,
        entity_type="offer",
        entity_id=row.id,
        details={"operation_id": str(operation.id), "rule": rule.name},
    )
    return True


async def _enqueue_cancel(
    session: AsyncSession,
    rule: AutomationRule,
    row: ManagedOffer,
    scope_kind: str,
) -> bool:
    dedupe_key = operations_service.make_dedupe_key("cancel", row.id)
    operation = await operations_service.enqueue(
        session,
        dedupe_key=dedupe_key,
        operation_type=OperationType.CANCEL_OFFER.value,
        user_id=rule.user_id,
        rule_id=rule.id,
        offer_id=row.id,
        payload={
            "offer_row_id": str(row.id),
            "external_offer_id": row.external_offer_id,
            "collection_id": row.collection_id,
            "scope_kind": scope_kind,
            "credential_id": str(row.credential_id) if row.credential_id else None,
        },
    )
    if operation is None:
        return False
    await audit.record(
        session,
        action="operation_scheduled",
        message=f"Запланирована отмена оффера {row.external_offer_id}",
        actor="worker",
        user_id=rule.user_id,
        entity_type="offer",
        entity_id=row.id,
        level="warning",
    )
    return True


async def _emit_status_notifications(
    session: AsyncSession,
    rule: AutomationRule,
    decision: Decision,
    floor_price: Decimal | None,
) -> None:
    if decision.position_status == PositionStatus.OUTBID.value:
        await notifications.notify(
            session,
            user_id=rule.user_id,
            event="outbid",
            title="Оффер перебит",
            message=f"«{rule.name}»: конкурент выше, целевая цена {money_str(decision.target_price) if decision.target_price else '—'} GRAM",
            level="warning",
        )
    elif decision.position_status == PositionStatus.LIMIT_REACHED.value:
        await notifications.notify(
            session,
            user_id=rule.user_id,
            event="limit_reached",
            title="Достигнут лимит цены",
            message=f"«{rule.name}»: {decision.reason}",
            level="warning",
        )
    elif decision.position_status == PositionStatus.INSUFFICIENT_FUNDS.value:
        await notifications.notify(
            session,
            user_id=rule.user_id,
            event="insufficient_funds",
            title="Недостаточно средств",
            message=f"«{rule.name}»: доступного баланса не хватает для повышения",
            level="error",
        )
    elif decision.position_status == PositionStatus.ATTRIBUTE_OFFERS_UNAVAILABLE.value:
        await notifications.notify(
            session,
            user_id=rule.user_id,
            event="attribute_offers_unavailable",
            title="Офферы по атрибутам недоступны",
            message=f"«{rule.name}»: API отклонил офферы по атрибутам",
            level="warning",
        )
    elif decision.position_status == PositionStatus.DATA_INCOMPLETE.value:
        await notifications.notify(
            session,
            user_id=rule.user_id,
            event="first_place_unconfirmed",
            title="Первое место не подтверждено",
            message=f"«{rule.name}»: {decision.reason}",
            level="info",
        )


def strategy_label(strategy: str) -> str:
    labels = {
        Strategy.FIXED.value: "Фиксированный оффер",
        Strategy.FLOOR_RELATIVE.value: "Цена относительно floor",
        Strategy.HOLD_FIRST_PLACE.value: "Удержание первого места",
        Strategy.MODELS_ONLY.value: "Только выбранные модели",
        Strategy.SAFE_PAUSE.value: "Пауза при неопределённости",
    }
    return labels.get(strategy, strategy)
