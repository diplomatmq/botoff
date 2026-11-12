from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import AutomationMode
from app.models import ApplicationSetting

DEFAULTS: dict[str, Any] = {
    "automation_enabled": False,
    "emergency_stop": False,
    "mode": AutomationMode.DRY_RUN.value,
    "emergency_stop_reason": None,
    "default_max_budget": None,
    "default_min_step": "0.00001",
    "notifications_paused": False,
    "smart_trader_enabled": False,
    "smart_trader_min_spread_percent": "0",
    "smart_trader_max_rebids_per_offer": None,
    "smart_trader_max_active_offers": 1,
    "smart_trader_excluded_collections": [],
    "smart_trader_excluded_models": [],
    "smart_trader_excluded_backdrops": [],
    "smart_trader_attribute_collection_id": None,
}


async def get_setting(session: AsyncSession, key: str, default: Any = None) -> Any:
    row = await session.get(ApplicationSetting, key)
    if row is None:
        return DEFAULTS.get(key, default)
    value = row.value or {}
    return value.get("v", DEFAULTS.get(key, default))


async def set_setting(session: AsyncSession, key: str, value: Any) -> None:
    row = await session.get(ApplicationSetting, key)
    if row is None:
        session.add(ApplicationSetting(key=key, value={"v": value}))
    else:
        row.value = {"v": value}


async def all_settings(session: AsyncSession) -> dict[str, Any]:
    result = await session.execute(select(ApplicationSetting))
    rows = {row.key: (row.value or {}).get("v") for row in result.scalars().all()}
    return {**DEFAULTS, **rows}


async def ensure_defaults(session: AsyncSession) -> None:
    for key, value in DEFAULTS.items():
        if await session.get(ApplicationSetting, key) is None:
            session.add(ApplicationSetting(key=key, value={"v": value}))
    await session.flush()


async def trading_allowed(session: AsyncSession) -> tuple[bool, str | None]:
    enabled = await get_setting(session, "automation_enabled", False)
    stop = await get_setting(session, "emergency_stop", False)
    mode = await get_setting(session, "mode", AutomationMode.DRY_RUN.value)
    if stop:
        return False, "EMERGENCY_STOP"
    if not enabled:
        return False, "AUTOMATION_DISABLED"
    if mode != AutomationMode.LIVE.value:
        return False, "DRY_RUN"
    return True, None
