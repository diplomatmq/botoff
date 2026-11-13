from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import OfferStatus, PositionStatus, RuleState
from app.models import (
    ApiCredential,
    AutomationRule,
    CollectionCache,
    ManagedOffer,
    MarketSnapshot,
    ModelCache,
    PurchasedGift,
)
from app.money import ZERO, money_str, to_decimal
from app.notifications import service as notifications
from app.portals.client import PortalsGateway
from app.portals.errors import PortalsError, PortalsRateLimited, is_trait_unavailable

logger = logging.getLogger("portals.offers")

FLOOR_TTL_SECONDS = 600
SNAPSHOT_TTL_SECONDS = 120


@dataclass(slots=True)
class MarketSnapshotData:
    collection_id: str
    scope_kind: str
    offers: list[dict[str, Any]]
    total_count: int
    floor_price: Decimal | None
    own_offer: dict[str, Any] | None
    own_rank: int | None
    competitor_amount: Decimal | None
    competitor_unknown: bool
    attribute_offers_unavailable: bool
    error: str | None = None
    rate_limited: bool = False


def offer_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        nested = payload.get("offers")
        if isinstance(nested, list):
            return [{"offers": nested, "total_count": payload.get("total_count")}]
        for key in ("data", "results", "collections"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def sender_matches(value: Any, sender_id: int | None) -> bool:
    return sender_id is not None and str(value) == str(sender_id)


def rule_scope_kind(rule: AutomationRule) -> str:
    return "trait" if rule_uses_attributes(rule) else "broad"


def rule_uses_attributes(rule: AutomationRule) -> bool:
    return bool(rule.models or rule.backdrops or rule.symbols or rule.excluded_backdrops)


def rule_excluded_backdrops(rule: AutomationRule) -> set[str]:
    return {str(value) for value in (rule.excluded_backdrops or [])}


def rule_attributes(rule: AutomationRule) -> list[dict[str, str]]:
    attributes: list[dict[str, str]] = []
    for value in rule.models or []:
        attributes.append({"type": "model", "value": value})
    for value in rule.backdrops or []:
        attributes.append({"type": "backdrop", "value": value})
    for value in rule.symbols or []:
        attributes.append({"type": "symbol", "value": value})
    return attributes


@dataclass(slots=True, frozen=True)
class RuleScope:
    """A single independently managed offer inside one rule.

    When several models are selected the rule is split into one scope per model,
    so every model gets its own offer that is priced from its own floor and
    tracked on its own.
    """

    models: tuple[str, ...] = ()
    backdrops: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    excluded_backdrops: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return ", ".join(self.models) if self.models else "вся коллекция"


def scope_uses_attributes(scope: RuleScope) -> bool:
    return bool(scope.models or scope.backdrops or scope.symbols or scope.excluded_backdrops)


def scope_kind(scope: RuleScope) -> str:
    return "trait" if scope_uses_attributes(scope) else "broad"


def scope_signature(scope: RuleScope) -> str:
    payload = "|".join(
        [
            ",".join(sorted(scope.models)),
            ",".join(sorted(scope.backdrops)),
            ",".join(sorted(scope.symbols)),
            ",".join(sorted(scope.excluded_backdrops)),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def rule_scope(rule: AutomationRule) -> RuleScope:
    return RuleScope(
        models=tuple(str(value) for value in (rule.models or [])),
        backdrops=tuple(str(value) for value in (rule.backdrops or [])),
        symbols=tuple(str(value) for value in (rule.symbols or [])),
        excluded_backdrops=tuple(str(value) for value in (rule.excluded_backdrops or [])),
    )


def rule_scopes(rule: AutomationRule) -> list[RuleScope]:
    base = rule_scope(rule)
    if not base.models:
        return [base]
    return [
        RuleScope(
            models=(model,),
            backdrops=base.backdrops,
            symbols=base.symbols,
            excluded_backdrops=base.excluded_backdrops,
        )
        for model in base.models
    ]


def row_matches_scope(row: ManagedOffer, scope: RuleScope) -> bool:
    row_scope = row.scope or {}
    return (
        {str(value) for value in (row_scope.get("models") or [])} == set(scope.models)
        and {str(value) for value in (row_scope.get("backdrops") or [])} == set(scope.backdrops)
        and {str(value) for value in (row_scope.get("symbols") or [])} == set(scope.symbols)
    )


def offer_belongs_to_scope(offer: dict[str, Any], scope: RuleScope) -> bool:
    attributes = offer_scope_attributes(offer)
    return (
        attributes["model"] == set(scope.models)
        and attributes["backdrop"] == set(scope.backdrops)
        and attributes["symbol"] == set(scope.symbols)
    )


def offer_scope_attributes(offer: dict[str, Any]) -> dict[str, set[str]]:
    scope = offer.get("scope") or {}
    values: dict[str, set[str]] = {
        "model": set(str(value) for value in scope.get("models") or []),
        "backdrop": set(str(value) for value in scope.get("backdrops") or []),
        "symbol": set(str(value) for value in scope.get("symbols") or []),
    }
    attributes = offer.get("attributes")
    if isinstance(attributes, list):
        for attribute in attributes:
            if not isinstance(attribute, dict):
                continue
            attribute_type = str(attribute.get("type") or "").lower()
            value = attribute.get("value") or attribute.get("name")
            if attribute_type in values and value is not None:
                values[attribute_type].add(str(value))
    for attribute_type, keys in {
        "model": ("model", "model_name"),
        "backdrop": ("backdrop", "backdrop_name", "background", "background_name"),
        "symbol": ("symbol", "symbol_name"),
    }.items():
        for key in keys:
            value = offer.get(key)
            if value is not None:
                values[attribute_type].add(str(value))
    return values


def offer_matches_rule(offer: dict[str, Any], rule: AutomationRule) -> bool:
    """
    Determines if an offer competes with a rule.

    Key logic:
    - If rule has NO attributes selected (all empty), it matches ALL offers (broad scope)
    - If rule has attributes selected, it only matches offers that:
      a) Have NO attributes specified (broad offers match all rules)
      b) Have overlapping attributes with the rule

    Backdrop nuances:
    - A rule that keeps every backdrop ("all backdrops") does not compete with an offer
      narrowed down to specific backdrops: such an offer only fights for that subset.
    - Backdrops listed in `rule.excluded_backdrops` are ignored on both sides: a competitor
      targeting only excluded backdrops is not a competitor.
    """
    return offer_matches_attributes(
        offer,
        models=set(rule.models or []),
        backdrops=set(rule.backdrops or []),
        symbols=set(rule.symbols or []),
        excluded_backdrops=rule_excluded_backdrops(rule),
    )


def offer_matches_scope(offer: dict[str, Any], scope: RuleScope) -> bool:
    return offer_matches_attributes(
        offer,
        models=set(scope.models),
        backdrops=set(scope.backdrops),
        symbols=set(scope.symbols),
        excluded_backdrops=set(scope.excluded_backdrops),
    )


def offer_matches_attributes(
    offer: dict[str, Any],
    *,
    models: set[str],
    backdrops: set[str],
    symbols: set[str],
    excluded_backdrops: set[str],
) -> bool:
    offer_attributes = offer_scope_attributes(offer)
    offer_models = offer_attributes["model"]
    offer_backdrops = offer_attributes["backdrop"]
    offer_symbols = offer_attributes["symbol"]

    # Broad offer (no attributes specified) - it's a wildcard
    offer_is_broad = not (offer_models or offer_backdrops or offer_symbols)

    # Scope with no attributes selected - matches everything
    rule_is_broad = not (models or backdrops or symbols or excluded_backdrops)

    if rule_is_broad:
        # Scope wants all items in collection - matches all offers
        return True

    if offer_is_broad:
        # Broad offer competes with all scopes
        return True

    # Competitors that target only backdrops excluded by the scope are not competitors.
    if excluded_backdrops and offer_backdrops and offer_backdrops <= excluded_backdrops:
        return False

    # The scope keeps all backdrops, so an offer narrowed to specific backdrops
    # competes only for that subset and can be ignored.
    if not backdrops and offer_backdrops:
        return False

    # Check for attribute overlap
    # If scope specifies models and offer has models, they must overlap
    if models and offer_models and not (offer_models & models):
        return False
    if backdrops and offer_backdrops and not (offer_backdrops & backdrops):
        return False
    if symbols and offer_symbols and not (offer_symbols & symbols):
        return False

    # A trait offer scoped only to an unselected attribute does not compete
    # with a scope for another attribute. Broad offers remain applicable.
    if models and not offer_models and (offer_backdrops or offer_symbols):
        return False
    if backdrops and not offer_backdrops and (offer_models or offer_symbols):
        return False
    if symbols and not offer_symbols and (offer_models or offer_backdrops):
        return False

    return True


async def _resolve_floor(
    session: AsyncSession,
    gateway: PortalsGateway,
    collection: CollectionCache | None,
    collection_id: str,
) -> Decimal | None:
    now = datetime.now(UTC)
    raw = dict(collection.raw or {}) if collection else {}
    fetched_at = raw.get("floor_fetched_at")
    fresh = False
    if fetched_at:
        try:
            fresh = (now - datetime.fromisoformat(fetched_at)).total_seconds() < FLOOR_TTL_SECONDS
        except ValueError:
            fresh = False

    if collection is not None and collection.floor_price is not None and fresh:
        return collection.floor_price

    try:
        payload = await gateway.top_offer(collection_id)
        if payload:
            floor = to_decimal((payload.get("collection") or {}).get("floor_price"))
            if floor is not None:
                if collection is not None:
                    collection.floor_price = floor
                    raw["floor_fetched_at"] = now.isoformat()
                    collection.raw = raw
                return floor
    except PortalsError as exc:
        logger.debug("top offer unavailable for %s: %s", collection_id, exc)

    # Fallback to cached floor if API call failed or returned no floor
    if collection is not None and collection.floor_price is not None:
        return collection.floor_price

    # Last resort: try to refresh this specific collection from preview
    try:
        preview = await gateway.collections_preview()
        items = (preview or {}).get("collections") or []
        for item in items:
            if str(item.get("id")) == collection_id:
                floor = to_decimal(item.get("floor_price"))
                if floor is not None:
                    if collection is not None:
                        collection.floor_price = floor
                        raw["floor_fetched_at"] = now.isoformat()
                        collection.raw = raw
                    return floor
    except PortalsError:
        pass

    return None


async def resolve_model_floor(
    session: AsyncSession,
    gateway: PortalsGateway,
    collection: CollectionCache | None,
    collection_id: str,
    model_name: str,
) -> Decimal | None:
    """Floor of a single model, falling back to the collection floor when unknown.

    Model floors are cached in `ModelCache` and refreshed on demand so a stale
    value cannot make the rule overpay above the real floor of the model.
    """
    now = datetime.now(UTC)
    row = (
        await session.execute(
            select(ModelCache).where(
                ModelCache.collection_id == collection_id,
                ModelCache.name == model_name,
            )
        )
    ).scalar_one_or_none()
    if row is not None and _model_floor_is_fresh(row, now):
        return row.floor_price

    if await _refresh_model_floors_once(session, gateway):
        row = (
            await session.execute(
                select(ModelCache).where(
                    ModelCache.collection_id == collection_id,
                    ModelCache.name == model_name,
                )
            )
        ).scalar_one_or_none()
        if row is not None and row.floor_price is not None:
            return row.floor_price
    elif row is not None and row.floor_price is not None:
        return row.floor_price

    return await _resolve_floor(session, gateway, collection, collection_id)


def _model_floor_is_fresh(row: ModelCache, now: datetime) -> bool:
    if row.floor_price is None:
        return False
    value = _as_utc(row.updated_at)
    if value is None:
        return False
    return (now - value).total_seconds() < FLOOR_TTL_SECONDS


_model_floors_refreshed_at: datetime | None = None


async def _refresh_model_floors_once(session: AsyncSession, gateway: PortalsGateway) -> bool:
    """Refresh every cached model floor at most once per FLOOR_TTL_SECONDS."""
    global _model_floors_refreshed_at

    now = datetime.now(UTC)
    if _model_floors_refreshed_at is not None and (
        now - _model_floors_refreshed_at
    ).total_seconds() < FLOOR_TTL_SECONDS:
        return False
    _model_floors_refreshed_at = now

    from app.services import collections_service

    try:
        await collections_service.refresh_models(session, gateway)
    except PortalsError as exc:
        logger.debug("model floors refresh failed: %s", exc)
        return False
    return True


async def resolve_scope_floor(
    session: AsyncSession,
    gateway: PortalsGateway,
    collection: CollectionCache | None,
    collection_id: str,
    scope: RuleScope,
) -> Decimal | None:
    """Price basis of a scope: the model floor for a single-model offer."""
    if len(scope.models) == 1:
        return await resolve_model_floor(
            session, gateway, collection, collection_id, scope.models[0]
        )
    return await _resolve_floor(session, gateway, collection, collection_id)


def _snapshot_own_rows(
    rows: list[ManagedOffer], scope: RuleScope
) -> list[ManagedOffer]:
    return [row for row in rows if row_matches_scope(row, scope)]


async def build_market_snapshot(
    session: AsyncSession,
    gateway: PortalsGateway,
    rule: AutomationRule,
    *,
    credential_sender_id: int | None = None,
    scope: RuleScope | None = None,
) -> MarketSnapshotData:
    scope = scope or rule_scope(rule)
    collection_id = rule.collection_id
    scope_kind_value = scope_kind(scope)
    collection = await session.get(CollectionCache, collection_id)

    own_rows_all = list(
        (
            await session.execute(
                select(ManagedOffer).where(
                    ManagedOffer.rule_id == rule.id,
                    ManagedOffer.status.in_([OfferStatus.PENDING.value, OfferStatus.UNKNOWN.value]),
                )
            )
        )
        .scalars()
        .all()
    )
    own_rows = _snapshot_own_rows(own_rows_all, scope)
    own_ids = {row.external_offer_id for row in own_rows}

    try:
        payload = await gateway.offers_all(collection_id, scope=scope_kind_value, limit=10)
    except PortalsRateLimited as exc:
        await _store_snapshot(session, collection_id, scope_kind_value, [], 0, None)
        return MarketSnapshotData(
            collection_id,
            scope_kind_value,
            [],
            0,
            None,
            None,
            None,
            None,
            False,
            False,
            error=str(exc),
            rate_limited=True,
        )
    except PortalsError as exc:
        return MarketSnapshotData(
            collection_id,
            scope_kind_value,
            [],
            0,
            None,
            None,
            None,
            None,
            False,
            is_trait_unavailable(exc),
            error=str(exc),
        )

    rows = offer_entries(payload)
    offers: list[dict[str, Any]] = []
    total_count = 0
    has_explicit_total = False
    for entry in rows:
        if isinstance(entry, dict):
            offers.extend(entry.get("offers") or [])
            if entry.get("total_count") is not None:
                has_explicit_total = True
                total_count = max(total_count, int(entry.get("total_count") or 0))
    if not total_count:
        total_count = len(offers)

    floor = await resolve_scope_floor(session, gateway, collection, collection_id, scope)

    own_offer: dict[str, Any] | None = None
    own_rank: int | None = None
    for index, offer in enumerate(offers):
        offer_id = str(offer.get("id") or "")
        if not offer_id:
            continue
        # Prefer our known offer rows of this scope; the live scope may be missing
        # attributes that the API normalised away.
        if offer_id in own_ids:
            if own_offer is None:
                own_offer, own_rank = offer, index
            continue
        if (
            credential_sender_id is not None
            and sender_matches(offer.get("sender_id"), credential_sender_id)
            and offer_belongs_to_scope(offer, scope)
        ):
            if own_offer is None:
                own_offer, own_rank = offer, index

    relevant_competitors: list[Decimal] = []
    for offer in offers:
        offer_id = str(offer.get("id") or "")
        if own_offer is not None and offer_id == str(own_offer.get("id")):
            continue
        if own_ids and offer_id in own_ids:
            continue
        if sender_matches(offer.get("sender_id"), credential_sender_id):
            continue
        if not offer_matches_scope(offer, scope):
            continue
        amount = to_decimal(offer.get("amount"))
        if amount is not None:
            relevant_competitors.append(amount)

    competitor_amount = max(relevant_competitors) if relevant_competitors else None
    competitor_unknown = own_offer is None and total_count > len(offers)

    # `offers_all` is intentionally limited to the first page.  Without an
    # explicit total_count, absence from that page does not prove cancellation.
    if (
        own_offer is None
        and own_rows
        and has_explicit_total
        and total_count <= len(offers)
        and not competitor_unknown
    ):
        for row in own_rows:
            row.status = OfferStatus.CANCELED.value
            row.position_status = PositionStatus.UNKNOWN.value
            row.last_action = "sync"
            row.last_action_at = datetime.now(UTC)
            row.last_error = "Оффер не найден в активной ленте коллекции"

    await _store_snapshot(session, collection_id, scope_kind_value, offers, total_count, floor)

    return MarketSnapshotData(
        collection_id=collection_id,
        scope_kind=scope_kind_value,
        offers=offers,
        total_count=total_count,
        floor_price=floor,
        own_offer=own_offer,
        own_rank=own_rank,
        competitor_amount=competitor_amount,
        competitor_unknown=competitor_unknown,
        attribute_offers_unavailable=False,
    )


async def _store_snapshot(
    session: AsyncSession,
    collection_id: str,
    scope_kind: str,
    offers: list[dict[str, Any]],
    total_count: int,
    floor: Decimal | None,
) -> None:
    best = None
    for offer in offers:
        amount = to_decimal(offer.get("amount"))
        if amount is not None and (best is None or amount > best):
            best = amount
    session.add(
        MarketSnapshot(
            collection_id=collection_id,
            scope=scope_kind,
            floor_price=floor,
            best_amount=best,
            offers_count=total_count,
            offers=[
                {
                    "id": offer.get("id"),
                    "amount": offer.get("amount"),
                    "sender_id": offer.get("sender_id"),
                    "scope": offer.get("scope"),
                }
                for offer in offers[:10]
            ],
        )
    )


def snapshot_is_stale(captured_at: datetime | None, ttl_seconds: int = SNAPSHOT_TTL_SECONDS) -> bool:
    if captured_at is None:
        return True
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - captured_at).total_seconds() > ttl_seconds


def is_error_code_rate_limited(message: str | None) -> bool:
    return bool(message and "429" in message)


def portals_gift_url(gift: dict[str, Any]) -> str | None:
    telegram_id = gift.get("tg_id")
    if telegram_id:
        return f"https://t.me/nft/{telegram_id}"
    name = gift.get("name") or gift.get("collection_name")
    number = gift.get("external_collection_number")
    if name and number is not None:
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", str(name)).strip("_")
        if slug:
            return f"https://t.me/nft/{slug}-{number}"
    gift_id = gift.get("id")
    return f"https://t.me/nft/{gift_id}" if gift_id else None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def remember_owned_inventory(
    row: ManagedOffer,
    gateway: PortalsGateway,
) -> None:
    if not hasattr(gateway, "owned_nfts"):
        return
    try:
        payload = await gateway.owned_nfts(row.collection_id)
    except PortalsError:
        return
    nfts = payload.get("nfts") if isinstance(payload, dict) else None
    if not isinstance(nfts, list):
        return
    raw = dict(row.raw or {})
    raw["owned_inventory_ids"] = [
        str(item.get("id"))
        for item in nfts
        if isinstance(item, dict) and item.get("id")
    ]
    row.raw = raw


async def recover_owned_purchase(
    session: AsyncSession,
    row: ManagedOffer,
    gateway: PortalsGateway,
) -> bool:
    if not hasattr(gateway, "owned_nfts"):
        return False
    try:
        payload = await gateway.owned_nfts(row.collection_id)
    except PortalsError:
        return False
    return await recover_owned_purchase_from_payload(session, row, payload)


async def recover_owned_purchase_from_payload(
    session: AsyncSession,
    row: ManagedOffer,
    payload: dict[str, Any],
) -> bool:
    nfts = payload.get("nfts") if isinstance(payload, dict) else None
    if not isinstance(nfts, list):
        return False
    previous_ids = set((row.raw or {}).get("owned_inventory_ids") or [])
    candidates = [
        item for item in nfts
        if isinstance(item, dict) and item.get("id") and str(item["id"]) not in previous_ids
    ]
    if not previous_ids:
        last_seen = _as_utc(row.last_synced_at or row.updated_at)
        recent_candidates: list[dict[str, Any]] = []
        for item in candidates:
            imported_at = item.get("imported_at")
            if not imported_at:
                continue
            try:
                imported_time = datetime.fromisoformat(str(imported_at).replace("Z", "+00:00"))
            except ValueError:
                continue
            imported_time = _as_utc(imported_time)
            if last_seen is None or imported_time >= last_seen:
                recent_candidates.append(item)
        candidates = recent_candidates
    if not candidates:
        return False
    purchased_at = datetime.now(UTC)
    recovered = False
    for item in candidates[: max(1, row.max_nfts - row.current_nfts)]:
        gift_id = str(item["id"])
        exists = await session.scalar(
            select(PurchasedGift.id).where(
                PurchasedGift.offer_id == row.id,
                PurchasedGift.purchase_key == gift_id,
            )
        )
        if exists is not None:
            continue
        session.add(
            PurchasedGift(
                user_id=row.user_id,
                offer_id=row.id,
                collection_id=row.collection_id,
                gift_id=gift_id,
                purchase_key=gift_id,
                amount=row.amount,
                purchased_at=purchased_at,
                raw={**item, "portals_url": portals_gift_url(item), "recovered_from_inventory": True},
            )
        )
        row.current_nfts += 1
        recovered = True
    if recovered:
        row.status = OfferStatus.COMPLETED.value
        row.last_action = "purchase_recovered_from_inventory"
        row.last_action_at = purchased_at
        row.last_error = None
    return recovered


async def sync_offer_row(
    session: AsyncSession,
    row: ManagedOffer,
    offer: dict[str, Any] | None,
    *,
    rank: int | None,
    wallet_balance: Decimal | None = None,
) -> None:
    now = datetime.now(UTC)
    row.last_synced_at = now
    if offer is None:
        if row.status == OfferStatus.PENDING.value:
            row.status = OfferStatus.UNKNOWN.value
        row.position_status = PositionStatus.UNKNOWN.value
        return
    previous_nfts = row.current_nfts
    row.amount = to_decimal(offer.get("amount"), row.amount) or row.amount
    row.max_nfts = int(offer.get("max_nfts") or row.max_nfts)
    row.current_nfts = int(offer.get("current_nfts") or 0)
    row.raw = {**(row.raw or {}), **offer}
    status = str(offer.get("status") or "pending")
    if status in {"pending", "completed", "canceled"}:
        row.status = status
    if rank is None:
        row.position_status = PositionStatus.UNKNOWN.value
        row.position_rank = None
    else:
        row.position_rank = rank + 1
        row.position_status = (
            PositionStatus.FIRST_CONFIRMED.value if rank == 0 else PositionStatus.OUTBID.value
        )
    if row.current_nfts > previous_nfts:
        await _record_purchases_and_stop_rule(
            session,
            row,
            offer,
            previous_nfts=previous_nfts,
            wallet_balance=wallet_balance,
        )


async def _record_purchases_and_stop_rule(
    session: AsyncSession,
    row: ManagedOffer,
    offer: dict[str, Any],
    *,
    previous_nfts: int,
    wallet_balance: Decimal | None = None,
) -> None:
    purchased_count = row.current_nfts - previous_nfts
    items: list[dict[str, Any]] = []
    for key in ("purchased_gifts", "purchased_items", "filled_items", "nfts", "items"):
        value = offer.get(key)
        if isinstance(value, list):
            items.extend(item for item in value if isinstance(item, dict))
            break

    if not items:
        items = [{} for _ in range(purchased_count)]
    else:
        items = items[-purchased_count:]

    purchased_at = datetime.now(UTC)
    row.last_action = "purchased"
    row.last_action_at = purchased_at
    for offset, item in enumerate(items):
        gift_id = item.get("id") or item.get("gift_id") or item.get("nft_id")
        purchase_key = str(gift_id) if gift_id is not None else f"count-{previous_nfts + offset + 1}"
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
                    gift_id=str(gift_id) if gift_id is not None else None,
                    purchase_key=purchase_key,
                    amount=row.amount,
                    purchased_at=purchased_at,
                    raw={
                        **(item or offer),
                        "portals_url": portals_gift_url(item or offer),
                    },
                )
            )

    model_names = [
        str(value)
        for value in (row.scope or {}).get("models") or []
    ]
    model_floor: Decimal | None = None
    if model_names:
        model_floor = await session.scalar(
            select(ModelCache.floor_price)
            .where(
                ModelCache.collection_id == row.collection_id,
                ModelCache.name.in_(model_names),
            )
            .order_by(ModelCache.floor_price.desc())
            .limit(1)
        )
    floor_text = money_str(model_floor) if model_floor is not None else "—"
    purchase_amount = row.amount * purchased_count
    reported_balance = wallet_balance
    if reported_balance is None:
        reported_balance = (
            to_decimal(offer.get("balance"))
            or to_decimal(offer.get("wallet_balance"))
            or to_decimal(offer.get("available_balance"))
        )
    balance_text = money_str(reported_balance) if reported_balance is not None else "—"
    await notifications.notify(
        session,
        user_id=row.user_id,
        event="offer_filled",
        title="Оффер исполнен",
        message=(
            f"Куплено: {purchased_count} шт. на {money_str(purchase_amount)} GRAM\n"
            f"Цена за штуку: {money_str(row.amount)} GRAM\n"
            f"Floor модели: {floor_text} GRAM\n"
            f"Баланс: {balance_text} GRAM"
        ),
        level="success",
    )

    if row.current_nfts >= row.max_nfts:
        row.status = OfferStatus.COMPLETED.value
        row.last_action = "purchase_completed"
        row.last_action_at = purchased_at
        if row.rule_id is not None:
            rule = await session.get(AutomationRule, row.rule_id)
            if rule is not None and rule.enabled:
                rule.enabled = False
                rule.state = RuleState.PAUSED.value
                rule.next_run_at = None
                rule.locked_by = None
                rule.lease_expires_at = None
                rule.last_position_status = PositionStatus.UNKNOWN.value
                rule.last_error = "Оффер исполнен: подарок куплен, правило остановлено"


async def rule_active_offers(session: AsyncSession, rule_id) -> list[ManagedOffer]:
    return list(
        (
            await session.execute(
                select(ManagedOffer).where(
                    ManagedOffer.rule_id == rule_id,
                    ManagedOffer.status == OfferStatus.PENDING.value,
                )
            )
        )
        .scalars()
        .all()
    )


def rule_committed_amount(offers: list[ManagedOffer]) -> Decimal:
    total = ZERO
    for row in offers:
        if row.status != OfferStatus.PENDING.value:
            continue
        total += (row.amount or ZERO) * max(1, row.max_nfts)
    return total


async def account_balance(session: AsyncSession, gateway: PortalsGateway) -> tuple[Decimal | None, Decimal | None]:
    try:
        payload = await gateway.wallet()
    except PortalsError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    return to_decimal(payload.get("balance")), to_decimal(payload.get("frozen_funds"))


async def sync_remote_offers(
    session: AsyncSession,
    gateway: PortalsGateway,
    credential: ApiCredential,
) -> int:
    if credential.sender_id is None:
        raise PortalsError("Не удалось определить sender_id API-ключа")

    collections = (
        await session.execute(
            select(CollectionCache.id)
            .where(CollectionCache.offers_supported.is_(True))
            .order_by(CollectionCache.id)
        )
    ).scalars().all()
    synced = 0
    remote_ids: set[str] = set()
    complete_collections: set[str] = set()
    for collection_id in collections:
        try:
            payload = await asyncio.wait_for(
                gateway.offers_all(str(collection_id), scope="broad", limit=10),
                timeout=15,
            )
        except asyncio.TimeoutError:
            logger.warning("remote offer sync timed out for collection %s", collection_id)
            continue
        except PortalsRateLimited:
            logger.warning("remote offer sync rate limited at collection %s", collection_id)
            break
        except PortalsError as exc:
            logger.warning("remote offer sync failed for collection %s: %s", collection_id, exc)
            continue
        for entry in offer_entries(payload):
            total_count = int(entry.get("total_count") or 0)
            offers = entry.get("offers") or []
            if total_count <= len(offers):
                complete_collections.add(str(collection_id))
            for offer in offers:
                if not sender_matches(offer.get("sender_id"), credential.sender_id):
                    continue
                external_id = str(offer.get("id") or "")
                if not external_id:
                    continue
                remote_ids.add(external_id)
                row = (
                    await session.execute(
                        select(ManagedOffer).where(ManagedOffer.external_offer_id == external_id)
                    )
                ).scalar_one_or_none()
                if row is None:
                    row = ManagedOffer(
                        user_id=credential.user_id,
                        rule_id=None,
                        credential_id=credential.id,
                        external_offer_id=external_id,
                        collection_id=str(collection_id),
                        scope=offer.get("scope") or {},
                        scope_kind="broad",
                        amount=to_decimal(offer.get("amount")) or ZERO,
                        max_nfts=int(offer.get("max_nfts") or 1),
                        current_nfts=int(offer.get("current_nfts") or 0),
                        status=OfferStatus.PENDING.value,
                        position_status=PositionStatus.UNKNOWN.value,
                        last_action="sync",
                        last_action_at=datetime.now(UTC),
                    )
                    session.add(row)
                await sync_offer_row(session, row, offer, rank=None)
                synced += 1

    stale_rows = (
        await session.execute(
            select(ManagedOffer).where(
                ManagedOffer.user_id == credential.user_id,
                ManagedOffer.credential_id == credential.id,
                ManagedOffer.status == OfferStatus.PENDING.value,
                ManagedOffer.scope_kind == "broad",
                ManagedOffer.collection_id.in_(complete_collections),
            )
        )
    ).scalars().all()
    for row in stale_rows:
        if row.external_offer_id not in remote_ids:
            row.status = OfferStatus.CANCELED.value
            row.position_status = PositionStatus.UNKNOWN.value
            row.last_action = "sync"
            row.last_action_at = datetime.now(UTC)
            row.last_error = "Оффер отсутствует в активном списке Portals"
    return synced


def default_next_run(rule: AutomationRule, *, offset_seconds: int = 0) -> datetime:
    settings = get_settings()
    interval = max(settings.min_check_interval_seconds, rule.check_interval_seconds or settings.default_check_interval_seconds)
    return datetime.now(UTC) + timedelta(seconds=interval + offset_seconds)
