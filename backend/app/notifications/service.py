from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Notification, NotificationSettings
from app.notifications.telegram import send_message

logger = logging.getLogger("portals.notifications")

OUTBOX_KEY = "telegram_outbox"


@dataclass(slots=True)
class TelegramMessage:
    chat_id: str
    text: str


DEFAULT_EVENTS = {
    "offer_filled": True,
    "offer_created": False,
    "offer_updated": False,
    "offer_cancelled": False,
    "outbid": False,
    "limit_reached": False,
    "insufficient_funds": False,
    "attribute_offers_unavailable": False,
    "api_error": False,
    "connection_lost": False,
    "worker_stopped": False,
    "rule_paused": False,
    "first_place_unconfirmed": False,
    "emergency_stop": True,
}


async def get_or_create_settings(session: AsyncSession, user_id) -> NotificationSettings:
    settings = get_settings()
    row = (
        await session.execute(select(NotificationSettings).where(NotificationSettings.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        row = NotificationSettings(
            user_id=user_id,
            telegram_enabled=bool(settings.telegram_bot_token),
            telegram_chat_id=settings.telegram_default_chat_id or None,
            events=dict(DEFAULT_EVENTS),
        )
        session.add(row)
        await session.flush()
    elif not row.events:
        row.events = dict(DEFAULT_EVENTS)
    return row


async def telegram_target(session: AsyncSession, user_id) -> str:
    row = await get_or_create_settings(session, user_id)
    return row.telegram_chat_id or get_settings().telegram_default_chat_id


async def _recent_count(session: AsyncSession, user_id, event: str, seconds: int) -> int:
    since = datetime.now(UTC) - timedelta(seconds=seconds)
    result = await session.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.event == event,
            Notification.created_at >= since,
        )
    )
    return int(result.scalar_one())


async def notify(
    session: AsyncSession,
    *,
    user_id,
    event: str,
    title: str,
    message: str,
    level: str = "info",
    force: bool = False,
) -> Notification | None:
    settings = await get_or_create_settings(session, user_id)
    events = settings.events or {}
    if not force and events and not events.get(event, True):
        return None

    if not force:
        recent = await _recent_count(session, user_id, event, settings.min_interval_seconds)
        if recent > 0 and level != "error":
            return None
        hourly = await _recent_count(session, user_id, event, 3600)
        if hourly >= max(1, settings.max_per_hour):
            return None

    notification: Notification | None = None
    if settings.in_app_enabled or force:
        notification = Notification(
            user_id=user_id,
            level=level,
            event=event,
            title=title[:255],
            message=message,
        )
        session.add(notification)
        await session.flush()

    chat_id = settings.telegram_chat_id or get_settings().telegram_default_chat_id
    if settings.telegram_enabled and chat_id and event == "offer_filled":
        session.info.setdefault(OUTBOX_KEY, []).append(
            TelegramMessage(chat_id=chat_id, text=f"{title}\n{message}")
        )

    return notification


async def flush_outbox(session: AsyncSession) -> None:
    pending = session.info.pop(OUTBOX_KEY, None)
    if not pending:
        return
    for message in pending:
        sent = await send_message(message.chat_id, message.text)
        if not sent:
            logger.debug("telegram notification skipped for %s", message.chat_id)
