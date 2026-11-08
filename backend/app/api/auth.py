from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import (
    SESSION_COOKIE,
    AuthContext,
    client_ip,
    client_user_agent,
    current_auth,
    get_db,
    require_csrf,
)
from app.enums import AuditAction
from app.models import User, UserSession
from app.schemas import ChangePasswordRequest, LoginRequest, MessageOut, UserOut
from app.security import generate_token, hash_password, token_fingerprint, verify_password
from app.services import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_FAILED_LOGINS = 8
LOCK_MINUTES = 15


def user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        username=user.username,
        is_admin=user.is_admin,
        last_login_at=user.last_login_at,
    )


def _locked(user: User) -> bool:
    if user.locked_until is None:
        return False
    locked_until = user.locked_until
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)
    return locked_until > datetime.now(UTC)


def _set_session_cookie(response: Response, token: str, max_age: int) -> None:
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        domain=settings.cookie_domain,
        path="/",
    )


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> dict:
    settings = get_settings()
    user = (
        await session.execute(select(User).where(User.username == payload.username.strip()))
    ).scalar_one_or_none()

    if user is None or not user.is_active or _locked(user):
        await audit.record(
            session,
            action=AuditAction.LOGIN_FAILED.value,
            message=f"Неудачная попытка входа: {payload.username}",
            actor="anonymous",
            level="warning",
            details={"ip": client_ip(request)},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = datetime.now(UTC) + timedelta(minutes=LOCK_MINUTES)
            user.failed_login_count = 0
        await audit.record(
            session,
            action=AuditAction.LOGIN_FAILED.value,
            message=f"Неудачная попытка входа: {user.username}",
            actor="anonymous",
            level="warning",
            details={"ip": client_ip(request)},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(UTC)

    token = generate_token(32)
    csrf = generate_token(24)
    ttl_seconds = settings.session_ttl_hours * 3600
    row = UserSession(
        user_id=user.id,
        token_hash=token_fingerprint(token),
        csrf_token=csrf,
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        ip_address=client_ip(request),
        user_agent=client_user_agent(request),
    )
    session.add(row)
    await audit.record(
        session,
        action=AuditAction.LOGIN.value,
        message=f"Вход выполнен: {user.username}",
        actor=user.username,
        user_id=user.id,
        details={"ip": client_ip(request)},
    )
    await session.commit()

    _set_session_cookie(response, token, ttl_seconds)
    return {
        "user": user_out(user).model_dump(mode="json"),
        "csrf_token": csrf,
        "expires_at": row.expires_at.isoformat(),
    }


@router.post("/logout", response_model=MessageOut)
async def logout(
    response: Response,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> MessageOut:
    context.session.revoked_at = datetime.now(UTC)
    await audit.record(
        session,
        action=AuditAction.LOGOUT.value,
        message=f"Выход выполнен: {context.user.username}",
        actor=context.user.username,
        user_id=context.user.id,
    )
    response.delete_cookie(SESSION_COOKIE, path="/")
    return MessageOut(message="Сессия завершена")


@router.get("/me")
async def me(context: AuthContext = Depends(current_auth)) -> dict:
    return {
        "user": user_out(context.user).model_dump(mode="json"),
        "csrf_token": context.session.csrf_token,
        "expires_at": context.session.expires_at.isoformat(),
    }


@router.post("/password", response_model=MessageOut)
async def change_password(
    payload: ChangePasswordRequest,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> MessageOut:
    user = context.user
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Текущий пароль неверен")

    user.password_hash = hash_password(payload.new_password)
    sessions = (
        await session.execute(select(UserSession).where(UserSession.user_id == user.id))
    ).scalars().all()
    for row in sessions:
        if row.id != context.session.id:
            row.revoked_at = datetime.now(UTC)

    await audit.record(
        session,
        action=AuditAction.PASSWORD_CHANGED.value,
        message=f"Пароль изменён: {user.username}",
        actor=user.username,
        user_id=user.id,
    )
    return MessageOut(message="Пароль обновлён")
