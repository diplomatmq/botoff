from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import AutomationMode
from app.models import ApplicationSetting, UserSetting

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
    "smart_trader_max_purchases_per_collection": 1,
    "smart_trader_excluded_collections": [],
    "smart_trader_excluded_models": [],
    "smart_trader_excluded_backdrops": [],
    "smart_trader_attribute_collection_id": None,
}

# Keys that describe the running process rather than an account. They stay in
# ``application_settings`` and are shared by every account.
GLOBAL_KEYS: frozenset[str] = frozenset({"throughput"})


async def get_setting(
    session: AsyncSession,
    key: str,
    default: Any = None,
    *,
    user_id: uuid.UUID | None = None,
) -> Any:
    """Read a setting for a specific account.

    Account-scoped settings never fall back to the shared ``application_settings``
    row, so one account cannot inherit another account's automation or trader
    configuration. Only :data:`GLOBAL_KEYS` are read from the shared row.
    """
    if user_id is not None:
        user_row = await session.get(UserSetting, (user_id, key))
        if user_row is not None and "v" in (user_row.value or {}):
            return (user_row.value or {})["v"]
        if key not in GLOBAL_KEYS:
            return DEFAULTS.get(key, default)
    row = await session.get(ApplicationSetting, key)
    if row is None:
        return DEFAULTS.get(key, default)
    value = row.value or {}
    return value.get("v", DEFAULTS.get(key, default))


async def set_setting(
    session: AsyncSession,
    key: str,
    value: Any,
    *,
    user_id: uuid.UUID | None = None,
) -> None:
    """Store a setting for a specific account, or globally when no account is given."""
    if user_id is not None:
        row = await session.get(UserSetting, (user_id, key))
        if row is None:
            session.add(UserSetting(user_id=user_id, key=key, value={"v": value}))
        else:
            row.value = {"v": value}
        return
    row = await session.get(ApplicationSetting, key)
    if row is None:
        session.add(ApplicationSetting(key=key, value={"v": value}))
    else:
        row.value = {"v": value}


async def all_settings(
    session: AsyncSession, *, user_id: uuid.UUID | None = None
) -> dict[str, Any]:
    result = await session.execute(select(ApplicationSetting))
    rows = {row.key: (row.value or {}).get("v") for row in result.scalars().all()}
    if user_id is not None:
        # Only process-wide keys are shared; account settings come from the user.
        rows = {key: value for key, value in rows.items() if key in GLOBAL_KEYS}
        user_rows = (
            await session.execute(select(UserSetting).where(UserSetting.user_id == user_id))
        ).scalars().all()
        rows.update({row.key: (row.value or {}).get("v") for row in user_rows})
    return {**DEFAULTS, **rows}


async def ensure_defaults(session: AsyncSession) -> None:
    for key, value in DEFAULTS.items():
        if await session.get(ApplicationSetting, key) is None:
            session.add(ApplicationSetting(key=key, value={"v": value}))
    await session.flush()


async def trading_allowed(
    session: AsyncSession, *, user_id: uuid.UUID | None = None
) -> tuple[bool, str | None]:
    enabled = await get_setting(session, "automation_enabled", False, user_id=user_id)
    stop = await get_setting(session, "emergency_stop", False, user_id=user_id)
    mode = await get_setting(session, "mode", AutomationMode.DRY_RUN.value, user_id=user_id)
    if stop:
        return False, "EMERGENCY_STOP"
    if not enabled:
        return False, "AUTOMATION_DISABLED"
    if mode != AutomationMode.LIVE.value:
        return False, "DRY_RUN"
    return True, None
