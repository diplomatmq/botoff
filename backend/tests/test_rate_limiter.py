from __future__ import annotations

import asyncio

import pytest_asyncio

from app.db import SessionLocal
from app.models import ApiCredential, User
from app.portals.rate_limiter import RateLimiter


@pytest_asyncio.fixture
async def credential_id(db):
    async with SessionLocal() as session:
        user = User(username="rl-user", password_hash="x", is_admin=False)
        session.add(user)
        await session.flush()
        credential = ApiCredential(
            user_id=user.id,
            encrypted_token="cipher",
            token_hint="tok****en",
            rate_limit_per_second=1,
        )
        session.add(credential)
        await session.commit()
        return credential.id


async def test_rate_limiter_waits_between_requests(credential_id):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    limiter = RateLimiter(SessionLocal, sleep=fake_sleep)
    await limiter.acquire(credential_id, 1)
    await limiter.acquire(credential_id, 1)
    assert slept, "второй запрос обязан подождать соблюдения лимита"
    assert min(slept) > 0


async def test_rate_limiter_counts_requests(credential_id):
    limiter = RateLimiter(SessionLocal, sleep=_noop)
    await limiter.acquire(credential_id, 5)
    state = await limiter.snapshot(credential_id)
    assert state is not None
    assert state.total_requests == 1
    assert state.limit_per_second == 4


async def test_block_for_delays_next_request(credential_id):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    limiter = RateLimiter(SessionLocal, sleep=fake_sleep)
    await limiter.block_for(credential_id, 2.0)
    await limiter.acquire(credential_id, 1)
    assert sum(slept) >= 2.0


async def test_report_error_increments_counters(credential_id):
    limiter = RateLimiter(SessionLocal, sleep=_noop)
    await limiter.report_error(credential_id, "boom", rate_limited=True)
    state = await limiter.snapshot(credential_id)
    assert state.total_errors == 1
    assert state.total_rate_limited == 1
    assert state.last_error_message == "boom"


async def test_parallel_rules_share_rate_limiter_state(credential_id):
    limiters = [RateLimiter(SessionLocal, sleep=_noop) for _ in range(2)]

    await asyncio.gather(*(limiters[index % 2].acquire(credential_id, 100) for index in range(8)))

    state = await limiters[0].snapshot(credential_id)
    assert state is not None
    assert state.total_requests == 8


async def test_parallel_rate_limiter_writes_for_different_credentials(credential_id):
    from sqlalchemy import select

    async with SessionLocal() as session:
        original = await session.get(ApiCredential, credential_id)
        credential_ids = [credential_id]
        for index in range(7):
            credential = ApiCredential(
                user_id=original.user_id,
                encrypted_token=f"cipher-{index}",
                token_hint=f"tok****{index}",
                rate_limit_per_second=100,
            )
            session.add(credential)
            await session.flush()
            credential_ids.append(credential.id)
        await session.commit()

    limiters = [RateLimiter(SessionLocal, sleep=_noop) for _ in credential_ids]
    await asyncio.gather(
        *(limiter.acquire(cid, 100) for limiter, cid in zip(limiters, credential_ids))
    )

    async with SessionLocal() as session:
        states = (
            await session.execute(
                select(ApiCredential.id)
                .where(ApiCredential.id.in_(credential_ids))
            )
        ).scalars().all()
    assert len(states) == len(credential_ids)
    for limiter, cid in zip(limiters, credential_ids):
        state = await limiter.snapshot(cid)
        assert state is not None
        assert state.total_requests == 1


async def test_reset_clears_block(credential_id):
    limiter = RateLimiter(SessionLocal, sleep=_noop)
    await limiter.block_for(credential_id, 60.0)
    await limiter.reset(credential_id)
    state = await limiter.snapshot(credential_id)
    assert state.blocked_until is None


async def test_pending_worker_update_does_not_block_limiter(credential_id):
    """A pending worker mutation must not hold SQLite's single write lock.

    Regression: the worker mutates the operation payload right before calling Portals.
    With autoflush enabled the next SELECT flushed that UPDATE, so the worker held the
    write lock for the whole network call and the limiter failed on `BEGIN IMMEDIATE`
    with "database is locked" — which also took login down with a 500.
    """
    from sqlalchemy import select

    async with SessionLocal() as worker:
        credential = await worker.get(ApiCredential, credential_id)
        credential.token_hint = "changed-hint"
        # Mimics the executor: a SELECT happens between the mutation and the network call.
        await worker.execute(select(ApiCredential.id))
        assert credential in worker.dirty, "мутация воркера не должна сбрасываться в БД досрочно"

        limiter = RateLimiter(SessionLocal, sleep=_noop)
        await limiter.acquire(credential_id, 1)

    state = await limiter.snapshot(credential_id)
    assert state is not None
    assert state.total_requests == 1


async def _noop(seconds: float) -> None:
    return None
