from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio

from app.db import SessionLocal
from app.enums import OperationState
from app.models import OperationQueue, User
from app.services import operations_service


@pytest_asyncio.fixture
async def user_id(db):
    async with SessionLocal() as session:
        user = User(username="ops-user", password_hash="x")
        session.add(user)
        await session.commit()
        return user.id


async def test_enqueue_and_deduplicate(user_id):
    async with SessionLocal() as session:
        key = operations_service.make_dedupe_key("create", "collection-1", "1.5")
        first = await operations_service.enqueue(
            session,
            dedupe_key=key,
            operation_type="create_offer",
            user_id=user_id,
            payload={"amount": "1.5"},
        )
        second = await operations_service.enqueue(
            session,
            dedupe_key=key,
            operation_type="create_offer",
            user_id=user_id,
            payload={"amount": "1.5"},
        )
        await session.commit()
        assert first is not None
        assert second is None


async def test_claim_next_marks_running_with_lease(user_id):
    async with SessionLocal() as session:
        await operations_service.enqueue(
            session,
            dedupe_key=operations_service.make_dedupe_key("create", "c2"),
            operation_type="create_offer",
            user_id=user_id,
            payload={"amount": "2"},
        )
        await session.commit()

    async with SessionLocal() as session:
        operation = await operations_service.claim_next(session, worker_id="worker-a", lease_seconds=30)
        await session.commit()
        assert operation is not None
        assert operation.state == OperationState.RUNNING.value
        assert operation.attempts == 1
        assert operation.locked_by == "worker-a"
        assert operation.lease_expires_at is not None

    async with SessionLocal() as session:
        assert await operations_service.claim_next(session, worker_id="worker-b") is None


async def test_complete_and_stats(user_id):
    async with SessionLocal() as session:
        await operations_service.enqueue(
            session,
            dedupe_key=operations_service.make_dedupe_key("create", "c3"),
            operation_type="create_offer",
            user_id=user_id,
        )
        await session.commit()

    async with SessionLocal() as session:
        operation = await operations_service.claim_next(session, worker_id="w")
        await operations_service.complete(session, operation, result={"ok": True})
        await session.commit()
        assert operation.state == OperationState.DONE.value
        assert operation.locked_by is None

    async with SessionLocal() as session:
        stats = await operations_service.queue_stats(session)
        assert stats["done"] == 1


async def test_fail_schedules_retry_with_backoff(user_id):
    async with SessionLocal() as session:
        await operations_service.enqueue(
            session,
            dedupe_key=operations_service.make_dedupe_key("create", "c4"),
            operation_type="create_offer",
            user_id=user_id,
        )
        await session.commit()

    async with SessionLocal() as session:
        operation = await operations_service.claim_next(session, worker_id="w")
        await operations_service.fail(session, operation, error="boom", retryable=True)
        await session.commit()
        assert operation.state == OperationState.RETRY.value
        assert operation.last_error == "boom"
        assert operation.scheduled_at > datetime.now(UTC)


async def test_fail_after_max_attempts_becomes_failed(user_id):
    async with SessionLocal() as session:
        await operations_service.enqueue(
            session,
            dedupe_key=operations_service.make_dedupe_key("create", "c5"),
            operation_type="create_offer",
            user_id=user_id,
            max_attempts=1,
        )
        await session.commit()

    async with SessionLocal() as session:
        operation = await operations_service.claim_next(session, worker_id="w")
        await operations_service.fail(session, operation, error="boom", retryable=True)
        await session.commit()
        assert operation.state == OperationState.FAILED.value


async def test_recover_expired_leases_marks_verification(user_id):
    async with SessionLocal() as session:
        await operations_service.enqueue(
            session,
            dedupe_key=operations_service.make_dedupe_key("create", "c6"),
            operation_type="create_offer",
            user_id=user_id,
        )
        await session.commit()

    async with SessionLocal() as session:
        operation = await operations_service.claim_next(session, worker_id="w")
        operation.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
        await session.commit()

    async with SessionLocal() as session:
        recovered = await operations_service.recover_expired_leases(session)
        await session.commit()
        assert recovered == 1

    async with SessionLocal() as session:
        row = (await session.execute(_all_operations())).scalars().one()
        assert row.state == OperationState.RETRY.value
        assert row.requires_verification is True


def _all_operations():
    from sqlalchemy import select

    return select(OperationQueue)


async def test_retry_now_resets_failed_operation(user_id):
    async with SessionLocal() as session:
        await operations_service.enqueue(
            session,
            dedupe_key=operations_service.make_dedupe_key("create", "c7"),
            operation_type="create_offer",
            user_id=user_id,
            max_attempts=1,
        )
        await session.commit()

    async with SessionLocal() as session:
        operation = await operations_service.claim_next(session, worker_id="w")
        await operations_service.fail(session, operation, error="boom", retryable=False)
        assert operation.state == OperationState.FAILED.value
        await operations_service.retry_now(session, operation)
        await session.commit()
        assert operation.state == OperationState.RETRY.value
        assert operation.last_error is None
        assert operation.max_attempts > operation.attempts
