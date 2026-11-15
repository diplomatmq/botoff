from __future__ import annotations

import logging
from typing import Any, Iterator

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


def _extract_deprecated_model_entries(payload: Any) -> list[dict[str, Any]]:
    """Read the deprecated `models` list of an `attribute-floors` payload.

    Portals marks this list as deprecated and does not include every model, so it is
    only used as a fallback for `attribute_floors`.
    """
    if not isinstance(payload, dict):
        return []
    value = payload.get("models")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _iter_attribute_floor_models(payload: Any) -> Iterator[tuple[str, str, Any]]:
    """Iterate `(collection short name, model name, price)` of the `attribute_floors` map.

    Portals keys this map by the collection short name in lowercase and lists every
    model of the collection under `models`.
    """
    floors = payload.get("attribute_floors") if isinstance(payload, dict) else None
    if not isinstance(floors, dict):
        return
    for short_name, entry in floors.items():
        if not isinstance(entry, dict):
            continue
        models = entry.get("models")
        if not isinstance(models, dict):
            continue
        for model_name, price in models.items():
            yield str(short_name), model_name, price


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


_ATTRIBUTE_KEYS = {"model": "models", "backdrop": "backdrops", "symbol": "symbols"}


def _attribute_entries(floors: Any) -> list[dict[str, Any]]:
    """Normalize `{name: price}` and `{name: {floor_price, ...}}` maps into entries."""
    if not isinstance(floors, dict):
        return []
    entries: list[dict[str, Any]] = []
    for name, value in floors.items():
        key = str(name).strip()
        if not key:
            continue
        if isinstance(value, dict):
            price = (
                value.get("floor_price")
                or value.get("floor")
                or value.get("price")
                or value.get("amount")
            )
            photo = _photo_url(value)
        else:
            price = value
            photo = None
        entries.append({"name": key, "floor_price": price, "photo_url": photo})
    return entries


def collection_attribute_entries(
    payload: Any, attribute_type: str, collection_names: list[str | None]
) -> list[dict[str, Any]]:
    """Read model/backdrop/symbol floors of one collection from an `attribute-floors` payload."""
    key = _ATTRIBUTE_KEYS.get(attribute_type)
    floors = payload.get("attribute_floors") if isinstance(payload, dict) else None
    if key is None or not isinstance(floors, dict):
        return []
    for name in collection_names:
        if not name:
            continue
        entry = floors.get(name)
        if isinstance(entry, dict):
            entries = _attribute_entries(entry.get(key))
            if entries:
                return entries
    return []


def _model_background_entries(payload: Any) -> list[dict[str, Any]]:
    """Flatten `{"model_backgrounds": {model: {backdrop: price}}}` into backdrop entries."""
    grouped = payload.get("model_backgrounds") if isinstance(payload, dict) else None
    if not isinstance(grouped, dict):
        return []
    merged: dict[str, dict[str, Any]] = {}
    for per_model in grouped.values():
        for entry in _attribute_entries(per_model):
            current = merged.get(entry["name"])
            if current is None:
                merged[entry["name"]] = entry
                continue
            price = to_decimal(entry.get("floor_price"))
            known = to_decimal(current.get("floor_price"))
            if price is not None and (known is None or price < known):
                current["floor_price"] = entry["floor_price"]
    return list(merged.values())


async def resolve_attribute_entries(
    session: AsyncSession,
    gateway: PortalsGateway,
    collection_id: str,
    attribute_type: str,
    model_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Resolve backdrops/symbols of a collection from live Portals data.

    Backdrops and symbols are not cached locally, so we try several Portals sources
    in order of accuracy and return the first non-empty result.
    """
    collection = await session.get(CollectionCache, collection_id)
    names = [
        collection.name if collection is not None else None,
        collection.short_name if collection is not None else None,
        collection_id,
    ]

    source_errors: list[PortalsError] = []
    resolved = False
    requested_models = [
        str(name).strip() for name in model_names or [] if str(name).strip()
    ]
    if attribute_type == "backdrop" and requested_models:
        try:
            rows = _model_background_entries(
                await gateway.model_background_floors(requested_models)
            )
            resolved = True
        except PortalsError as exc:
            source_errors.append(exc)
            logger.warning(
                "selected model backgrounds unavailable for %s: %s", collection_id, exc
            )
            rows = []
        if rows:
            return rows

    attribute_payload: Any = None
    try:
        attribute_payload = await gateway.attribute_floors()
        resolved = True
    except PortalsError as exc:
        source_errors.append(exc)
        logger.warning("attribute floors unavailable for %s: %s", collection_id, exc)

    rows = collection_attribute_entries(attribute_payload, attribute_type, names)
    if rows:
        return rows

    if attribute_type == "backdrop":
        try:
            rows = _attribute_entries((await gateway.backdrop_floors() or {}).get("floorPrices"))
            resolved = True
        except PortalsError as exc:
            source_errors.append(exc)
            logger.warning("backdrop floors unavailable for %s: %s", collection_id, exc)
            rows = []
        if rows:
            return rows

        cached_model_names = requested_models or [
            row.name for row in await list_models(session, collection_id)
        ]
        if cached_model_names and not requested_models:
            try:
                rows = _model_background_entries(
                    await gateway.model_background_floors(cached_model_names)
                )
                resolved = True
            except PortalsError as exc:
                source_errors.append(exc)
                logger.warning(
                    "model background floors unavailable for %s: %s", collection_id, exc
                )
                rows = []
            if rows:
                return rows

    if attribute_payload is not None:
        rows = extract_attribute_entries(attribute_payload, attribute_type, collection_id)
        if rows:
            return rows
    # Only report a failure when no source answered at all; an empty answer is not an error.
    if not resolved and source_errors:
        raise source_errors[-1]
    return []


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

    collections = list((await session.execute(select(CollectionCache))).scalars().all())
    by_id = {row.id: row for row in collections}
    by_name = {row.name.lower(): row for row in collections}
    by_short_name = {row.short_name.lower(): row for row in collections if row.short_name}

    existing_models = {
        (row.collection_id, row.name): row
        for row in (await session.execute(select(ModelCache))).scalars().all()
    }

    touched: set[tuple[str, str]] = set()

    def upsert(
        collection: CollectionCache,
        name: Any,
        price: Any,
        photo_url: str | None = None,
        max_offer: Any = None,
    ) -> None:
        key = (collection.id, str(name)[:255])
        row = existing_models.get(key)
        if row is None:
            row = ModelCache(collection_id=collection.id, name=str(name)[:255])
            session.add(row)
            existing_models[key] = row
        touched.add(key)
        row.photo_url = photo_url or row.photo_url
        row.floor_price = to_decimal(price) or row.floor_price
        row.max_offer = to_decimal(max_offer) or row.max_offer
        row.source = "attribute_floors"

    # The current source of truth: `attribute_floors`, keyed by collection short name.
    for short_name, model_name, price in _iter_attribute_floor_models(payload):
        collection = by_short_name.get(short_name.lower())
        if collection is not None and model_name:
            upsert(collection, model_name, price)

    # Fallback for the deprecated `models` list, which the API still returns.
    for entry in _extract_deprecated_model_entries(payload):
        name = entry.get("name") or entry.get("model") or entry.get("value")
        price = entry.get("floor_price") or entry.get("amount") or entry.get("price")
        collection_id = entry.get("collection_id")
        collection_name = entry.get("collection_name")
        if collection_id is not None:
            collection = by_id.get(str(collection_id))
        elif collection_name:
            collection = by_name.get(str(collection_name).lower())
        else:
            collection = None
        if collection is not None and name:
            upsert(collection, name, price, _photo_url(entry), _max_offer(entry))

    await session.flush()
    return {"models": len(touched), "models_available": 1}


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
