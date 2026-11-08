from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import AuthContext, as_uuid, get_db, require_csrf
from app.enums import OperationState
from app.models import OperationQueue
from app.schemas import MessageOut, OperationOut
from app.services import audit, operations_service

router = APIRouter(prefix="/api/operations", tags=["operations"])

RETRYABLE_STATES = {OperationState.FAILED.value, OperationState.DEAD.value}


def operation_out(row: OperationQueue) -> OperationOut:
    return OperationOut(
        id=str(row.id),
        operation_type=row.operation_type,
        state=row.state,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        scheduled_at=row.scheduled_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        last_error=row.last_error,
        requires_verification=row.requires_verification,
        result=row.result,
        rule_id=str(row.rule_id) if row.rule_id else None,
        offer_id=str(row.offer_id) if row.offer_id else None,
        created_at=row.created_at,
    )


@router.get("", response_model=list[OperationOut])
async def list_operations(
    state: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> list[OperationOut]:
    query = select(OperationQueue).where(OperationQueue.user_id == context.user.id)
    if state:
        query = query.where(OperationQueue.state == state)
    query = query.order_by(OperationQueue.created_at.desc()).limit(limit)
    rows = (await session.execute(query)).scalars().all()
    return [operation_out(row) for row in rows]


@router.post("/{operation_id}/retry", response_model=MessageOut)
async def retry_operation(
    operation_id: str,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> MessageOut:
    operation = await session.get(OperationQueue, as_uuid(operation_id, "Операция не найдена"))
    if operation is None or operation.user_id != context.user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Операция не найдена")
    if operation.state not in RETRYABLE_STATES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Повторить можно только неуспешные операции",
        )
    await operations_service.retry_now(session, operation)
    await audit.record(
        session,
        action="operation_retried",
        message=f"Повтор операции {operation.operation_type}",
        actor=context.user.username,
        user_id=context.user.id,
        entity_type="operation",
        entity_id=operation.id,
        level="warning",
    )
    return MessageOut(message="Операция поставлена в очередь на повтор")
