from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ApiCredential, User
from app.security import hash_password
from app.services import credentials_service, settings_service

logger = logging.getLogger("portals.bootstrap")


async def ensure_admin(session: AsyncSession) -> User | None:
    settings = get_settings()
    username = settings.admin_username.strip()
    password = settings.admin_password
    if not username or not password:
        logger.warning("ADMIN_USERNAME/ADMIN_PASSWORD не заданы — администратор не создан")
        return None

    user = (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if user is not None:
        return user

    user = User(username=username, password_hash=hash_password(password), is_admin=True, is_active=True)
    session.add(user)
    await session.flush()
    logger.info("создан администратор %s", username)
    if settings.admin_password == "admin":
        logger.warning("используется пароль администратора по умолчанию — смените его в панели")
    return user


async def ensure_portals_credential(session: AsyncSession, user: User) -> None:
    settings = get_settings()
    token = settings.portals_api_token.strip()
    if not token:
        return
    existing = (
        await session.execute(select(ApiCredential).where(ApiCredential.user_id == user.id))
    ).scalars().first()
    if existing is not None:
        return
    await credentials_service.create_credential(
        session,
        user_id=user.id,
        token=token,
        label="Из .env",
        rate_limit_per_second=settings.portals_default_rps,
        actor="bootstrap",
    )
    logger.info("API-ключ Portals подключён из переменной PORTALS_API_TOKEN")


async def bootstrap(session: AsyncSession) -> None:
    await settings_service.ensure_defaults(session)
    user = await ensure_admin(session)
    if user is not None:
        await ensure_portals_credential(session, user)
