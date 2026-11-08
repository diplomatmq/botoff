from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import AuthContext, as_uuid, get_db, require_csrf
from app.enums import AuditAction, AutomationMode, OfferStatus, RuleState, Strategy
from app.models import ApiCredential, AutomationRule, CollectionCache, ManagedOffer
from app.money import ZERO, money_str
from app.runtime import build_gateway, get_primary_credential
from app.schemas import DryRunPreview, MessageOut, RuleCreate, RuleOut, RuleStateChange, RuleUpdate
from app.services import audit, operations_service, settings_service
from app.services.engine import AccountView, MarketView, decide
from app.services.offers_service import (
    account_balance,
    build_market_snapshot,
    default_next_run,
    rule_active_offers,
    rule_committed_amount,
)
from app.services.rule_cycle import rule_snapshot

router = APIRouter(prefix="/api/rules", tags=["rules"])

ACTIVE_STATES = {RuleState.ACTIVE.value, RuleState.DRY_RUN.value}


def _state_enabled(state: str) -> bool:
    return state in ACTIVE_STATES


async def _active_offer_count(session: AsyncSession, rule_id) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(ManagedOffer)
        .where(
            ManagedOffer.rule_id == rule_id,
            ManagedOffer.status == OfferStatus.PENDING.value,
        )
    )
    return int(result.scalar_one())


async def _rule_out(session: AsyncSession, rule: AutomationRule) -> RuleOut:
    return RuleOut(
        id=str(rule.id),
        name=rule.name,
        collection_id=rule.collection_id,
        collection_name=rule.collection_name,
        scope_mode=rule.scope_mode,
        models=list(rule.models or []),
        backdrops=list(rule.backdrops or []),
        symbols=list(rule.symbols or []),
        scope_guard=rule.scope_guard,
        strategy=rule.strategy,
        hold_first_place=rule.hold_first_place,
        pause_on_uncertainty=rule.pause_on_uncertainty,
        discount_percent=str(rule.discount_percent or 0),
        max_price_percent=str(rule.max_price_percent) if rule.max_price_percent is not None else None,
        fixed_price=money_str(rule.fixed_price) if rule.fixed_price is not None else None,
        min_step=money_str(rule.min_step),
        max_price_per_offer=money_str(rule.max_price_per_offer) if rule.max_price_per_offer is not None else None,
        max_budget=money_str(rule.max_budget) if rule.max_budget is not None else None,
        max_active_offers=rule.max_active_offers,
        max_nfts=rule.max_nfts,
        expiration_days=rule.expiration_days,
        check_interval_seconds=rule.check_interval_seconds,
        enabled=rule.enabled,
        state=rule.state,
        on_limit_behavior=rule.on_limit_behavior,
        last_run_at=rule.last_run_at,
        next_run_at=rule.next_run_at,
        last_error=rule.last_error,
        last_position_status=rule.last_position_status,
        last_decision=rule.last_decision,
        active_offers=await _active_offer_count(session, rule.id),
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


async def _own_rule(session: AsyncSession, user_id, rule_id: str) -> AutomationRule:
    rule = await session.get(AutomationRule, as_uuid(rule_id, "Правило не найдено"))
    if rule is None or rule.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Правило не найдено")
    return rule


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный идентификатор") from exc


async def _require_collection(session: AsyncSession, collection_id: str) -> CollectionCache:
    collection = await session.get(CollectionCache, collection_id)
    if collection is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Коллекция не найдена. Обновите каталог коллекций.",
        )
    return collection


async def _apply_payload(session: AsyncSession, rule: AutomationRule, payload) -> None:
    collection = await _require_collection(session, payload.collection_id)
    if payload.credential_id is not None:
        credential_id = _parse_uuid(payload.credential_id)
        credential = await session.get(ApiCredential, credential_id)
        if credential is None or credential.user_id != rule.user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Указан недоступный API-ключ")

    rule.name = payload.name
    rule.collection_id = payload.collection_id
    rule.collection_name = collection.name
    rule.scope_mode = payload.scope_mode.value if hasattr(payload.scope_mode, "value") else str(payload.scope_mode)
    rule.models = list(payload.models)
    rule.backdrops = list(payload.backdrops)
    rule.symbols = list(payload.symbols)
    rule.scope_guard = payload.scope_guard
    rule.strategy = payload.strategy.value if hasattr(payload.strategy, "value") else str(payload.strategy)
    rule.hold_first_place = payload.hold_first_place or rule.strategy == Strategy.HOLD_FIRST_PLACE.value
    rule.pause_on_uncertainty = payload.pause_on_uncertainty
    rule.discount_percent = payload.discount_percent
    rule.max_price_percent = payload.max_price_percent
    rule.fixed_price = payload.fixed_price
    rule.min_step = payload.min_step
    rule.max_price_per_offer = payload.max_price_per_offer
    rule.max_budget = payload.max_budget
    rule.max_active_offers = payload.max_active_offers
    rule.max_nfts = payload.max_nfts
    rule.expiration_days = payload.expiration_days
    rule.check_interval_seconds = payload.check_interval_seconds
    rule.on_limit_behavior = (
        payload.on_limit_behavior.value
        if hasattr(payload.on_limit_behavior, "value")
        else str(payload.on_limit_behavior)
    )
    rule.credential_id = credential_id if payload.credential_id else rule.credential_id


def _set_state(rule: AutomationRule, state: str) -> None:
    rule.state = state
    rule.enabled = _state_enabled(state)
    if rule.enabled:
        rule.next_run_at = datetime.now(UTC)
    else:
        rule.next_run_at = None
        rule.lease_expires_at = None
        rule.locked_by = None


@router.get("", response_model=list[RuleOut])
async def list_rules(
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> list[RuleOut]:
    rows = (
        await session.execute(
            select(AutomationRule)
            .where(AutomationRule.user_id == context.user.id)
            .order_by(AutomationRule.created_at.desc())
        )
    ).scalars().all()
    return [await _rule_out(session, row) for row in rows]


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: RuleCreate,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> RuleOut:
    await _require_collection(session, payload.collection_id)
    rule = AutomationRule(
        user_id=context.user.id,
        name=payload.name,
        collection_id=payload.collection_id,
        credential_id=uuid.UUID(payload.credential_id) if payload.credential_id else None,
    )
    session.add(rule)
    await session.flush()
    await _apply_payload(session, rule, payload)
    _set_state(rule, payload.state.value if hasattr(payload.state, "value") else str(payload.state))
    await audit.record(
        session,
        action=AuditAction.RULE_CREATED.value,
        message=f"Создано правило «{rule.name}»",
        actor=context.user.username,
        user_id=context.user.id,
        entity_type="rule",
        entity_id=rule.id,
    )
    await session.flush()
    return await _rule_out(session, rule)


@router.get("/{rule_id}", response_model=RuleOut)
async def get_rule(
    rule_id: str,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> RuleOut:
    rule = await _own_rule(session, context.user.id, rule_id)
    return await _rule_out(session, rule)


@router.put("/{rule_id}", response_model=RuleOut)
async def update_rule(
    rule_id: str,
    payload: RuleUpdate,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> RuleOut:
    rule = await _own_rule(session, context.user.id, rule_id)
    await _apply_payload(session, rule, payload)
    if payload.state is not None:
        _set_state(rule, payload.state.value)
    await audit.record(
        session,
        action=AuditAction.RULE_UPDATED.value,
        message=f"Обновлено правило «{rule.name}»",
        actor=context.user.username,
        user_id=context.user.id,
        entity_type="rule",
        entity_id=rule.id,
    )
    await session.flush()
    return await _rule_out(session, rule)


@router.delete("/{rule_id}", response_model=MessageOut)
async def delete_rule(
    rule_id: str,
    cancel_offers: bool = True,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> MessageOut:
    rule = await _own_rule(session, context.user.id, rule_id)
    offers = await rule_active_offers(session, rule.id)
    if cancel_offers:
        for row in offers:
            await operations_service.enqueue(
                session,
                dedupe_key=operations_service.make_dedupe_key("cancel", row.id, "rule_delete"),
                operation_type="cancel_offer",
                user_id=context.user.id,
                rule_id=rule.id,
                offer_id=row.id,
                payload={
                    "offer_row_id": str(row.id),
                    "external_offer_id": row.external_offer_id,
                    "collection_id": row.collection_id,
                    "scope_kind": row.scope_kind,
                },
            )
    name = rule.name
    await session.delete(rule)
    await audit.record(
        session,
        action=AuditAction.RULE_DELETED.value,
        message=f"Удалено правило «{name}»" + (f", отмена офферов: {len(offers)}" if cancel_offers else ""),
        actor=context.user.username,
        user_id=context.user.id,
        level="warning",
    )
    return MessageOut(message="Правило удалено")


@router.post("/{rule_id}/state", response_model=RuleOut)
async def change_state(
    rule_id: str,
    payload: RuleStateChange,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> RuleOut:
    rule = await _own_rule(session, context.user.id, rule_id)

    if payload.enabled is not None and payload.state is None:
        target = RuleState.ACTIVE.value if payload.enabled else RuleState.DISABLED.value
    elif payload.state is not None:
        target = payload.state.value
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Укажите состояние правила")

    if target == RuleState.ACTIVE.value:
        automation_enabled = await settings_service.get_setting(session, "automation_enabled", False)
        mode = await settings_service.get_setting(session, "mode", AutomationMode.DRY_RUN.value)
        if mode != AutomationMode.LIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Включите режим LIVE в настройках, чтобы активировать правило",
            )
        if not automation_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Автоматизация выключена. Включите её в настройках.",
            )

    _set_state(rule, target)
    if rule.enabled:
        rule.last_error = None
    await audit.record(
        session,
        action=AuditAction.RULE_STATE_CHANGED.value,
        message=f"Правило «{rule.name}»: состояние {target}",
        actor=context.user.username,
        user_id=context.user.id,
        entity_type="rule",
        entity_id=rule.id,
    )
    await session.flush()
    return await _rule_out(session, rule)


@router.post("/{rule_id}/preview", response_model=DryRunPreview)
async def preview_rule(
    rule_id: str,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> DryRunPreview:
    rule = await _own_rule(session, context.user.id, rule_id)
    credential = None
    if rule.credential_id is not None:
        credential = await session.get(ApiCredential, rule.credential_id)
    if credential is None or credential.status != "active":
        credential = await get_primary_credential(session, context.user.id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сначала подключите API-ключ Portals")

    gateway = build_gateway(credential)
    balance, _ = await account_balance(session, gateway)
    snapshot = await build_market_snapshot(
        session, gateway, rule, credential_sender_id=credential.sender_id
    )
    own_rows = await rule_active_offers(session, rule.id)
    own_row = own_rows[0] if own_rows else None
    committed = rule_committed_amount(own_rows)

    market = MarketView(
        floor_price=snapshot.floor_price,
        own_amount=own_row.amount if own_row is not None else None,
        own_rank=snapshot.own_rank,
        competitor_amount=snapshot.competitor_amount,
        competitor_unknown=snapshot.competitor_unknown,
        total_offers=snapshot.total_count,
        data_stale=False,
    )
    account = AccountView(
        available=balance,
        reserved=ZERO,
        rule_committed=committed,
        active_offers_for_rule=len(own_rows),
        mode_live=False,
        automation_enabled=True,
        emergency_stop=False,
        attribute_offers_unavailable=snapshot.attribute_offers_unavailable,
    )

    decision = decide(rule_snapshot(rule), market, account)
    return DryRunPreview(
        rule_id=str(rule.id),
        action=decision.action,
        status=decision.position_status,
        reason=decision.reason,
        target_price=money_str(decision.target_price) if decision.target_price is not None else None,
        cap=money_str(decision.cap) if decision.cap is not None else None,
        floor_price=money_str(snapshot.floor_price) if snapshot.floor_price is not None else None,
        competitor_amount=money_str(snapshot.competitor_amount) if snapshot.competitor_amount is not None else None,
        own_amount=money_str(own_row.amount) if own_row is not None and own_row.amount is not None else None,
        own_rank=snapshot.own_rank + 1 if snapshot.own_rank is not None else None,
        total_offers=snapshot.total_count,
        detail={
            "error": snapshot.error,
            "rate_limited": snapshot.rate_limited,
            "scope_kind": snapshot.scope_kind,
            "available": money_str(balance) if balance is not None else None,
        },
    )
