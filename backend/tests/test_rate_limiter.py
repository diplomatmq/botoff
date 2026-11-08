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


async def test_reset_clears_block(credential_id):
    limiter = RateLimiter(SessionLocal, sleep=_noop)
    await limiter.block_for(credential_id, 60.0)
    await limiter.reset(credential_id)
    state = await limiter.snapshot(credential_id)
    assert state.blocked_until is None


async def _noop(seconds: float) -> None:
    return None
