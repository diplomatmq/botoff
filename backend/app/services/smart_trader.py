from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import OfferStatus, OperationType
from app.models import ApiCredential, CollectionCache, ManagedOffer, ModelCache, OperationQueue
from app.money import ZERO, increase_by_step, to_decimal
from app.portals.client import PortalsGateway
from app.portals.errors import PortalsError
from app.services import operations_service, settings_service
from app.services.collections_service import extract_attribute_entries
from app.services.offers_service import (
    offer_entries,
    sender_matches,
    sync_offer_row,
)

SOURCE = "smart_trader"
logger = logging.getLogger("portals.smart_trader")


def _excluded_value(values: set[str], collection_id: str, value: str) -> bool:
    return value in values or f"{collection_id}:{value}" in values


def _collection_exclusions(
    values: set[str],
    collection_id: str,
    legacy_collection_id: str | None = None,
) -> set[str]:
    prefix = f"{collection_id}:"
    return {
        value.removeprefix(prefix)
        for value in values
        if value.startswith(prefix)
        or (":" not in value and collection_id == legacy_collection_id)
    }


def _row_is_excluded(
    row: ManagedOffer,
    excluded_collections: set[str],
    excluded_models: set[str],
    excluded_backdrops: set[str],
    legacy_collection_id: str | None = None,
) -> bool:
    if row.collection_id in excluded_collections:
        return True
    scope = row.scope or {}
    models = scope.get("models") or []
    backdrops = scope.get("backdrops") or []
    collection_models = _collection_exclusions(excluded_models, row.collection_id, legacy_collection_id)
    collection_backdrops = _collection_exclusions(excluded_backdrops, row.collection_id, legacy_collection_id)
    if not models and not backdrops and (collection_models or collection_backdrops):
        return True
    return any(
        str(value) in collection_models
        for value in models
    ) or any(
        str(value) in collection_backdrops
        for value in backdrops
    )


def _signature(collection_id: str, attributes: list[dict[str, str]]) -> str:
    encoded = "|".join(f"{item['type']}:{item['value']}" for item in attributes)
    return hashlib.sha256(f"{SOURCE}:{collection_id}:{encoded}".encode()).hexdigest()[:24]


async def _enqueue_cancel(
    session: AsyncSession,
    *,
    user_id,
    row: ManagedOffer,
    reason: str | None = None,
) -> bool:
    if reason:
        row.last_error = reason[:500]
    operation = await operations_service.enqueue(
        session,
        dedupe_key=operations_service.make_dedupe_key("trader-cancel", row.id),
        operation_type=OperationType.CANCEL_OFFER.value,
        user_id=user_id,
        offer_id=row.id,
        payload={
            "offer_row_id": str(row.id),
            "external_offer_id": row.external_offer_id,
            "collection_id": row.collection_id,
            "scope_kind": row.scope_kind,
            "credential_id": str(row.credential_id) if row.credential_id else None,
        },
    )
    return operation is not None


async def run(
    session: AsyncSession,
    *,
    user_id,
    credential: ApiCredential,
    gateway: PortalsGateway,
) -> int:
    if not await settings_service.get_setting(session, "smart_trader_enabled", False):
        return 0
    spread = Decimal(str(await settings_service.get_setting(
        session, "smart_trader_min_spread_percent", "0"
    )))
    max_rebids = await settings_service.get_setting(session, "smart_trader_max_rebids_per_offer", None)
    max_rebids = int(max_rebids) if max_rebids is not None else None
    if max_rebids == 0:
        max_rebids = None
    step = Decimal(str(await settings_service.get_setting(session, "default_min_step", "0.00001")))
    try:
        balance, frozen = await _wallet(gateway)
    except PortalsError as exc:
        logger.warning("wallet lookup failed; smart trader cycle skipped: %s", exc)
        return 0
    # Portals returns `balance` as already available funds. `frozen_funds`
    # is informational and must not be subtracted a second time.
    available = balance or ZERO
    excluded_collections = set(
        await settings_service.get_setting(session, "smart_trader_excluded_collections", [])
    )
    excluded_models = set(await settings_service.get_setting(session, "smart_trader_excluded_models", []))
    excluded_backdrops = set(
        await settings_service.get_setting(session, "smart_trader_excluded_backdrops", [])
    )
    legacy_attribute_collection_id = await settings_service.get_setting(
        session, "smart_trader_attribute_collection_id", None
    )
    await session.commit()

    collections = (await session.execute(
        select(CollectionCache).where(CollectionCache.offers_supported.is_(True))
    )).scalars().all()
    all_local_rows = (await session.execute(
        select(ManagedOffer).where(
            ManagedOffer.user_id == user_id,
            ManagedOffer.credential_id == credential.id,
        )
    )).scalars().all()
    manually_cancelled_collections = {
        row.collection_id
        for row in all_local_rows
        if (row.raw or {}).get("source") == SOURCE
        and row.status == OfferStatus.PENDING.value
        and (row.raw or {}).get("manual_cancel_requested") is True
    }
    excluded_rows = [
        row for row in all_local_rows
        if (row.raw or {}).get("source") == SOURCE
        and row.status == OfferStatus.PENDING.value
        and _row_is_excluded(
            row,
            excluded_collections,
            excluded_models,
            excluded_backdrops,
            legacy_attribute_collection_id,
        )
    ]
    blocked_collections = {
        row.collection_id for row in excluded_rows
    } | manually_cancelled_collections
    for row in excluded_rows:
        await _enqueue_cancel(
            session,
            user_id=user_id,
            row=row,
            reason="Оффер отклонён: подарок добавлен в исключения smart trader",
        )
    local_rows = [
        row for row in all_local_rows
        if row.status == OfferStatus.PENDING.value
    ]
    by_collection = {
        row.collection_id: row for row in local_rows
        if (row.raw or {}).get("source") == SOURCE
    }
    pending_create = (
        await session.execute(
            select(OperationQueue).where(
                OperationQueue.user_id == user_id,
                OperationQueue.operation_type == OperationType.CREATE_OFFER.value,
                OperationQueue.state.in_(("pending", "running", "retry")),
            )
        )
    ).scalars().all()
    for operation in pending_create:
        payload = operation.payload or {}
        if payload.get("source") != SOURCE:
            continue
        collection_id = str(payload.get("collection_id") or "")
        collection_models_excluded = _collection_exclusions(
            excluded_models, collection_id, legacy_attribute_collection_id
        )
        collection_backdrops_excluded = _collection_exclusions(
            excluded_backdrops, collection_id, legacy_attribute_collection_id
        )
        if collection_id in excluded_collections:
            operation.state = "cancelled"
            blocked_collections.add(collection_id)
        elif collection_id and (
            any(str(value) in collection_models_excluded for value in payload.get("models") or [])
            or any(str(value) in collection_backdrops_excluded for value in payload.get("backdrops") or [])
        ):
            operation.state = "cancelled"
            blocked_collections.add(collection_id)
    pending_create = [
        operation for operation in pending_create
        if operation.state in ("pending", "running", "retry")
        and (operation.payload or {}).get("source") == SOURCE
    ]
    has_pending_create = bool(pending_create)
    if len(by_collection) > 1:
        keep = max(by_collection.values(), key=lambda item: item.updated_at)
        for row in by_collection.values():
            if row.id != keep.id:
                await _enqueue_cancel(session, user_id=user_id, row=row)
        by_collection = {keep.collection_id: keep}

    candidates: list[tuple[Decimal, CollectionCache, Decimal, list[dict[str, str]]]] = []
    for collection in collections:
        if collection.id in excluded_collections:
            continue
        if collection.id in blocked_collections:
            continue
        if collection.floor_price is None:
            continue
        collection_models_excluded = _collection_exclusions(
            excluded_models, collection.id, legacy_attribute_collection_id
        )
        collection_backdrops_excluded = _collection_exclusions(
            excluded_backdrops, collection.id, legacy_attribute_collection_id
        )
        attributes: list[dict[str, str]] = []
        attribute_restriction = bool(collection_models_excluded or collection_backdrops_excluded)
        if collection_models_excluded:
            models = (
                await session.execute(select(ModelCache).where(ModelCache.collection_id == collection.id))
            ).scalars().all()
            attributes.extend(
                {"type": "model", "value": model.name}
                for model in models
                if model.name not in collection_models_excluded
            )
            if not attributes and models:
                continue
        if collection_backdrops_excluded:
            try:
                await session.commit()
                backdrop_payload = await gateway.model_background_floors(collection.id)
                attributes.extend(
                    {"type": "backdrop", "value": entry["name"]}
                    for entry in extract_attribute_entries(backdrop_payload, "backdrop", collection.id)
                    if entry["name"] not in collection_backdrops_excluded
                )
            except PortalsError:
                continue
        if attribute_restriction and not attributes:
            continue
        attributes = sorted(attributes, key=lambda item: (item["type"], item["value"]))
        row = by_collection.get(collection.id)
        desired_models = {item["value"] for item in attributes if item["type"] == "model"}
        desired_backdrops = {item["value"] for item in attributes if item["type"] == "backdrop"}
        if row is not None:
            current_scope = row.scope or {}
            current_models = set(current_scope.get("models") or [])
            current_backdrops = set(current_scope.get("backdrops") or [])
            if current_models != desired_models or current_backdrops != desired_backdrops:
                await _enqueue_cancel(
                    session,
                    user_id=user_id,
                    row=row,
                    reason="Оффер обновлён: изменились исключения моделей или фонов",
                )
                by_collection.pop(collection.id, None)
                blocked_collections.add(collection.id)
                continue
        minimum_gap = collection.floor_price * spread / Decimal("100")
        maximum_target = collection.floor_price - minimum_gap
        try:
            await session.commit()
            raw = await gateway.offers_all(collection.id, scope="broad", limit=10)
        except PortalsError as exc:
            logger.warning("offers lookup failed for collection %s: %s", collection.id, exc)
            continue
        offers = [
            offer
            for entry in offer_entries(raw)
            for offer in (entry.get("offers") or [])
            if isinstance(offer, dict)
        ]
        own_offer = next(
            (
                offer for offer in offers
                if sender_matches(offer.get("sender_id"), credential.sender_id)
                or (row is not None and str(offer.get("id")) == row.external_offer_id)
            ),
            None,
        )
        if row is not None and own_offer is not None:
            await sync_offer_row(session, row, own_offer, rank=None)
            if row.status != OfferStatus.PENDING.value:
                by_collection.pop(collection.id, None)
                continue
        if row is not None:
            row.position_rank = (
                next(
                    (
                        index + 1
                        for index, offer in enumerate(
                            sorted(
                                [
                                    offer for offer in offers
                                    if to_decimal(offer.get("amount")) is not None
                                ],
                                key=lambda offer: to_decimal(offer.get("amount")) or ZERO,
                                reverse=True,
                            )
                        )
                        if str(offer.get("id")) == str((own_offer or {}).get("id"))
                    ),
                    None,
                )
                if own_offer is not None
                else None
            )
        own_offer_id = str((own_offer or {}).get("id") or "")
        competitor_offers = [
            offer for offer in offers
            if not sender_matches(offer.get("sender_id"), credential.sender_id)
            and str(offer.get("id")) != own_offer_id
        ]
        amounts = [to_decimal(offer.get("amount")) for offer in competitor_offers]
        amounts = [amount for amount in amounts if amount is not None]
        cancelled_for_gap = False
        if row is not None and row.amount is not None and row.amount > maximum_target:
            await _enqueue_cancel(
                session,
                user_id=user_id,
                row=row,
                reason="Оффер отклонён: достигнут порог минимального разрыва от floor",
            )
            by_collection.pop(collection.id, None)
            cancelled_for_gap = True
        if not amounts:
            continue
        best = max(amounts)
        gap = collection.floor_price - best
        target = increase_by_step(best, step, Decimal("0.00001"))
        if cancelled_for_gap:
            continue
        if row is not None and target >= collection.floor_price:
            if await _enqueue_cancel(
                session,
                user_id=user_id,
                row=row,
                reason="Оффер отклонён: невыгодно, цена достигла floor",
            ):
                by_collection.pop(collection.id, None)
        if gap <= ZERO or target > maximum_target:
            continue
        if target >= collection.floor_price:
            continue
        candidates.append((gap, collection, target, attributes))

    candidates.sort(key=lambda item: item[0], reverse=True)
    changed = 0
    has_active_offer = bool(by_collection) or has_pending_create
    for _, collection, target, attributes in candidates:
        row = by_collection.get(collection.id)
        if row is not None:
            current = row.amount or ZERO
            if target <= current:
                continue
            additional_required = target - current
            if target > available + current:
                await _enqueue_cancel(
                    session,
                    user_id=user_id,
                    row=row,
                    reason="Оффер отклонён: недостаточно средств для перебива",
                )
                by_collection.pop(collection.id, None)
                continue
            rebids = int((row.raw or {}).get("rebid_count") or 0)
            if max_rebids is not None and rebids >= max_rebids:
                if await _enqueue_cancel(
                    session,
                    user_id=user_id,
                    row=row,
                    reason="Оффер отклонён: достигнут порог перебивов",
                ):
                    changed += 1
                continue
            operation = await operations_service.enqueue(
                session,
                dedupe_key=operations_service.make_dedupe_key("trader-update", row.id, target),
                operation_type=OperationType.UPDATE_OFFER.value,
                user_id=user_id,
                offer_id=row.id,
                payload={"offer_row_id": str(row.id), "collection_id": row.collection_id,
                         "amount": str(target), "scope_kind": "broad", "source": SOURCE},
            )
            if operation is None:
                continue
            available -= additional_required
            row.raw = {**(row.raw or {}), "rebid_count": rebids + 1, "source": SOURCE}
            changed += 1
            continue

        if target > available:
            continue
        if has_active_offer:
            continue
        await operations_service.enqueue(
            session,
            dedupe_key=operations_service.make_dedupe_key("trader-create", _signature(collection.id, attributes)),
            operation_type=OperationType.CREATE_OFFER.value,
            user_id=user_id,
            payload={"source": SOURCE, "scope_signature": _signature(collection.id, attributes),
                     "collection_id": collection.id, "amount": str(target), "cap": str(collection.floor_price),
                     "max_nfts": 1, "scope_kind": "trait" if attributes else "broad", "attributes": attributes,
                     "models": [item["value"] for item in attributes if item["type"] == "model"],
                     "backdrops": [item["value"] for item in attributes if item["type"] == "backdrop"],
                     "rebid_count": 0, "credential_id": str(credential.id)},
        )
        available -= target
        has_active_offer = True
        changed += 1
    return changed


async def _wallet(gateway: PortalsGateway) -> tuple[Decimal | None, Decimal | None]:
    payload: Any = await gateway.wallet()
    if not isinstance(payload, dict):
        return None, None
    return to_decimal(payload.get("balance")), to_decimal(payload.get("frozen_funds"))
