from __future__ import annotations

import asyncio
import logging
import socket
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.enums import AutomationMode, CredentialStatus, OperationType, RuleState
from app.models import (
    AccountBudgetState,
    ApiCredential,
    AutomationRule,
    ManagedOffer,
    OperationQueue,
    User,
)
from app.notifications.service import flush_outbox
from app.portals.errors import PortalsAuthError, PortalsError, PortalsRateLimited
from app.portals.rate_limiter import as_utc
from app.runtime import build_gateway
from app.services import audit, operations_service, settings_service
from app.services.executor import execute
from app.services.offers_service import (
    account_balance,
    default_next_run,
    recover_owned_purchase_from_payload,
)
from app.services.rule_cycle import run_rule_cycle
from app.services.smart_trader import run as run_smart_trader

logger = logging.getLogger("portals.worker")

BUDGET_TTL_SECONDS = 60
REQUESTS_PER_CYCLE = 2.0


class Worker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        settings: Settings | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._stop = asyncio.Event()
        self._last_recovery = 0.0
        self._last_smart_trader = 0.0
        self._last_owned_recovery = 0.0
        self.stats = {
            "started_at": datetime.now(UTC).isoformat(),
            "cycles": 0,
            "operations_executed": 0,
            "rules_checked": 0,
            "errors": 0,
            "last_tick_at": None,
        }

    async def stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        logger.info("worker %s started", self.worker_id)
        while not self._stop.is_set():
            started = time.perf_counter()
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                self.stats["errors"] += 1
                logger.exception("worker tick failed")
            self.stats["cycles"] += 1
            self.stats["last_tick_at"] = datetime.now(UTC).isoformat()
            elapsed = time.perf_counter() - started
            delay = max(0.5, self.settings.worker_poll_interval_seconds - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                continue
        logger.info("worker %s stopped", self.worker_id)

    async def tick(self) -> None:
        if time.time() - self._last_recovery > 30:
            self._last_recovery = time.time()
            async with self.session_factory() as session:
                async with session.begin():
                    recovered = await operations_service.recover_expired_leases(session)
            if recovered:
                logger.warning("recovered %d interrupted operations", recovered)

        await self._drain_operations()
        await self._refresh_budgets()
        if time.time() - self._last_smart_trader >= 60:
            self._last_smart_trader = time.time()
            await self._process_smart_trader()
        await self._process_rules()
        if time.time() - self._last_owned_recovery >= 60:
            self._last_owned_recovery = time.time()
            await self._recover_owned_purchases()
        await self._publish_throughput()

    async def _recover_owned_purchases(self) -> None:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(ManagedOffer.id, ManagedOffer.collection_id, ManagedOffer.credential_id)
                    .where(
                        ManagedOffer.status.in_(("pending", "unknown")),
                        ManagedOffer.current_nfts < ManagedOffer.max_nfts,
                        ManagedOffer.credential_id.is_not(None),
                    )
                )
            ).all()
            await session.rollback()

        for row_id, collection_id, credential_id in rows:
            async with self.session_factory() as session:
                credential = await session.get(ApiCredential, credential_id)
                if credential is None or credential.status != CredentialStatus.ACTIVE.value:
                    await session.rollback()
                    continue
                gateway = build_gateway(credential)
                await session.rollback()
            try:
                payload = await gateway.owned_nfts(str(collection_id))
            except PortalsError as exc:
                logger.debug("owned inventory lookup failed for %s: %s", collection_id, exc)
                continue
            async with self.session_factory() as session:
                row = await session.get(ManagedOffer, row_id)
                if row is None or row.status not in ("pending", "unknown"):
                    await session.rollback()
                    continue
                if await recover_owned_purchase_from_payload(session, row, payload):
                    await session.commit()
                else:
                    await session.rollback()

    async def _drain_operations(self, budget: int = 8) -> None:
        for _ in range(budget):
            processed = await self._process_one_operation()
            if not processed:
                return

    async def _process_one_operation(self) -> bool:
        async with self.session_factory() as session:
            async with session.begin():
                operation = await operations_service.claim_next(
                    session, worker_id=self.worker_id, lease_seconds=self.settings.worker_lease_seconds
                )
            if operation is None:
                return False

            operation_id = operation.id

        async with self.session_factory() as session:
            operation = await session.get(OperationQueue, operation_id)
            if operation is None:
                return True
            credential = None
            if operation.payload and operation.payload.get("credential_id"):
                credential = await session.get(ApiCredential, uuid.UUID(operation.payload["credential_id"]))
            if credential is None and operation.user_id is not None:
                credential = (
                    await session.execute(
                        select(ApiCredential)
                        .where(ApiCredential.user_id == operation.user_id, ApiCredential.status != "disabled")
                        .order_by(ApiCredential.is_primary.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()

            if credential is None:
                await operations_service.fail(
                    session, operation, error="Нет подключённого API-ключа", retryable=False
                )
                await session.commit()
                return True

            gateway = build_gateway(credential)
            outcome = await execute(session, operation, gateway, credential)

            if outcome.ok:
                await operations_service.complete(
                    session, operation, result=outcome.result, duration_ms=outcome.duration_ms
                )
                for entry in outcome.audit:
                    await audit.record(
                        session,
                        action=entry["action"],
                        message=entry["message"],
                        actor="worker",
                        user_id=operation.user_id,
                        entity_type="offer",
                        entity_id=operation.offer_id,
                        duration_ms=outcome.duration_ms,
                    )
                self.stats["operations_executed"] += 1
            else:
                retryable = outcome.retryable
                if outcome.requires_verification:
                    operation.payload = {**(operation.payload or {}), "verify_before_retry": True}
                await operations_service.fail(
                    session,
                    operation,
                    error=outcome.error or "Неизвестная ошибка операции",
                    retryable=retryable,
                    requires_verification=outcome.requires_verification,
                    status_code=outcome.status_code,
                    response=outcome.response,
                    duration_ms=outcome.duration_ms,
                )
                await audit.record(
                    session,
                    action="operation_failed",
                    message=f"Операция {operation.operation_type} не выполнена: {outcome.error}",
                    actor="worker",
                    user_id=operation.user_id,
                    entity_type="operation",
                    entity_id=operation.id,
                    level="error" if not retryable else "warning",
                    details={"response": outcome.response, "status_code": outcome.status_code},
                )
                await self._handle_operation_error(session, operation, outcome)

            await session.commit()
        return True

    async def _handle_operation_error(self, session: AsyncSession, operation: OperationQueue, outcome) -> None:
        payload = operation.payload or {}
        if (
            operation.operation_type == OperationType.UPDATE_OFFER.value
            and payload.get("source") == "smart_trader"
            and operation.offer_id is not None
            and not outcome.retryable
        ):
            row = await session.get(ManagedOffer, operation.offer_id)
            if row is not None and row.status == "pending":
                await operations_service.enqueue(
                    session,
                    dedupe_key=operations_service.make_dedupe_key("trader-cancel", row.id),
                    operation_type=OperationType.CANCEL_OFFER.value,
                    user_id=operation.user_id,
                    offer_id=row.id,
                    payload={
                        "offer_row_id": str(row.id),
                        "external_offer_id": row.external_offer_id,
                        "collection_id": row.collection_id,
                        "scope_kind": row.scope_kind,
                    },
                )

        if outcome.status_code in (401, 403) and outcome.response and outcome.response.get("code") in {
            "PARTNER_INVALID_KEY",
            "PARTNER_KEY_DISABLED",
            "PARTNER_SUBSCRIPTION_REQUIRED",
            "PARTNER_SUBSCRIPTION_EXPIRED",
        }:
            credential = (
                await session.execute(
                    select(ApiCredential).where(ApiCredential.user_id == operation.user_id).limit(1)
                )
            ).scalar_one_or_none()
            if credential is not None:
                credential.status = CredentialStatus.INVALID.value
                credential.last_checked_at = datetime.now(UTC)
                credential.last_check_ok = False
                credential.last_check_message = (outcome.error or "")[:500]

        if operation.rule_id is not None and outcome.response and outcome.response.get("code") == "ATTRIBUTE_OFFERS_UNAVAILABLE":
            rule = await session.get(AutomationRule, operation.rule_id)
            if rule is not None:
                rule.state = RuleState.PAUSED.value
                rule.enabled = False
                rule.last_error = "Офферы по атрибутам недоступны (403)"
            if credential := (
                await session.execute(
                    select(ApiCredential).where(ApiCredential.user_id == operation.user_id).limit(1)
                )
            ).scalar_one_or_none():
                logger.info("credential %s: trait offers unavailable", credential.id)

    async def _refresh_budgets(self) -> None:
        updates: list[tuple[uuid.UUID, Decimal | None, Decimal | None, uuid.UUID | None, str | None]] = []
        async with self.session_factory() as session:
            stale_before = datetime.now(UTC) - timedelta(seconds=BUDGET_TTL_SECONDS)
            users = (
                await session.execute(
                    select(User).where(User.is_active.is_(True))
                )
            ).scalars().all()

            for user in users:
                state = await session.get(AccountBudgetState, user.id)
                updated_at = as_utc(state.updated_at) if state is not None else None
                if updated_at is not None and updated_at > stale_before:
                    continue
                credential = (
                    await session.execute(
                        select(ApiCredential)
                        .where(
                            ApiCredential.user_id == user.id,
                            ApiCredential.status == CredentialStatus.ACTIVE.value,
                        )
                        .order_by(ApiCredential.is_primary.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if credential is None:
                    continue

                gateway = build_gateway(credential)
                try:
                    balance, frozen = await account_balance(session, gateway)
                except PortalsRateLimited:
                    break
                except PortalsAuthError as exc:
                    updates.append((user.id, None, None, credential.id, exc.message))
                    continue
                except PortalsError:
                    balance, frozen = None, None

                updates.append((user.id, balance, frozen, None, None))

        if not updates:
            return

        async with self.session_factory() as session:
            async with session.begin():
                now = datetime.now(UTC)
                for user_id, balance, frozen, invalid_credential_id, message in updates:
                    if invalid_credential_id is not None:
                        credential = await session.get(ApiCredential, invalid_credential_id)
                        if credential is not None:
                            credential.status = CredentialStatus.INVALID.value
                            credential.last_check_ok = False
                            credential.last_check_message = (message or "")[:500]
                            credential.last_checked_at = now
                        continue

                    state = await session.get(AccountBudgetState, user_id)
                    if state is None:
                        state = AccountBudgetState(user_id=user_id)
                        session.add(state)
                    if balance is None:
                        state.source = "unknown"
                        state.balance = None
                        state.frozen_funds = None
                        state.available = None
                    else:
                        state.source = "api"
                        state.balance = balance
                        state.frozen_funds = frozen
                        state.available = balance
                    state.updated_at = now

    async def _process_smart_trader(self) -> None:
        async with self.session_factory() as session:
            users = (await session.execute(select(User).where(User.is_active.is_(True)))).scalars().all()
            for user in users:
                # Each account keeps its own smart trader configuration.
                if not await settings_service.get_setting(
                    session, "smart_trader_enabled", False, user_id=user.id
                ):
                    continue
                credential = (
                    await session.execute(
                        select(ApiCredential)
                        .where(
                            ApiCredential.user_id == user.id,
                            ApiCredential.status == CredentialStatus.ACTIVE.value,
                        )
                        .order_by(ApiCredential.is_primary.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if credential is None:
                    continue
                try:
                    await run_smart_trader(
                        session,
                        user_id=user.id,
                        credential=credential,
                        gateway=build_gateway(credential),
                    )
                    await session.commit()
                except PortalsRateLimited:
                    await session.rollback()
                    break
                except PortalsError as exc:
                    await session.rollback()
                    logger.warning("smart trader cycle failed for user %s: %s", user.id, exc)

    async def _claim_rules(self, limit: int = 5) -> list[uuid.UUID]:
        async with self.session_factory() as session:
            async with session.begin():
                now = datetime.now(UTC)
                query = (
                    select(AutomationRule)
                    .where(
                        AutomationRule.enabled.is_(True),
                        AutomationRule.state.in_((RuleState.ACTIVE.value, RuleState.DRY_RUN.value)),
                        or_(AutomationRule.next_run_at.is_(None), AutomationRule.next_run_at <= now),
                        or_(
                            AutomationRule.lease_expires_at.is_(None),
                            AutomationRule.lease_expires_at < now,
                        ),
                    )
                    .order_by(AutomationRule.next_run_at.asc().nulls_first())
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
                rules = (await session.execute(query)).scalars().all()
                for rule in rules:
                    rule.locked_by = self.worker_id
                    rule.lease_expires_at = now + timedelta(seconds=self.settings.worker_lease_seconds)
                return [rule.id for rule in rules]

    async def _process_rules(self) -> None:
        rule_ids = await self._claim_rules()
        for rule_id in rule_ids:
            try:
                await self._process_rule(rule_id)
                self.stats["rules_checked"] += 1
            except Exception:  # noqa: BLE001
                self.stats["errors"] += 1
                logger.exception("rule %s cycle failed", rule_id)
                await self._release_rule(rule_id, error="Внутренняя ошибка worker")

    async def _process_rule(self, rule_id: uuid.UUID) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                rule = await session.get(AutomationRule, rule_id)
                if rule is None:
                    return

                mode = await settings_service.get_setting(
                    session, "mode", AutomationMode.DRY_RUN.value, user_id=rule.user_id
                )
                enabled = await settings_service.get_setting(
                    session, "automation_enabled", False, user_id=rule.user_id
                )
                emergency = await settings_service.get_setting(
                    session, "emergency_stop", False, user_id=rule.user_id
                )

                credential = None
                if rule.credential_id is not None:
                    credential = await session.get(ApiCredential, rule.credential_id)
                if credential is None or credential.status != CredentialStatus.ACTIVE.value:
                    credential = (
                        await session.execute(
                            select(ApiCredential)
                            .where(
                                ApiCredential.user_id == rule.user_id,
                                ApiCredential.status == CredentialStatus.ACTIVE.value,
                            )
                            .order_by(ApiCredential.is_primary.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()

                if credential is None:
                    rule.last_position_status = "UNKNOWN"
                    rule.last_error = "Нет подключённого API-ключа"
                    rule.last_decision = {
                        "action": "noop",
                        "status": "UNKNOWN",
                        "reason": "NO_CREDENTIAL",
                    }
                    rule.next_run_at = default_next_run(rule)
                    rule.locked_by = None
                    rule.lease_expires_at = None
                    return

                gateway = build_gateway(credential)

                if emergency or not enabled:
                    rule.last_position_status = "UNKNOWN"
                    rule.last_decision = {
                        "action": "noop",
                        "status": "UNKNOWN",
                        "reason": "EMERGENCY_STOP" if emergency else "AUTOMATION_DISABLED",
                    }
                    rule.next_run_at = default_next_run(rule)
                    rule.locked_by = None
                    rule.lease_expires_at = None
                    return

                budget = await session.get(AccountBudgetState, rule.user_id)
                available = budget.available if budget is not None and budget.source == "api" else None

            # Do not keep a write transaction open while Portals requests run.
            await run_rule_cycle(
                session,
                rule=rule,
                gateway=gateway,
                credential=credential,
                mode_live=mode == AutomationMode.LIVE.value and rule.state == RuleState.ACTIVE.value,
                automation_enabled=enabled,
                emergency_stop=emergency,
                available_balance=available,
            )
            rule.last_run_at = datetime.now(UTC)
            rule.locked_by = None
            rule.lease_expires_at = None
            await session.commit()
            await flush_outbox(session)

    async def _release_rule(self, rule_id: uuid.UUID, *, error: str | None = None) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                rule = await session.get(AutomationRule, rule_id)
                if rule is None:
                    return
                rule.locked_by = None
                rule.lease_expires_at = None
                if error:
                    rule.last_error = error
                    rule.next_run_at = default_next_run(rule)

    async def _publish_throughput(self) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                active_rules = (
                    await session.execute(
                        select(func.count())
                        .select_from(AutomationRule)
                        .where(
                            AutomationRule.enabled.is_(True),
                            AutomationRule.state.in_((RuleState.ACTIVE.value, RuleState.DRY_RUN.value)),
                        )
                    )
                ).scalar_one()

                credentials = (
                    await session.execute(
                        select(ApiCredential).where(ApiCredential.status == CredentialStatus.ACTIVE.value)
                    )
                ).scalars().all()
                rps = min([c.rate_limit_per_second or 1 for c in credentials] or [1])

                capacity_per_minute = (rps * 60.0) / REQUESTS_PER_CYCLE
                warn = active_rules > 0 and active_rules > capacity_per_minute
                await settings_service.set_setting(
                    session,
                    "throughput",
                    {
                        "active_rules": int(active_rules),
                        "requests_per_second": rps,
                        "capacity_per_minute": round(capacity_per_minute, 1),
                        "warning": warn,
                        "updated_at": datetime.now(UTC).isoformat(),
                    },
                )
