from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import AuthContext, as_uuid, get_db, require_csrf
from app.models import Notification
from app.notifications import service as notifications
from app.schemas import (
    MessageOut,
    NotificationOut,
    NotificationSettingsOut,
    NotificationSettingsUpdate,
)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def notification_out(row: Notification) -> NotificationOut:
    return NotificationOut(
        id=str(row.id),
        level=row.level,
        event=row.event,
        title=row.title,
        message=row.message,
        read_at=row.read_at,
        created_at=row.created_at,
    )


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> list[NotificationOut]:
    query = select(Notification).where(Notification.user_id == context.user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    query = query.order_by(Notification.created_at.desc()).limit(limit)
    rows = (await session.execute(query)).scalars().all()
    return [notification_out(row) for row in rows]


@router.post("/{notification_id}/read", response_model=MessageOut)
async def mark_read(
    notification_id: str,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> MessageOut:
    row = await session.get(Notification, as_uuid(notification_id, "Уведомление не найдено"))
    if row is None or row.user_id != context.user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Уведомление не найдено")
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
    return MessageOut(message="Уведомление прочитано")


@router.post("/read-all", response_model=MessageOut)
async def mark_all_read(
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> MessageOut:
    await session.execute(
        update(Notification)
        .where(Notification.user_id == context.user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    return MessageOut(message="Все уведомления прочитаны")


@router.get("/settings", response_model=NotificationSettingsOut)
async def get_notification_settings(
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> NotificationSettingsOut:
    row = await notifications.get_or_create_settings(session, context.user.id)
    return NotificationSettingsOut(
        in_app_enabled=row.in_app_enabled,
        telegram_enabled=row.telegram_enabled,
        telegram_chat_id=row.telegram_chat_id,
        events=row.events or {},
        min_interval_seconds=row.min_interval_seconds,
        max_per_hour=row.max_per_hour,
    )


@router.put("/settings", response_model=NotificationSettingsOut)
async def update_notification_settings(
    payload: NotificationSettingsUpdate,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> NotificationSettingsOut:
    row = await notifications.get_or_create_settings(session, context.user.id)
    if payload.in_app_enabled is not None:
        row.in_app_enabled = payload.in_app_enabled
    if payload.telegram_enabled is not None:
        row.telegram_enabled = payload.telegram_enabled
    if payload.telegram_chat_id is not None:
        row.telegram_chat_id = payload.telegram_chat_id or None
    if payload.events is not None:
        merged = dict(row.events or {})
        merged.update(payload.events)
        row.events = merged
    if payload.min_interval_seconds is not None:
        row.min_interval_seconds = payload.min_interval_seconds
    if payload.max_per_hour is not None:
        row.max_per_hour = payload.max_per_hour
    await session.flush()
    return NotificationSettingsOut(
        in_app_enabled=row.in_app_enabled,
        telegram_enabled=row.telegram_enabled,
        telegram_chat_id=row.telegram_chat_id,
        events=row.events or {},
        min_interval_seconds=row.min_interval_seconds,
        max_per_hour=row.max_per_hour,
    )
