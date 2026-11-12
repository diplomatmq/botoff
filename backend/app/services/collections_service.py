from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CollectionCache, ModelCache
from app.money import to_decimal
from app.portals.client import PortalsGateway
from app.portals.errors import PortalsError

logger = logging.getLogger("portals.collections")


def _photo_url(item: dict[str, Any]) -> str | None:
    for key in ("photo_url", "image_url", "image", "thumbnail_url", "url"):
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("url") or value.get("src")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _max_offer(item: dict[str, Any]) -> Any:
    nested_offers = item.get("offers")
    if isinstance(nested_offers, list):
        amounts = [
            to_decimal(offer.get("amount") or offer.get("price") or offer.get("value"))
            for offer in nested_offers
            if isinstance(offer, dict)
        ]
        amounts = [amount for amount in amounts if amount is not None]
        if amounts:
            return max(amounts)
    for key in ("max_offer", "max_offer_amount", "max_amount", "top_offer"):
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("amount") or value.get("price") or value.get("value")
        if value is not None:
            return value
    return None


def _iter_floor_entries(payload: Any):
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, dict):
                text = value.get("floor_price") or value.get("amount") or value.get("price") or value.get("floor")
                if text is not None:
                    yield str(key), text
                else:
                    inner = value.get("collection_id") or value.get("id")
                    if inner is not None and value.get("floor_price") is not None:
                        yield str(inner), value.get("floor_price")
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                cid = item.get("collection_id") or item.get("id")
                price = item.get("floor_price") or item.get("amount") or item.get("price")
                if cid is not None and price is not None:
                    yield str(cid), price


def _extract_model_entries(payload: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("models", "attribute_floors"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, dict))
            elif isinstance(value, dict):
                for name, entry in value.items():
                    if isinstance(entry, dict):
                        merged = {"name": name, **entry}
                        candidates.append(merged)
                    elif isinstance(entry, list):
                        for sub in entry:
                            if isinstance(sub, dict):
                                candidates.append({"name": name, **sub})
    elif isinstance(payload, list):
        candidates.extend(item for item in payload if isinstance(item, dict))
    return candidates


def extract_attribute_entries(payload: Any, attribute_type: str, collection_id: str) -> list[dict[str, Any]]:
    """Extract named model/background/symbol floor entries from variant Portals payloads."""
    entries: dict[str, dict[str, Any]] = {}

    def visit(
        value: Any,
        context: str | None = None,
        collection_context: str | None = None,
    ) -> None:
        if isinstance(value, dict):
            current = context
            raw_type = str(value.get("type") or value.get("attribute_type") or "").lower()
            if raw_type in {"model", "background", "backdrop", "symbol"}:
                if raw_type == "model":
                    current = "model"
                elif raw_type in {"background", "backdrop"}:
                    current = "backdrop"
                else:
                    current = "symbol"
            if (
                current is None
                and (
                    value.get("model_name") is not None
                    or value.get("model") is not None
                )
            ):
                current = "model"
            if (
                current is None
                and (
                    value.get("background_name") is not None
                    or value.get("backdrop_name") is not None
                    or value.get("background") is not None
                    or value.get("backdrop") is not None
                )
            ):
                current = "backdrop"
            if (
                current is None
                and (
                    value.get("symbol_name") is not None
                    or value.get("symbol") is not None
                )
            ):
                current = "symbol"
            if current == attribute_type:
                name = (
                    value.get("name")
                    or value.get("value")
                    or value.get(attribute_type)
                    or value.get("model_name")
                    or value.get("background_name")
                    or value.get("backdrop_name")
                    or value.get("symbol_name")
                )
                item_collection = value.get("collection_id") or collection_context or collection_id
                if name is not None and str(item_collection) == collection_id:
                    # Store or update the entry with all available data
                    existing = entries.get(str(name), {})
                    entries[str(name)] = {
                        "name": str(name),
                        "floor_price": (
                            value.get("floor_price")
                            or value.get("floor")
                            or value.get("price")
                            or value.get("amount")
                            or existing.get("floor_price")
                        ),
                        "photo_url": _photo_url(value) or existing.get("photo_url"),
                        "photos": value.get("photos") or existing.get("photos"),
                        "image_url": value.get("image_url") or existing.get("image_url"),
                        "thumbnail_url": value.get("thumbnail_url") or existing.get("thumbnail_url"),
                    }
            for key, child in value.items():
                key_lower = str(key).lower()
                child_context = current
                if key_lower in {"models", "model"}:
                    child_context = "model"
                elif key_lower in {"backgrounds", "backdrops", "background", "backdrop"}:
                    child_context = "backdrop"
                elif key_lower in {"symbols", "symbol"}:
                    child_context = "symbol"
                if (
                    child_context == attribute_type
                    and isinstance(child, dict)
                    and not any(child.get(field) for field in ("name", "value", attribute_type))
                    and key_lower not in {"models", "model", "backgrounds", "backdrops", "background", "backdrop", "symbols", "symbol"}
                ):
                    child = {"name": key, **child}
                child_collection = key if str(key) == collection_id else collection_context
                visit(child, child_context, child_collection)
        elif isinstance(value, list):
            for child in value:
                visit(child, context, collection_context)

    visit(payload)
    return list(entries.values())


async def refresh_catalog(session: AsyncSession, gateway: PortalsGateway) -> dict[str, int]:
    preview = await gateway.collections_preview()
    preview_items = (preview or {}).get("collections") or []

    supported_ids: set[str] = set()
    offers_payload: dict[str, Any] = {}
    try:
        offers_payload = await gateway.offer_collections() or {}
        for item in offers_payload.get("collections") or []:
            cid = item.get("id")
            if cid:
                supported_ids.add(str(cid))
    except PortalsError as exc:
        logger.warning("offer collections unavailable: %s", exc)

    floors: dict[str, Any] = {}
    try:
        floor_payload = await gateway.collection_floors() or {}
        floors = {cid: price for cid, price in _iter_floor_entries(floor_payload.get("floorPrices"))}
    except PortalsError as exc:
        logger.warning("collection floors unavailable: %s", exc)

    attribute_payload = await _fetch_attribute_floors(gateway)

    offers_by_id = {str(item.get("id")): item for item in (offers_payload.get("collections") or []) if item.get("id")}

    existing = {row.id: row for row in (await session.execute(select(CollectionCache))).scalars().all()}
    seen: set[str] = set()
    created = 0
    updated = 0

    for item in preview_items:
        cid = item.get("id")
        if not cid:
            continue
        cid = str(cid)
        seen.add(cid)
        offer_info = offers_by_id.get(cid, {})
        floor = to_decimal(item.get("floor_price"))
        if floor is None:
            floor = to_decimal(floors.get(cid))
        row = existing.get(cid)
        if row is None:
            row = CollectionCache(id=cid)
            session.add(row)
            created += 1
        else:
            updated += 1
        row.name = str(item.get("name") or row.name or cid)[:255]
        row.short_name = (item.get("short_name") or None)
        row.photo_url = _photo_url(item) or row.photo_url
        row.floor_price = floor
        row.max_offer = to_decimal(_max_offer(offer_info)) or row.max_offer
        supply = item.get("supply")
        try:
            row.supply = int(supply) if supply is not None else row.supply
        except (TypeError, ValueError):
            pass
        row.day_volume = to_decimal(item.get("day_volume")) or row.day_volume
        row.market_cap = to_decimal(offer_info.get("market_cap")) or row.market_cap
        row.is_new = bool(item.get("is_new"))
        row.zero_commission = bool(item.get("zero_commission") or offer_info.get("zero_commission"))
        row.cashback_percent = to_decimal(item.get("cashback_percent"))
        row.points_multiplier = to_decimal(item.get("points_multiplier"))
        row.offers_supported = cid in supported_ids

        models_meta = []
        if item.get("models"):
            models_meta = item.get("models")
        if not row.raw or row.raw.get("models") != models_meta:
            raw = dict(item)
            raw["models"] = models_meta
            row.raw = raw

    await session.flush()

    models_report = await _apply_attribute_floors(session, attribute_payload)
    return {"collections": created + updated, "created": created, "updated": updated, **models_report}


async def _fetch_attribute_floors(gateway: PortalsGateway) -> Any:
    try:
        return await gateway.attribute_floors()
    except PortalsError as exc:
        logger.warning("attribute floors unavailable: %s", exc)
        return None


async def refresh_models(session: AsyncSession, gateway: PortalsGateway) -> dict[str, int]:
    return await _apply_attribute_floors(session, await _fetch_attribute_floors(gateway))


async def _apply_attribute_floors(session: AsyncSession, payload: Any) -> dict[str, int]:
    if payload is None:
        return {"models": 0, "models_available": 0}

    entries = _extract_model_entries(payload)
    if not entries:
        return {"models": 0, "models_available": 0}

    collections = {
        row.name.lower(): row for row in (await session.execute(select(CollectionCache))).scalars().all()
    }
    by_id = {row.id: row for row in collections.values()}

    existing_models = {
        (row.collection_id, row.name): row
        for row in (await session.execute(select(ModelCache))).scalars().all()
    }

    count = 0
    for entry in entries:
        name = entry.get("name") or entry.get("model") or entry.get("value")
        price = entry.get("floor_price") or entry.get("amount") or entry.get("price")
        collection_id = entry.get("collection_id")
        collection_name = entry.get("collection_name")
        if collection_id is None and collection_name:
            target = collections.get(str(collection_name).lower())
            if target is not None:
                collection_id = target.id
        if collection_id is None:
            continue
        collection_id = str(collection_id)
        if collection_id not in by_id or not name:
            continue
        key = (collection_id, str(name)[:255])
        row = existing_models.get(key)
        if row is None:
            row = ModelCache(collection_id=collection_id, name=str(name)[:255])
            session.add(row)
            existing_models[key] = row
        row.photo_url = _photo_url(entry) or row.photo_url
        row.floor_price = to_decimal(price) or row.floor_price
        row.max_offer = to_decimal(_max_offer(entry)) or row.max_offer
        row.source = "attribute_floors"
        count += 1

    await session.flush()
    return {"models": count, "models_available": 1}


async def list_collections(
    session: AsyncSession,
    *,
    search: str | None = None,
    only_offers: bool = False,
    sort_by: str = "name",
    sort_order: str = "asc",
    limit: int = 200,
    offset: int = 0,
) -> list[CollectionCache]:
    query = select(CollectionCache)
    if search:
        pattern = f"%{search.lower()}%"
        query = query.where(CollectionCache.name.ilike(pattern))
    if only_offers:
        query = query.where(CollectionCache.offers_supported.is_(True))
    column = CollectionCache.name if sort_by == "name" else CollectionCache.floor_price
    query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
    query = query.limit(min(limit, 500)).offset(max(0, offset))
    return list((await session.execute(query)).scalars().all())


async def list_models(session: AsyncSession, collection_id: str) -> list[ModelCache]:
    return list(
        (
            await session.execute(
                select(ModelCache)
                .where(ModelCache.collection_id == collection_id)
                .order_by(ModelCache.name.asc())
            )
        )
        .scalars()
        .all()
    )


async def clear_models(session: AsyncSession, collection_id: str) -> None:
    await session.execute(delete(ModelCache).where(ModelCache.collection_id == collection_id))
