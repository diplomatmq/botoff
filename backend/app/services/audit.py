from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog
from app.security import sanitize_payload


async def record(
    session: AsyncSession,
    *,
    action: str,
    message: str,
    actor: str = "system",
    user_id: Any = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    level: str = "info",
    details: dict | None = None,
    duration_ms: int | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        level=level,
        message=message,
        details=sanitize_payload(details),
        duration_ms=duration_ms,
    )
    session.add(entry)
    await session.flush()
    return entry
