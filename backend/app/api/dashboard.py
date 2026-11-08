from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import AuthContext, get_db, require_csrf
from app.enums import AutomationMode, OfferStatus, PositionStatus, RuleState
from app.models import (
    AccountBudgetState,
    ApiCredential,
    AuditLog,
    AutomationRule,
    ManagedOffer,
)
from app.money import money_str
from app.runtime import get_rate_limiter
from app.schemas import DashboardSummary, HistoryEntryOut
from app.services import operations_service, settings_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

WORKER_STALE_SECONDS = 30


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


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


async def _count(session: AsyncSession, query) -> int:
    return int((await session.execute(query)).scalar_one())


@router.get("", response_model=DashboardSummary)
async def dashboard(
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> DashboardSummary:
    user_id = context.user.id
    values = await settings_service.all_settings(session)
    throughput = values.get("throughput") or {}

    credential = (
        await session.execute(
            select(ApiCredential)
            .where(ApiCredential.user_id == user_id)
            .order_by(ApiCredential.is_primary.desc(), ApiCredential.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    rate_state = None
    api_status = "not_configured"
    api_message = None
    api_last_check = None
    if credential is not None:
        api_last_check = credential.last_checked_at
        rate_state = await get_rate_limiter().snapshot(credential.id)
        if credential.status == "active" and (credential.last_check_ok is None or credential.last_check_ok):
            api_status = "connected"
        elif credential.status == "invalid":
            api_status = "error"
        else:
            api_status = credential.status
        api_message = credential.last_check_message

    rules_by_state = dict(
        (
            await session.execute(
                select(AutomationRule.state, func.count())
                .where(AutomationRule.user_id == user_id)
                .group_by(AutomationRule.state)
            )
        ).all()
    )

    offers_by_position = dict(
        (
            await session.execute(
                select(ManagedOffer.position_status, func.count())
                .where(
                    ManagedOffer.user_id == user_id,
                    ManagedOffer.status == OfferStatus.PENDING.value,
                )
                .group_by(ManagedOffer.position_status)
            )
        ).all()
    )

    active_offers = await _count(
        session,
        select(func.count())
        .select_from(ManagedOffer)
        .where(ManagedOffer.user_id == user_id, ManagedOffer.status == OfferStatus.PENDING.value),
    )

    budget = await session.get(AccountBudgetState, user_id)
    balance = money_str(budget.balance) if budget is not None and budget.balance is not None else None
    frozen = money_str(budget.frozen_funds) if budget is not None and budget.frozen_funds is not None else None

    worker_state = "unknown"
    updated_at = throughput.get("updated_at")
    if updated_at:
        try:
            seen = datetime.fromisoformat(updated_at)
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=UTC)
            worker_state = "running" if (datetime.now(UTC) - seen) < timedelta(seconds=WORKER_STALE_SECONDS) else "stopped"
        except ValueError:
            worker_state = "unknown"

    recent = (
        await session.execute(
            select(AuditLog)
            .where((AuditLog.user_id == user_id) | (AuditLog.user_id.is_(None)))
            .order_by(AuditLog.created_at.desc())
            .limit(10)
        )
    ).scalars().all()

    rate_limit_payload = None
    if rate_state is not None:
        rate_limit_payload = {
            "limit_per_second": rate_state.limit_per_second,
            "remaining_hint": rate_state.remaining_hint,
            "limit_hint": rate_state.limit_hint,
            "blocked_until": _as_utc(rate_state.blocked_until).isoformat() if rate_state.blocked_until else None,
            "total_requests": rate_state.total_requests,
            "total_errors": rate_state.total_errors,
            "total_rate_limited": rate_state.total_rate_limited,
            "last_success_at": _as_utc(rate_state.last_success_at).isoformat() if rate_state.last_success_at else None,
            "last_error_at": _as_utc(rate_state.last_error_at).isoformat() if rate_state.last_error_at else None,
            "last_error_message": rate_state.last_error_message,
        }

    return DashboardSummary(
        api_status=api_status,
        api_message=api_message,
        api_last_check=api_last_check,
        worker_state=worker_state,
        worker_last_tick=updated_at,
        mode=str(values.get("mode", AutomationMode.DRY_RUN.value)),
        automation_enabled=bool(values.get("automation_enabled")),
        emergency_stop=bool(values.get("emergency_stop")),
        active_rules=int(rules_by_state.get(RuleState.ACTIVE.value, 0)),
        paused_rules=int(rules_by_state.get(RuleState.PAUSED.value, 0)),
        error_rules=int(rules_by_state.get(RuleState.ERROR.value, 0)),
        active_offers=active_offers,
        first_place_confirmed=int(offers_by_position.get(PositionStatus.FIRST_CONFIRMED.value, 0)),
        outbid_offers=int(offers_by_position.get(PositionStatus.OUTBID.value, 0)),
        limit_reached_offers=int(offers_by_position.get(PositionStatus.LIMIT_REACHED.value, 0)),
        insufficient_funds_offers=int(offers_by_position.get(PositionStatus.INSUFFICIENT_FUNDS.value, 0)),
        unknown_position_offers=int(offers_by_position.get(PositionStatus.UNKNOWN.value, 0)),
        balance=balance,
        frozen_funds=frozen,
        balance_source=budget.source if budget is not None else "unknown",
        queue=await operations_service.queue_stats(session),
        rate_limit=rate_limit_payload,
        throughput=throughput or None,
        recent_events=[history_out(row) for row in recent],
    )
