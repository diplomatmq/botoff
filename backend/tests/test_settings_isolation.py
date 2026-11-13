from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.security import hash_password
from app.services import settings_service


async def _user(session: AsyncSession, username: str) -> User:
    user = User(username=username, password_hash=hash_password("password-123456"), is_active=True)
    session.add(user)
    await session.flush()
    return user


async def test_settings_are_isolated_per_user(session: AsyncSession):
    alice = await _user(session, "alice")
    bob = await _user(session, "bob")

    await settings_service.set_setting(session, "automation_enabled", True, user_id=alice.id)
    await settings_service.set_setting(
        session, "smart_trader_max_purchases_per_collection", 5, user_id=alice.id
    )
    await session.commit()

    assert (
        await settings_service.get_setting(session, "automation_enabled", False, user_id=alice.id)
        is True
    )
    assert (
        await settings_service.get_setting(session, "automation_enabled", False, user_id=bob.id)
        is False
    )
    assert (
        await settings_service.get_setting(
            session, "smart_trader_max_purchases_per_collection", 1, user_id=bob.id
        )
        == 1
    )

    alice_values = await settings_service.all_settings(session, user_id=alice.id)
    bob_values = await settings_service.all_settings(session, user_id=bob.id)
    assert alice_values["automation_enabled"] is True
    assert bob_values["automation_enabled"] is False


async def test_global_setting_is_shared_fallback(session: AsyncSession):
    await settings_service.set_setting(session, "default_min_step", "0.5")
    await session.commit()

    assert await settings_service.get_setting(session, "default_min_step", "0.00001") == "0.5"


async def test_user_override_wins_over_global(session: AsyncSession):
    user = await _user(session, "carol")
    await settings_service.set_setting(session, "smart_trader_max_active_offers", 10)
    await settings_service.set_setting(
        session, "smart_trader_max_active_offers", 3, user_id=user.id
    )
    await session.commit()

    assert (
        await settings_service.get_setting(
            session, "smart_trader_max_active_offers", 1, user_id=user.id
        )
        == 3
    )
    assert await settings_service.get_setting(session, "smart_trader_max_active_offers", 1) == 10
