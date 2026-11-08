from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import AuthContext, get_db, require_csrf
from app.models import AuditLog
from app.schemas import HistoryEntryOut

router = APIRouter(prefix="/api/history", tags=["history"])


def history_out(row: AuditLog) -> HistoryEntryOut:
    return HistoryEntryOut(
        id=str(row.id),
        action=row.action,
        level=row.level,
        message=row.message,
        actor=row.actor,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        details=row.details,
        duration_ms=row.duration_ms,
        created_at=row.created_at,
    )


@router.get("", response_model=list[HistoryEntryOut])
async def list_history(
    level: str | None = Query(default=None),
    action: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> list[HistoryEntryOut]:
    query = select(AuditLog)
    if context.user.id is not None:
        query = query.where(
            (AuditLog.user_id == context.user.id) | (AuditLog.user_id.is_(None))
        )
    if level:
        query = query.where(AuditLog.level == level)
    if action:
        query = query.where(AuditLog.action == action)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)
    query = query.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(query)).scalars().all()
    return [history_out(row) for row in rows]
