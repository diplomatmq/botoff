from __future__ import annotations

import asyncio
import contextlib
import math
import random
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import ApiRequestState

_T = TypeVar("_T")
_LOCK_RETRY_ATTEMPTS = 4
_LOCK_RETRY_BASE_SECONDS = 0.05
_LOCK_RETRY_MAX_SECONDS = 0.5
_CREDENTIAL_LOCKS: defaultdict[object, asyncio.Lock] = defaultdict(asyncio.Lock)


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class RateLimiter:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        safety_margin: float = 0.05,
        sleep: Callable[[float], object] = asyncio.sleep,
    ) -> None:
        self._session_factory = session_factory
        self._safety_margin = max(0.0, min(0.5, safety_margin))
        self._sleep = sleep

    @staticmethod
    def _is_lock_error(error: OperationalError) -> bool:
        message = str(error).lower()
        return "database is locked" in message or "database table is locked" in message

    async def _run_write(
        self,
        credential_id,
        operation: Callable[[], Awaitable[_T]],
    ) -> _T:
        async with _CREDENTIAL_LOCKS[credential_id]:
            for attempt in range(_LOCK_RETRY_ATTEMPTS):
                try:
                    return await operation()
                except OperationalError as error:
                    if not self._is_lock_error(error) or attempt == _LOCK_RETRY_ATTEMPTS - 1:
                        raise
                    backoff = min(
                        _LOCK_RETRY_MAX_SECONDS,
                        _LOCK_RETRY_BASE_SECONDS * (2**attempt),
                    )
                    await self._sleep(random.uniform(0.5 * backoff, 1.5 * backoff))
        raise RuntimeError("unreachable")

    def _effective_limit(self, limit_per_second: int) -> int:
        limit_per_second = max(1, int(limit_per_second))
        scaled = math.floor(limit_per_second * (1.0 - self._safety_margin))
        return max(1, scaled)

    async def _locked_state(self, session: AsyncSession, credential_id) -> ApiRequestState:
        state = (
            await session.execute(
                select(ApiRequestState).where(ApiRequestState.credential_id == credential_id).with_for_update()
            )
        ).scalar_one_or_none()
        if state is None:
            now = utcnow()
            state = ApiRequestState(
                credential_id=credential_id,
                window_started_at=now,
                window_count=0,
                limit_per_second=1,
            )
            try:
                async with session.begin_nested():
                    session.add(state)
                    await session.flush()
            except IntegrityError:
                state = (
                    await session.execute(
                        select(ApiRequestState)
                        .where(ApiRequestState.credential_id == credential_id)
                        .with_for_update()
                    )
                ).scalar_one()
        return state

    async def acquire(self, credential_id, limit_per_second: int) -> ApiRequestState:
        limit = self._effective_limit(limit_per_second)
        min_interval = 1.0 / limit
        while True:
            async def update_state() -> tuple[ApiRequestState | None, float]:
                wait_for = 0.0
                async with self._session_factory() as session:
                    async with session.begin():
                        state = await self._locked_state(session, credential_id)
                        now = utcnow()
                        state.limit_per_second = limit

                        blocked_until = as_utc(state.blocked_until)
                        if blocked_until is not None and blocked_until > now:
                            wait_for = max(wait_for, (blocked_until - now).total_seconds())

                        window_started_at = as_utc(state.window_started_at) or now
                        elapsed = (now - window_started_at).total_seconds()
                        if elapsed >= 1.0:
                            state.window_started_at = now
                            state.window_count = 0

                        if state.window_count >= limit:
                            remaining = 1.0 - (now - window_started_at).total_seconds()
                            wait_for = max(wait_for, max(0.01, remaining))

                        last_request_at = as_utc(state.last_request_at)
                        if last_request_at is not None:
                            since_last = (now - last_request_at).total_seconds()
                            if since_last < min_interval:
                                wait_for = max(wait_for, min_interval - since_last)

                        if wait_for <= 0.0:
                            state.window_count += 1
                            state.last_request_at = now
                            state.total_requests += 1
                            return state, 0.0
                return None, wait_for

            state, wait_for = await self._run_write(credential_id, update_state)
            if state is not None:
                return state

            await self._sleep(min(wait_for, 5.0) + 0.005)

    async def report_success(
        self,
        credential_id,
        *,
        remaining: int | None = None,
        limit: int | None = None,
    ) -> None:
        async def update_state() -> None:
            async with self._session_factory() as session:
                async with session.begin():
                    state = await self._locked_state(session, credential_id)
                    state.last_success_at = utcnow()
                    if remaining is not None:
                        state.remaining_hint = remaining
                    if limit is not None:
                        state.limit_hint = limit

        await self._run_write(credential_id, update_state)

    async def report_error(self, credential_id, message: str, *, rate_limited: bool = False) -> None:
        async def update_state() -> None:
            async with self._session_factory() as session:
                async with session.begin():
                    state = await self._locked_state(session, credential_id)
                    state.last_error_at = utcnow()
                    state.last_error_message = message[:500]
                    state.total_errors += 1
                    if rate_limited:
                        state.total_rate_limited += 1

        await self._run_write(credential_id, update_state)

    async def block_for(self, credential_id, seconds: float) -> None:
        async def update_state() -> None:
            async with self._session_factory() as session:
                async with session.begin():
                    state = await self._locked_state(session, credential_id)
                    until = utcnow() + timedelta(seconds=max(0.05, seconds))
                    blocked_until = as_utc(state.blocked_until)
                    if blocked_until is None or blocked_until < until:
                        state.blocked_until = until

        await self._run_write(credential_id, update_state)

    async def snapshot(self, credential_id) -> ApiRequestState | None:
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(ApiRequestState).where(ApiRequestState.credential_id == credential_id)
                )
            ).scalar_one_or_none()

    async def reset(self, credential_id) -> None:
        async def update_state() -> None:
            async with self._session_factory() as session:
                async with session.begin():
                    state = await self._locked_state(session, credential_id)
                    state.blocked_until = None

        await self._run_write(credential_id, update_state)


@contextlib.asynccontextmanager
async def null_rate_limiter():
    yield None
