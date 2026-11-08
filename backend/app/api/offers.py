from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import AuthContext, as_uuid, get_db, require_csrf
from app.enums import OfferStatus, OperationType, PositionStatus, RuleState
from app.models import AutomationRule, CollectionCache, ManagedOffer, PurchasedGift
from app.money import money_str
from app.schemas import MessageOut, OfferOut, PurchasedGiftOut
from app.services import audit, operations_service
from app.services.offers_service import portals_gift_url, sync_remote_offers
from app.runtime import build_gateway, get_primary_credential

router = APIRouter(prefix="/api/offers", tags=["offers"])


@router.get("/purchased", response_model=list[PurchasedGiftOut])
async def list_purchased_gifts(
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> list[PurchasedGiftOut]:
    rows = (
        await session.execute(
            select(PurchasedGift)
            .where(PurchasedGift.user_id == context.user.id)
            .order_by(PurchasedGift.purchased_at.desc())
            .limit(500)
        )
    ).scalars().all()
    collection_ids = {row.collection_id for row in rows}
    collections = {
        item.id: item.name
        for item in (
            await session.execute(
                select(CollectionCache).where(CollectionCache.id.in_(collection_ids))
            )
        ).scalars().all()
    }
    return [
        PurchasedGiftOut(
            id=str(row.id),
            offer_id=str(row.offer_id),
            collection_id=row.collection_id,
            collection_name=collections.get(row.collection_id)
            or (row.raw or {}).get("collection_name")
            or (row.raw or {}).get("name")
            or row.collection_id,
            gift_id=row.gift_id,
            amount=money_str(row.amount),
            purchased_at=row.purchased_at,
            portals_url=portals_gift_url(row.raw or {}) or (row.raw or {}).get("portals_url"),
            raw=row.raw,
        )
        for row in rows
    ]


@router.post("/{offer_id}/mark-purchased", response_model=MessageOut)
async def mark_offer_purchased(
    offer_id: str,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> MessageOut:
    row = await _own_offer(session, context.user.id, offer_id)
    purchase_key = "manual-recovery"
    exists = await session.scalar(
        select(PurchasedGift.id).where(
            PurchasedGift.offer_id == row.id,
            PurchasedGift.purchase_key == purchase_key,
        )
    )
    if exists is None:
        session.add(
            PurchasedGift(
                user_id=row.user_id,
                offer_id=row.id,
                collection_id=row.collection_id,
                gift_id=None,
                purchase_key=purchase_key,
                amount=row.amount,
                purchased_at=datetime.now(UTC),
                raw={"recovered": True, "reason": "Подтверждено пользователем"},
            )
        )
    row.status = OfferStatus.COMPLETED.value
    row.last_action = "purchase_recovered"
    row.last_action_at = datetime.now(UTC)
    row.last_error = None
    if row.rule_id is not None:
        rule = await session.get(AutomationRule, row.rule_id)
        if rule is not None:
            rule.enabled = False
            rule.state = RuleState.PAUSED.value
            rule.next_run_at = None
            rule.locked_by = None
            rule.lease_expires_at = None
            rule.last_position_status = PositionStatus.UNKNOWN.value
            rule.last_error = "Покупка подтверждена: правило остановлено"
    return MessageOut(message="Покупка добавлена во вкладку «Мои подарки»")


@router.post("/sync-remote", response_model=MessageOut)
async def sync_remote(
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> MessageOut:
    credential = await get_primary_credential(session, context.user.id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нет подключённого API-ключа")
    synced = await sync_remote_offers(session, build_gateway(credential), credential)
    return MessageOut(message=f"Синхронизировано активных офферов: {synced}")


def offer_out(row: ManagedOffer, rule_name: str | None, collection_name: str | None) -> OfferOut:
    return OfferOut(
        id=str(row.id),
        rule_id=str(row.rule_id) if row.rule_id else None,
        rule_name=rule_name,
        source=(
            "rule"
            if row.rule_id is not None
            else str((row.raw or {}).get("source") or "manual")
        ),
        rebid_count=int((row.raw or {}).get("rebid_count") or 0),
        collection_id=row.collection_id,
        collection_name=collection_name,
        external_offer_id=row.external_offer_id,
        scope=row.scope or {},
        scope_kind=row.scope_kind,
        amount=money_str(row.amount) if row.amount is not None else "0",
        max_amount=money_str(row.max_amount) if row.max_amount is not None else None,
        max_nfts=row.max_nfts,
        current_nfts=row.current_nfts,
        status=row.status,
        position_status=row.position_status,
        position_rank=row.position_rank,
        last_action=row.last_action,
        last_action_at=row.last_action_at,
        last_synced_at=row.last_synced_at,
        last_error=row.last_error,
        created_at=row.created_at,
    )


@router.get("", response_model=list[OfferOut])
async def list_offers(
    rule_id: str | None = Query(default=None),
    offer_status: str | None = Query(default=None, alias="status"),
    source: str | None = Query(default=None),
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> list[OfferOut]:
    query = select(ManagedOffer).where(ManagedOffer.user_id == context.user.id)
    if rule_id:
        query = query.where(ManagedOffer.rule_id == as_uuid(rule_id, "Правило не найдено"))
    if offer_status:
        query = query.where(ManagedOffer.status == offer_status)
    query = query.order_by(ManagedOffer.created_at.desc()).limit(500)
    rows = (await session.execute(query)).scalars().all()
    if source:
        rows = [row for row in rows if (row.raw or {}).get("source", "manual") == source]

    rules = {
        row.id: row
        for row in (
            await session.execute(
                select(AutomationRule).where(AutomationRule.user_id == context.user.id)
            )
        ).scalars().all()
    }
    collection_ids = {row.collection_id for row in rows}
    collections = {
        row.id: row.name
        for row in (
            await session.execute(
                select(CollectionCache).where(CollectionCache.id.in_(collection_ids))
            )
        ).scalars().all()
    }
    return [
        offer_out(
            row,
            rules.get(row.rule_id).name if rules.get(row.rule_id) else None,
            rules.get(row.rule_id).collection_name if rules.get(row.rule_id) else collections.get(row.collection_id),
        )
        for row in rows
    ]


async def _own_offer(session: AsyncSession, user_id, offer_id: str) -> ManagedOffer:
    row = await session.get(ManagedOffer, as_uuid(offer_id, "Оффер не найден"))
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Оффер не найден")
    return row


@router.post("/{offer_id}/cancel", response_model=MessageOut)
async def cancel_offer(
    offer_id: str,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> MessageOut:
    row = await _own_offer(session, context.user.id, offer_id)
    if row.status == OfferStatus.CANCELED.value:
        return MessageOut(message="Оффер уже отменён")
    if (row.raw or {}).get("source") == "smart_trader":
        row.raw = {**(row.raw or {}), "manual_cancel_requested": True}
        row.last_error = "Оффер smart trader отменён вручную"

    row_id = row.id
    rule_id = row.rule_id
    collection_id = row.collection_id
    scope_kind = row.scope_kind
    external_offer_id = row.external_offer_id
    actor = context.user.username
    user_id = context.user.id
    operation = await operations_service.enqueue(
        session,
        dedupe_key=operations_service.make_dedupe_key("cancel", row_id, "manual"),
        operation_type=OperationType.CANCEL_OFFER.value,
        user_id=user_id,
        rule_id=rule_id,
        offer_id=row_id,
        payload={
            "offer_row_id": str(row_id),
            "external_offer_id": external_offer_id,
            "collection_id": collection_id,
            "scope_kind": scope_kind,
        },
    )
    await audit.record(
        session,
        action="offer_cancel_requested",
        message=f"Запрошена отмена оффера {external_offer_id}",
        actor=actor,
        user_id=user_id,
        entity_type="offer",
        entity_id=row_id,
        level="warning",
    )
    if operation is None:
        return MessageOut(message="Отмена уже в очереди")
    return MessageOut(message="Отмена поставлена в очередь")


@router.post("/{offer_id}/sync", response_model=MessageOut)
async def sync_offer(
    offer_id: str,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> MessageOut:
    row = await _own_offer(session, context.user.id, offer_id)
    operation = await operations_service.enqueue(
        session,
        dedupe_key=operations_service.make_dedupe_key("sync", row.id),
        operation_type=OperationType.SYNC_OFFER.value,
        user_id=context.user.id,
        rule_id=row.rule_id,
        offer_id=row.id,
        payload={
            "offer_row_id": str(row.id),
            "external_offer_id": row.external_offer_id,
            "collection_id": row.collection_id,
            "scope_kind": row.scope_kind,
        },
    )
    if operation is None:
        return MessageOut(message="Синхронизация уже в очереди")
    return MessageOut(message="Синхронизация поставлена в очередь")
