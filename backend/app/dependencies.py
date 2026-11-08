from __future__ import annotations

import hmac
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.models import User, UserSession
from app.notifications.service import flush_outbox
from app.security import token_fingerprint

SESSION_COOKIE = "portals_session"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        await flush_outbox(session)


@dataclass(slots=True)
class AuthContext:
    user: User
    session: UserSession


def as_uuid(value: object, detail: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from None


def client_ip(request: Request) -> str | None:
    settings = get_settings()
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()[:64]
    return request.client.host[:64] if request.client else None


def client_user_agent(request: Request) -> str | None:
    value = request.headers.get("user-agent")
    return value[:255] if value else None


def _unauthorized(detail: str = "Требуется авторизация") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Session"},
    )


def session_is_expired(row: UserSession, now: datetime | None = None) -> bool:
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires < (now or datetime.now(UTC))


async def resolve_session(request: Request, session: AsyncSession) -> AuthContext | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    row = (
        await session.execute(
            select(UserSession).where(UserSession.token_hash == token_fingerprint(token))
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None or session_is_expired(row):
        return None
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    return AuthContext(user=user, session=row)


async def current_auth(request: Request, session: AsyncSession = Depends(get_db)) -> AuthContext:
    context = await resolve_session(request, session)
    if context is None:
        raise _unauthorized()
    return context


async def require_csrf(
    request: Request,
    context: AuthContext = Depends(current_auth),
    x_csrf_token: str | None = Header(default=None, alias=CSRF_HEADER),
) -> AuthContext:
    if request.method in SAFE_METHODS:
        return context
    if not x_csrf_token or not hmac.compare_digest(x_csrf_token, context.session.csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недействительный или отсутствующий CSRF-токен",
        )
    return context


async def require_admin(context: AuthContext = Depends(require_csrf)) -> AuthContext:
    if not context.user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Требуются права администратора",
        )
    return context
