from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import AuthContext, get_db, require_csrf
from app.enums import OfferStatus
from app.models import ApiCredential, ManagedOffer
from app.runtime import get_rate_limiter
from app.schemas import MessageOut, SystemStatus
from app.services import audit, operations_service

router = APIRouter(prefix="/api/system", tags=["system"])

APP_VERSION = "1.0.0"


@router.get("/status", response_model=SystemStatus)
async def system_status(
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> SystemStatus:
    settings = get_settings()
    user_id = context.user.id

    credential = (
        await session.execute(
            select(ApiCredential)
            .where(ApiCredential.user_id == user_id)
            .order_by(ApiCredential.is_primary.desc(), ApiCredential.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    rate_state = await get_rate_limiter().snapshot(credential.id) if credential is not None else None
    from app.services import settings_service

    values = await settings_service.all_settings(session)
    throughput = values.get("throughput") or {}

    unsynced = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ManagedOffer)
                .where(
                    ManagedOffer.user_id == user_id,
                    ManagedOffer.status == OfferStatus.PENDING.value,
                    ManagedOffer.last_synced_at.is_(None),
                )
            )
        ).scalar_one()
    )

    last_synced = (
        await session.execute(
            select(func.max(ManagedOffer.last_synced_at)).where(ManagedOffer.user_id == user_id)
        )
    ).scalar_one()

    database = "ok"
    try:
        await session.execute(select(1))
    except Exception:  # noqa: BLE001
        database = "error"

    portals_reachable = bool(rate_state and rate_state.last_success_at) or bool(
        credential and credential.last_check_ok
    )

    return SystemStatus(
        app_version=APP_VERSION,
        environment=settings.environment,
        database=database,
        portals_reachable=portals_reachable,
        credential_status=credential.status if credential is not None else None,
        credential_hint=credential.token_hint if credential is not None else None,
        requests_total=int(rate_state.total_requests) if rate_state is not None else 0,
        errors_total=int(rate_state.total_errors) if rate_state is not None else 0,
        rate_limited_total=int(rate_state.total_rate_limited) if rate_state is not None else 0,
        last_success_at=rate_state.last_success_at if rate_state is not None else None,
        last_error_at=rate_state.last_error_at if rate_state is not None else None,
        last_error_message=rate_state.last_error_message if rate_state is not None else None,
        remaining_limit=rate_state.remaining_hint if rate_state is not None else None,
        limit_per_second=rate_state.limit_per_second if rate_state is not None else None,
        worker=throughput or {},
        queue=await operations_service.queue_stats(session),
        offers_synced_at=last_synced,
        unsynced_offers=unsynced,
    )


@router.post("/rate-limit/reset", response_model=MessageOut)
async def reset_rate_limit(
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> MessageOut:
    credential = (
        await session.execute(
            select(ApiCredential)
            .where(ApiCredential.user_id == context.user.id)
            .order_by(ApiCredential.is_primary.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if credential is None:
        return MessageOut(message="Ключ не подключён")
    await get_rate_limiter().reset(credential.id)
    await audit.record(
        session,
        action="rate_limit_reset",
        message="Сброс блокировки лимита запросов",
        actor=context.user.username,
        user_id=context.user.id,
    )
    return MessageOut(message="Блокировка лимита сброшена")
