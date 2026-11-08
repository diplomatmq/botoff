from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import AuthContext, as_uuid, get_db, require_admin
from app.enums import AuditAction
from app.models import NotificationSettings, User, UserSession
from app.notifications.service import get_or_create_settings
from app.schemas import AdminUserCreate, AdminUserOut, AdminUserUpdate, MessageOut
from app.security import hash_password
from app.services import audit

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def _settings_for(session: AsyncSession, user_id) -> NotificationSettings:
    return await get_or_create_settings(session, user_id)


async def _user_out(session: AsyncSession, user: User) -> AdminUserOut:
    settings = await _settings_for(session, user.id)
    return AdminUserOut(
        id=str(user.id),
        username=user.username,
        is_admin=user.is_admin,
        last_login_at=user.last_login_at,
        is_active=user.is_active,
        telegram_enabled=settings.telegram_enabled,
        telegram_chat_id=settings.telegram_chat_id,
    )


@router.get("/users", response_model=list[AdminUserOut])
async def list_users(
    _: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db),
) -> list[AdminUserOut]:
    users = (await session.execute(select(User).order_by(User.username))).scalars().all()
    return [await _user_out(session, user) for user in users]


@router.post("/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: AdminUserCreate,
    context: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db),
) -> AdminUserOut:
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Логин не может быть пустым")
    existing = (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Пользователь с таким логином уже существует")

    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        is_admin=payload.is_admin,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    settings = NotificationSettings(
        user_id=user.id,
        telegram_enabled=payload.telegram_enabled,
        telegram_chat_id=payload.telegram_chat_id.strip() if payload.telegram_chat_id else None,
    )
    session.add(settings)
    await audit.record(
        session,
        action=AuditAction.SETTINGS_UPDATED.value,
        message=f"Создан пользователь: {username}",
        actor=context.user.username,
        user_id=context.user.id,
        details={"created_user_id": str(user.id)},
    )
    return await _user_out(session, user)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: str,
    payload: AdminUserUpdate,
    context: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db),
) -> AdminUserOut:
    user = await session.get(User, as_uuid(user_id, "Пользователь не найден"))
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.id == context.user.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="Нельзя отключить текущую учётную запись")
    if user.id == context.user.id and payload.is_admin is False:
        raise HTTPException(status_code=400, detail="Нельзя снять права текущего администратора")

    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        sessions = (
            await session.execute(select(UserSession).where(UserSession.user_id == user.id))
        ).scalars().all()
        for row in sessions:
            row.revoked_at = datetime.now(UTC)
    if payload.is_admin is not None:
        user.is_admin = payload.is_admin
    if payload.is_active is not None:
        user.is_active = payload.is_active
        if not payload.is_active:
            sessions = (
                await session.execute(select(UserSession).where(UserSession.user_id == user.id))
            ).scalars().all()
            for row in sessions:
                row.revoked_at = datetime.now(UTC)

    settings = await _settings_for(session, user.id)
    if payload.telegram_chat_id is not None:
        settings.telegram_chat_id = payload.telegram_chat_id.strip() or None
    if payload.telegram_enabled is not None:
        settings.telegram_enabled = payload.telegram_enabled
    await audit.record(
        session,
        action=AuditAction.SETTINGS_UPDATED.value,
        message=f"Изменён пользователь: {user.username}",
        actor=context.user.username,
        user_id=context.user.id,
        details={"updated_user_id": str(user.id)},
    )
    return await _user_out(session, user)


@router.delete("/users/{user_id}", response_model=MessageOut)
async def deactivate_user(
    user_id: str,
    context: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db),
) -> MessageOut:
    user = await session.get(User, as_uuid(user_id, "Пользователь не найден"))
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.id == context.user.id:
        raise HTTPException(status_code=400, detail="Нельзя отключить текущую учётную запись")
    user.is_active = False
    sessions = (
        await session.execute(select(UserSession).where(UserSession.user_id == user.id))
    ).scalars().all()
    for row in sessions:
        row.revoked_at = datetime.now(UTC)
    return MessageOut(message="Пользователь отключён")
