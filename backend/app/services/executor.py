from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import OfferStatus, OperationType
from app.models import AccountBudgetState, ApiCredential, AutomationRule, ManagedOffer, OperationQueue
from app.money import money_str, to_decimal
from app.portals.client import PortalsGateway
from app.portals.errors import (
    PortalsAuthError,
    PortalsError,
    PortalsNetworkError,
    PortalsNotFoundError,
    PortalsRateLimited,
    PortalsServerError,
    PortalsUnavailableError,
    is_trait_unavailable,
)
from app.services.offers_service import offer_entries, sender_matches
from app.services import settings_service

logger = logging.getLogger("portals.executor")


@dataclass(slots=True)
class ExecutionOutcome:
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    retryable: bool = False
    requires_verification: bool = False
    status_code: int | None = None
    response: dict[str, Any] | None = None
    duration_ms: int | None = None
    audit: list[dict[str, Any]] = field(default_factory=list)


def _network_outcome(exc: Exception, started: float) -> ExecutionOutcome:
    return ExecutionOutcome(
        ok=False,
        error=str(exc),
        retryable=True,
        requires_verification=True,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _error_outcome(exc: PortalsError, started: float) -> ExecutionOutcome:
    duration_ms = int((time.perf_counter() - started) * 1000)
    if isinstance(exc, PortalsRateLimited):
        return ExecutionOutcome(
            ok=False, error=str(exc), retryable=True, status_code=429, duration_ms=duration_ms
        )
    if isinstance(exc, (PortalsServerError, PortalsUnavailableError)):
        return ExecutionOutcome(
            ok=False, error=str(exc), retryable=True, status_code=exc.status, duration_ms=duration_ms
        )
    if isinstance(exc, PortalsAuthError):
        return ExecutionOutcome(
            ok=False,
            error=str(exc),
            retryable=False,
            status_code=exc.status,
            response={"code": exc.code},
            duration_ms=duration_ms,
        )
    if isinstance(exc, PortalsNotFoundError):
        return ExecutionOutcome(
            ok=False, error=str(exc), retryable=False, status_code=404, duration_ms=duration_ms
        )
    code = "ATTRIBUTE_OFFERS_UNAVAILABLE" if is_trait_unavailable(exc) else exc.code
    return ExecutionOutcome(
        ok=False,
        error=str(exc),
        retryable=False,
        status_code=exc.status,
        response={"code": code} if code else None,
        duration_ms=duration_ms,
    )


async def execute(
    session: AsyncSession,
    operation: OperationQueue,
    gateway: PortalsGateway,
    credential: ApiCredential,
) -> ExecutionOutcome:
    started = time.perf_counter()
    try:
        if (
            operation.operation_type == OperationType.CREATE_OFFER.value
            and (operation.payload or {}).get("source") == "smart_trader"
            and not await settings_service.get_setting(session, "smart_trader_enabled", False)
        ):
            return ExecutionOutcome(
                ok=True,
                result={"skipped": True, "reason": "Smart Trader отключён пользователем"},
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        if operation.operation_type == OperationType.CREATE_OFFER.value:
            return await _execute_create(session, operation, gateway, credential, started)
        if operation.operation_type == OperationType.UPDATE_OFFER.value:
            return await _execute_update(session, operation, gateway, started)
        if operation.operation_type == OperationType.CANCEL_OFFER.value:
            return await _execute_cancel(session, operation, gateway, started)
        if operation.operation_type == OperationType.SYNC_OFFER.value:
            return await _execute_sync(session, operation, gateway, credential, started)
        if operation.operation_type == OperationType.ACCEPT_OFFER.value:
            return await _execute_accept(operation, gateway, started)
        return ExecutionOutcome(ok=False, error=f"Неизвестный тип операции: {operation.operation_type}")
    except PortalsNetworkError as exc:
        return _network_outcome(exc, started)
    except PortalsError as exc:
        return _error_outcome(exc, started)


async def _find_managed_offer(session: AsyncSession, offer_row_id) -> ManagedOffer | None:
    if offer_row_id is None:
        return None
    return await session.get(ManagedOffer, offer_row_id)


async def _load_rule(session: AsyncSession, rule_id) -> AutomationRule | None:
    if rule_id is None:
        return None
    return await session.get(AutomationRule, rule_id)


async def _execute_create(
    session: AsyncSession,
    operation: OperationQueue,
    gateway: PortalsGateway,
    credential: ApiCredential,
    started: float,
) -> ExecutionOutcome:
    payload = operation.payload or {}
    collection_id = payload["collection_id"]
    amount = to_decimal(payload["amount"])
    if amount is None:
        return ExecutionOutcome(ok=False, error="Некорректная цена оффера")
    attributes = payload.get("attributes") or None
    max_nfts = int(payload.get("max_nfts") or 1)
    expiration_days = payload.get("expiration_days")

    if payload.get("verify_before_retry"):
        found = await _find_own_offer(session, gateway, payload, credential)
        if found is not None:
            await _persist_created_offer(session, operation, credential, found)
            return ExecutionOutcome(
                ok=True,
                result={"adopted_offer_id": found.get("id"), "amount": found.get("amount")},
                duration_ms=int((time.perf_counter() - started) * 1000),
                audit=[{"action": "offer_created", "message": "Создание оффера подтверждено после тайм-аута"}],
            )

    existing = await _find_existing_managed_offer(session, operation, amount)
    if existing is not None:
        return ExecutionOutcome(
            ok=True,
            result={"skipped": True, "reason": "Оффер с такими параметрами уже существует"},
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    try:
        response = await gateway.create_offer(
            collection_id=collection_id,
            amount=money_str(amount),
            max_nfts=max_nfts,
            attributes=attributes,
            expiration_days=expiration_days,
        )
    except (PortalsNetworkError, PortalsServerError):
        raise
    except PortalsError as exc:
        return _error_outcome(exc, started)

    created = response or {}
    await _persist_created_offer(session, operation, credential, created)
    return ExecutionOutcome(
        ok=True,
        result={"offer_id": created.get("id"), "amount": created.get("amount")},
        status_code=201,
        response={"id": created.get("id")},
        duration_ms=int((time.perf_counter() - started) * 1000),
        audit=[
            {
                "action": "offer_created",
                "message": f"Создан оффер {created.get('id')} на {created.get('amount')} GRAM",
            }
        ],
    )


async def _find_existing_managed_offer(
    session: AsyncSession, operation: OperationQueue, amount
) -> ManagedOffer | None:
    payload = operation.payload or {}
    if not payload.get("scope_signature"):
        return None
    result = await session.execute(
        select(ManagedOffer).where(
            ManagedOffer.rule_id == operation.rule_id,
            ManagedOffer.status == OfferStatus.PENDING.value,
            ManagedOffer.collection_id == payload.get("collection_id"),
        )
    )
    for row in result.scalars().all():
        if (row.amount or 0) == amount and (row.raw or {}).get("scope_signature") == payload.get("scope_signature"):
            return row
    return None


async def _find_own_offer(
    session: AsyncSession,
    gateway: PortalsGateway,
    payload: dict[str, Any],
    credential: ApiCredential,
) -> dict[str, Any] | None:
    scope_kind = payload.get("scope_kind") or ("trait" if payload.get("attributes") else "broad")
    try:
        raw = await gateway.offers_all(payload["collection_id"], scope=scope_kind, limit=10)
    except PortalsError:
        return None
    offers: list[dict[str, Any]] = []
    for entry in offer_entries(raw):
        offers.extend(entry.get("offers") or [])
    target_amount = to_decimal(payload.get("amount"))
    for offer in offers:
        if not sender_matches(offer.get("sender_id"), credential.sender_id):
            continue
        if to_decimal(offer.get("amount")) == target_amount:
            return offer
    return None


async def _persist_created_offer(
    session: AsyncSession,
    operation: OperationQueue,
    credential: ApiCredential,
    created: dict[str, Any],
) -> ManagedOffer:
    payload = operation.payload or {}
    external_id = str(created.get("id"))
    existing = (
        await session.execute(
            select(ManagedOffer).where(ManagedOffer.external_offer_id == external_id)
        )
    ).scalar_one_or_none()

    if credential.sender_id is None and created.get("sender_id") is not None:
        credential.sender_id = int(created["sender_id"])

    if existing is not None:
        return existing

    scope = created.get("scope") or {}
    if not (scope.get("models") or scope.get("backdrops") or scope.get("symbols")):
        scope = {
            "models": payload.get("models") or [],
            "backdrops": payload.get("backdrops") or [],
            "symbols": payload.get("symbols") or [],
        }

    row = ManagedOffer(
        user_id=operation.user_id,
        rule_id=operation.rule_id,
        credential_id=credential.id,
        external_offer_id=external_id,
        collection_id=str(created.get("collection_id") or payload.get("collection_id")),
        scope=scope,
        scope_kind=payload.get("scope_kind") or "broad",
        amount=to_decimal(created.get("amount"), to_decimal(payload.get("amount"))) or to_decimal(payload.get("amount")),
        max_amount=to_decimal(payload.get("cap")) if payload.get("cap") else None,
        max_nfts=int(created.get("max_nfts") or payload.get("max_nfts") or 1),
        current_nfts=int(created.get("current_nfts") or 0),
        expiration_days=payload.get("expiration_days"),
        status=str(created.get("status") or "pending"),
        position_status="UNKNOWN",
        last_action="create",
        last_action_at=datetime.now(UTC),
        raw={
            **created,
            "scope_signature": payload.get("scope_signature"),
            "source": payload.get("source"),
            "rebid_count": payload.get("rebid_count", 0),
        },
    )
    session.add(row)
    await session.flush()
    operation.offer_id = row.id
    return row


async def _execute_update(
    session: AsyncSession,
    operation: OperationQueue,
    gateway: PortalsGateway,
    started: float,
) -> ExecutionOutcome:
    payload = operation.payload or {}
    row = await _find_managed_offer(session, operation.offer_id or payload.get("offer_row_id"))
    if row is None:
        return ExecutionOutcome(ok=False, error="Оффер не найден в локальной базе")
    if row.status == OfferStatus.CANCELED.value:
        return ExecutionOutcome(ok=False, error="Оффер отменён, обновление невозможно")

    amount = to_decimal(payload.get("amount"))
    if amount is None:
        return ExecutionOutcome(ok=False, error="Некорректная цена обновления")

    item: dict[str, Any] = {"id": row.external_offer_id, "amount": money_str(amount)}
    if payload.get("max_nfts") is not None:
        item["max_nfts"] = int(payload["max_nfts"])
    if payload.get("expiration_days") is not None:
        item["expiration_days"] = int(payload["expiration_days"])

    try:
        response = await gateway.bulk_update_offers([item])
    except (PortalsNetworkError, PortalsServerError):
        raise
    except PortalsError as exc:
        return _error_outcome(exc, started)

    updated = (response or {}).get("updated") or []
    failed = (response or {}).get("failed") or []
    duration_ms = int((time.perf_counter() - started) * 1000)

    updated_ids = {
        str(item.get("id") if isinstance(item, dict) else item)
        for item in updated
    }
    if str(row.external_offer_id) in updated_ids:
        previous = row.amount
        row.amount = amount
        if payload.get("max_nfts") is not None:
            row.max_nfts = int(payload["max_nfts"])
        row.last_action = "update"
        row.last_action_at = datetime.now(UTC)
        row.last_error = None
        return ExecutionOutcome(
            ok=True,
            result={"offer_id": row.external_offer_id, "from": money_str(previous), "to": money_str(amount)},
            status_code=200,
            duration_ms=duration_ms,
            audit=[
                {
                    "action": "offer_updated",
                    "message": f"Оффер {row.external_offer_id}: цена {money_str(previous)} → {money_str(amount)} GRAM",
                }
            ],
        )

    reason = "; ".join(str(item.get("reason")) for item in failed) or "Оффер не обновлён"
    row.last_error = reason[:500]
    return ExecutionOutcome(
        ok=False,
        error=reason,
        retryable=False,
        status_code=200,
        response={"updated": updated, "failed": failed},
        duration_ms=duration_ms,
    )


async def _execute_cancel(
    session: AsyncSession,
    operation: OperationQueue,
    gateway: PortalsGateway,
    started: float,
) -> ExecutionOutcome:
    payload = operation.payload or {}
    row = await _find_managed_offer(session, operation.offer_id or payload.get("offer_row_id"))
    external_id = str(payload.get("external_offer_id") or (row.external_offer_id if row else ""))

    if payload.get("verify_before_retry"):
        still_there = await _offer_present(gateway, payload, external_id)
        if still_there is False:
            if row is not None:
                row.status = OfferStatus.CANCELED.value
                row.last_action = "cancel"
                row.last_action_at = datetime.now(UTC)
            return ExecutionOutcome(
                ok=True,
                result={"offer_id": external_id, "confirmed_by_verification": True},
                duration_ms=int((time.perf_counter() - started) * 1000),
                audit=[{"action": "offer_cancelled", "message": f"Отмена оффера {external_id} подтверждена"}],
            )

    try:
        await gateway.cancel_offer(external_id)
    except PortalsNotFoundError:
        if row is not None:
            row.status = OfferStatus.CANCELED.value
        await _refresh_budget_after_cancel(session, gateway, operation.user_id)
        return ExecutionOutcome(
            ok=True,
            result={"offer_id": external_id, "already_absent": True},
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except (PortalsNetworkError, PortalsServerError):
        raise
    except PortalsError as exc:
        return _error_outcome(exc, started)

    if row is not None:
        row.status = OfferStatus.CANCELED.value
        row.last_action = "cancel"
        row.last_action_at = datetime.now(UTC)
        row.position_status = "UNKNOWN"
    await _refresh_budget_after_cancel(session, gateway, operation.user_id)
    return ExecutionOutcome(
        ok=True,
        result={"offer_id": external_id},
        status_code=204,
        duration_ms=int((time.perf_counter() - started) * 1000),
        audit=[{"action": "offer_cancelled", "message": f"Оффер {external_id} отменён"}],
    )


async def _refresh_budget_after_cancel(
    session: AsyncSession,
    gateway: PortalsGateway,
    user_id,
) -> None:
    try:
        wallet = await gateway.wallet()
    except PortalsError as exc:
        logger.warning("wallet refresh after offer cancellation failed: %s", exc)
        return
    if not isinstance(wallet, dict):
        logger.warning("wallet refresh after offer cancellation returned invalid payload")
        return

    state = await session.get(AccountBudgetState, user_id)
    if state is None:
        state = AccountBudgetState(user_id=user_id)
        session.add(state)
    state.balance = to_decimal(wallet.get("balance"))
    state.frozen_funds = to_decimal(wallet.get("frozen_funds"))
    state.available = state.balance
    state.source = "api"
    state.updated_at = datetime.now(UTC)


async def _offer_present(gateway: PortalsGateway, payload: dict[str, Any], external_id: str) -> bool | None:
    scope_kind = payload.get("scope_kind") or "broad"
    try:
        raw = await gateway.offers_all(payload["collection_id"], scope=scope_kind, limit=10)
    except PortalsError:
        return None
    for entry in offer_entries(raw):
        for offer in entry.get("offers") or []:
            if str(offer.get("id")) == external_id:
                return True
    return False


async def _execute_sync(
    session: AsyncSession,
    operation: OperationQueue,
    gateway: PortalsGateway,
    credential: ApiCredential,
    started: float,
) -> ExecutionOutcome:
    payload = operation.payload or {}
    raw = await gateway.offers_all(payload["collection_id"], scope=payload.get("scope_kind"), limit=10)
    return ExecutionOutcome(
        ok=True,
        result={"collection_id": payload.get("collection_id"), "entries": len(raw or [])},
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


async def _execute_accept(
    operation: OperationQueue,
    gateway: PortalsGateway,
    started: float,
) -> ExecutionOutcome:
    payload = operation.payload or {}
    response = await gateway.accept_offer(str(payload["offer_id"]))
    return ExecutionOutcome(
        ok=True,
        result=response or {},
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
