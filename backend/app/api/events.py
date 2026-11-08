from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.db import SessionLocal
from app.dependencies import AuthContext, current_auth
from app.enums import OfferStatus, RuleState
from app.models import AuditLog, AutomationRule, ManagedOffer
from app.services import operations_service, settings_service

router = APIRouter(prefix="/api/events", tags=["events"])

POLL_SECONDS = 3.0
HEARTBEAT_SECONDS = 15.0


async def _snapshot() -> dict:
    async with SessionLocal() as session:
        values = await settings_service.all_settings(session)
        rules = dict(
            (
                await session.execute(
                    select(AutomationRule.state, func.count()).group_by(AutomationRule.state)
                )
            ).all()
        )
        offers = dict(
            (
                await session.execute(
                    select(ManagedOffer.position_status, func.count())
                    .where(ManagedOffer.status == OfferStatus.PENDING.value)
                    .group_by(ManagedOffer.position_status)
                )
            ).all()
        )
        latest = (
            await session.execute(
                select(AuditLog).order_by(AuditLog.created_at.desc()).limit(5)
            )
        ).scalars().all()
        return {
            "ts": datetime.now(UTC).isoformat(),
            "mode": values.get("mode"),
            "automation_enabled": bool(values.get("automation_enabled")),
            "emergency_stop": bool(values.get("emergency_stop")),
            "active_rules": int(rules.get(RuleState.ACTIVE.value, 0)),
            "paused_rules": int(rules.get(RuleState.PAUSED.value, 0)),
            "positions": {key: int(value) for key, value in offers.items()},
            "queue": await operations_service.queue_stats(session),
            "events": [
                {
                    "id": str(row.id),
                    "action": row.action,
                    "level": row.level,
                    "message": row.message,
                    "created_at": row.created_at.isoformat(),
                }
                for row in latest
            ],
        }


def _format(name: str, payload: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream(request: Request) -> AsyncGenerator[str, None]:
    last_beat = 0.0
    last_snapshot: str | None = None
    loop = asyncio.get_running_loop()
    while True:
        if await request.is_disconnected():
            break
        try:
            payload = await _snapshot()
            snapshot = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            if snapshot != last_snapshot:
                yield _format("update", payload)
                last_snapshot = snapshot
        except Exception as exc:  # noqa: BLE001
            yield _format("error", {"message": str(exc)})

        now = loop.time()
        if now - last_beat >= HEARTBEAT_SECONDS:
            last_beat = now
            yield ": keep-alive\n\n"
        await asyncio.sleep(POLL_SECONDS)


@router.get("/stream")
async def stream(request: Request, context: AuthContext = Depends(current_auth)) -> StreamingResponse:
    return StreamingResponse(
        _stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
