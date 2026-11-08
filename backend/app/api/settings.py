from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import AuthContext, get_db, require_csrf
from app.enums import AuditAction, AutomationMode, OfferStatus, OperationType
from app.models import ManagedOffer, OperationQueue
from app.money import money_str
from app.notifications import service as notifications
from app.schemas import EmergencyStopRequest, SettingsOut, SettingsUpdate
from app.services import audit, operations_service, settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


async def _settings_out(session: AsyncSession) -> SettingsOut:
    values = await settings_service.all_settings(session)
    return SettingsOut(
        automation_enabled=bool(values.get("automation_enabled")),
        emergency_stop=bool(values.get("emergency_stop")),
        emergency_stop_reason=values.get("emergency_stop_reason"),
        mode=AutomationMode(values.get("mode", AutomationMode.DRY_RUN.value)),
        default_min_step=str(values.get("default_min_step", "0.00001")),
        throughput=values.get("throughput"),
        notifications_paused=bool(values.get("notifications_paused")),
        smart_trader_enabled=bool(values.get("smart_trader_enabled")),
        smart_trader_min_spread_percent=str(values.get("smart_trader_min_spread_percent", "0")),
        smart_trader_max_rebids_per_offer=values.get("smart_trader_max_rebids_per_offer"),
        smart_trader_excluded_collections=list(values.get("smart_trader_excluded_collections") or []),
        smart_trader_excluded_models=list(values.get("smart_trader_excluded_models") or []),
        smart_trader_excluded_backdrops=list(values.get("smart_trader_excluded_backdrops") or []),
        smart_trader_attribute_collection_id=values.get("smart_trader_attribute_collection_id"),
    )


@router.get("", response_model=SettingsOut)
async def get_settings_view(
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> SettingsOut:
    return await _settings_out(session)


@router.put("", response_model=SettingsOut)
async def update_settings(
    payload: SettingsUpdate,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> SettingsOut:
    current = await settings_service.all_settings(session)
    emergency = bool(current.get("emergency_stop"))

    if payload.mode is not None:
        if payload.mode == AutomationMode.LIVE and not payload.confirm_live:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Переключение в режим LIVE требует явного подтверждения",
            )
        if payload.mode == AutomationMode.LIVE and emergency:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Сначала снимите аварийную остановку",
            )
        await settings_service.set_setting(session, "mode", payload.mode.value)
        await audit.record(
            session,
            action=AuditAction.MODE_CHANGED.value,
            message=f"Режим изменён на {payload.mode.value}",
            actor=context.user.username,
            user_id=context.user.id,
            level="warning" if payload.mode == AutomationMode.LIVE else "info",
        )

    if payload.automation_enabled is not None:
        if payload.automation_enabled and emergency:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Сначала снимите аварийную остановку",
            )
        await settings_service.set_setting(session, "automation_enabled", payload.automation_enabled)

    if payload.default_min_step is not None:
        await settings_service.set_setting(session, "default_min_step", money_str(payload.default_min_step))
    if payload.smart_trader_enabled is not None:
        await settings_service.set_setting(session, "smart_trader_enabled", payload.smart_trader_enabled)
        if not payload.smart_trader_enabled:
            pending_trader_operations = (
                await session.execute(
                    select(OperationQueue).where(
                        OperationQueue.operation_type == OperationType.CREATE_OFFER.value,
                        OperationQueue.state.in_(("pending", "retry")),
                    )
                )
            ).scalars().all()
            for operation in pending_trader_operations:
                if (operation.payload or {}).get("source") == "smart_trader":
                    operation.state = "cancelled"
                    operation.finished_at = datetime.now(UTC)
                    operation.last_error = "Smart Trader отключён пользователем"
    if payload.smart_trader_min_spread_percent is not None:
        await settings_service.set_setting(
            session, "smart_trader_min_spread_percent", str(payload.smart_trader_min_spread_percent)
        )
    if "smart_trader_max_rebids_per_offer" in payload.model_fields_set:
        await settings_service.set_setting(
            session, "smart_trader_max_rebids_per_offer", payload.smart_trader_max_rebids_per_offer
        )
    for key in (
        "smart_trader_excluded_collections",
        "smart_trader_excluded_models",
        "smart_trader_excluded_backdrops",
        "smart_trader_attribute_collection_id",
    ):
        if key in payload.model_fields_set:
            await settings_service.set_setting(session, key, getattr(payload, key))

    await audit.record(
        session,
        action=AuditAction.SETTINGS_UPDATED.value,
        message="Настройки автоматизации обновлены",
        actor=context.user.username,
        user_id=context.user.id,
        details={
            "automation_enabled": payload.automation_enabled,
            "default_min_step": money_str(payload.default_min_step) if payload.default_min_step is not None else None,
        },
    )
    return await _settings_out(session)


@router.post("/emergency-stop", response_model=SettingsOut)
async def emergency_stop(
    payload: EmergencyStopRequest,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> SettingsOut:
    await settings_service.set_setting(session, "emergency_stop", payload.enabled)
    await settings_service.set_setting(session, "emergency_stop_reason", payload.reason if payload.enabled else None)
    if payload.enabled:
        await settings_service.set_setting(session, "automation_enabled", False)

    cancelled = 0
    if payload.enabled and payload.cancel_offers:
        rows = (
            await session.execute(
                select(ManagedOffer).where(
                    ManagedOffer.user_id == context.user.id,
                    ManagedOffer.status == OfferStatus.PENDING.value,
                )
            )
        ).scalars().all()
        for row in rows:
            operation = await operations_service.enqueue(
                session,
                dedupe_key=operations_service.make_dedupe_key("cancel", row.id, "emergency"),
                operation_type=OperationType.CANCEL_OFFER.value,
                user_id=context.user.id,
                rule_id=row.rule_id,
                offer_id=row.id,
                payload={
                    "offer_row_id": str(row.id),
                    "external_offer_id": row.external_offer_id,
                    "collection_id": row.collection_id,
                    "scope_kind": row.scope_kind,
                },
            )
            if operation is not None:
                cancelled += 1

    action = (
        AuditAction.EMERGENCY_STOP.value if payload.enabled else AuditAction.EMERGENCY_STOP_RELEASED.value
    )
    message = "Аварийная остановка включена" if payload.enabled else "Аварийная остановка снята"
    if cancelled:
        message += f", отмена офферов: {cancelled}"
    await audit.record(
        session,
        action=action,
        message=message,
        actor=context.user.username,
        user_id=context.user.id,
        level="error" if payload.enabled else "warning",
        details={"reason": payload.reason, "cancel_offers": payload.cancel_offers},
    )
    await notifications.notify(
        session,
        user_id=context.user.id,
        event="emergency_stop",
        title="Аварийная остановка",
        message=message,
        level="error",
        force=True,
    )
    return await _settings_out(session)
