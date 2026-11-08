from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import OperationState
from app.models import OperationAttempt, OperationQueue
from app.security import sanitize_payload

logger = logging.getLogger("portals.operations")

ACTIVE_STATES = (OperationState.PENDING.value, OperationState.RUNNING.value, OperationState.RETRY.value)


def make_dedupe_key(*parts: Any) -> str:
    raw = "|".join(str(part) for part in parts if part is not None)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"{raw.split('|')[0][:16]}:{digest}"


async def enqueue(
    session: AsyncSession,
    *,
    dedupe_key: str,
    operation_type: str,
    user_id=None,
    rule_id=None,
    offer_id=None,
    payload: dict[str, Any] | None = None,
    scheduled_at: datetime | None = None,
    max_attempts: int | None = None,
) -> OperationQueue | None:
    settings = get_settings()
    operation = OperationQueue(
        user_id=user_id,
        rule_id=rule_id,
        offer_id=offer_id,
        operation_type=operation_type,
        payload=payload or {},
        dedupe_key=dedupe_key[:128],
        state=OperationState.PENDING.value,
        max_attempts=max_attempts or settings.operation_max_attempts,
        scheduled_at=scheduled_at or datetime.now(UTC),
    )
    session.add(operation)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        logger.debug("operation with dedupe key %s already queued", dedupe_key)
        return None
    return operation


async def claim_next(session: AsyncSession, *, worker_id: str, lease_seconds: int | None = None) -> OperationQueue | None:
    settings = get_settings()
    lease = lease_seconds or settings.worker_lease_seconds
    now = datetime.now(UTC)
    query = (
        select(OperationQueue)
        .where(
            OperationQueue.state.in_((OperationState.PENDING.value, OperationState.RETRY.value)),
            OperationQueue.scheduled_at <= now,
        )
        .order_by(OperationQueue.scheduled_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    operation = (await session.execute(query)).scalar_one_or_none()
    if operation is None:
        return None
    operation.state = OperationState.RUNNING.value
    operation.attempts += 1
    operation.started_at = operation.started_at or now
    operation.locked_by = worker_id
    operation.lease_expires_at = now + timedelta(seconds=lease)
    await session.flush()

    session.add(
        OperationAttempt(
            operation_id=operation.id,
            attempt_no=operation.attempts,
            request_summary=sanitize_payload(operation.payload),
            outcome="started",
        )
    )
    await session.flush()
    return operation


async def complete(
    session: AsyncSession,
    operation: OperationQueue,
    *,
    result: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> None:
    operation.state = OperationState.DONE.value
    operation.finished_at = datetime.now(UTC)
    operation.locked_by = None
    operation.lease_expires_at = None
    operation.last_error = None
    operation.requires_verification = False
    operation.result = sanitize_payload(result)
    await _attach_attempt(session, operation, outcome="success", duration_ms=duration_ms, status_code=200)
    await session.flush()


async def fail(
    session: AsyncSession,
    operation: OperationQueue,
    *,
    error: str,
    retryable: bool,
    requires_verification: bool = False,
    status_code: int | None = None,
    response: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> None:
    now = datetime.now(UTC)
    operation.last_error = error[:1000]
    operation.requires_verification = requires_verification
    operation.locked_by = None
    operation.lease_expires_at = None

    if retryable and operation.attempts < operation.max_attempts:
        delay = min(2 ** operation.attempts, 60)
        operation.state = OperationState.RETRY.value
        operation.scheduled_at = now + timedelta(seconds=delay)
        outcome = "retry"
    else:
        operation.state = OperationState.FAILED.value
        operation.finished_at = now
        outcome = "failed"

    await _attach_attempt(
        session,
        operation,
        outcome=outcome,
        error=error,
        status_code=status_code,
        response=response,
        duration_ms=duration_ms,
    )
    await session.flush()


async def _attach_attempt(
    session: AsyncSession,
    operation: OperationQueue,
    *,
    outcome: str,
    error: str | None = None,
    status_code: int | None = None,
    response: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> None:
    result = await session.execute(
        select(OperationAttempt)
        .where(OperationAttempt.operation_id == operation.id)
        .order_by(OperationAttempt.attempt_no.desc())
        .limit(1)
    )
    attempt = result.scalar_one_or_none()
    if attempt is not None and attempt.outcome == "started" and attempt.attempt_no == operation.attempts:
        attempt.outcome = outcome
        attempt.error = error[:1000] if error else None
        attempt.response_status = status_code
        attempt.response_summary = sanitize_payload(response)
        attempt.duration_ms = duration_ms
    else:
        session.add(
            OperationAttempt(
                operation_id=operation.id,
                attempt_no=operation.attempts,
                outcome=outcome,
                error=error[:1000] if error else None,
                response_status=status_code,
                response_summary=sanitize_payload(response),
                duration_ms=duration_ms,
            )
        )


async def retry_now(session: AsyncSession, operation: OperationQueue) -> None:
    operation.state = OperationState.RETRY.value
    operation.scheduled_at = datetime.now(UTC)
    operation.finished_at = None
    operation.last_error = None
    operation.locked_by = None
    operation.lease_expires_at = None
    if operation.attempts >= operation.max_attempts:
        operation.max_attempts = operation.attempts + 1
    await session.flush()


async def recover_expired_leases(session: AsyncSession) -> int:
    now = datetime.now(UTC)
    query = (
        select(OperationQueue)
        .where(
            OperationQueue.state == OperationState.RUNNING.value,
            OperationQueue.lease_expires_at.is_not(None),
            OperationQueue.lease_expires_at < now,
        )
        .with_for_update(skip_locked=True)
    )
    recovered = 0
    for operation in (await session.execute(query)).scalars().all():
        operation.state = OperationState.RETRY.value
        operation.locked_by = None
        operation.lease_expires_at = None
        operation.scheduled_at = now
        operation.last_error = "Прерванная операция восстановлена после перезапуска"
        operation.requires_verification = True
        recovered += 1
    if recovered:
        await session.flush()
    return recovered


async def queue_stats(session: AsyncSession) -> dict[str, int]:
    result = await session.execute(
        select(OperationQueue.state, func.count()).group_by(OperationQueue.state)
    )
    stats = {"pending": 0, "running": 0, "retry": 0, "done": 0, "failed": 0, "dead": 0}
    for state, count in result.all():
        stats[state] = int(count)
    return stats


async def has_active_operation(session: AsyncSession, dedupe_key: str) -> bool:
    result = await session.execute(
        select(OperationQueue.id)
        .where(OperationQueue.dedupe_key == dedupe_key, OperationQueue.state.in_(ACTIVE_STATES))
        .limit(1)
    )
    return result.scalar_one_or_none() is not None
