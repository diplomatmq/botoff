from __future__ import annotations

from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ApiCredential
from app.portals.client import CredentialContext, PortalsClient, PortalsGateway
from app.portals.rate_limiter import RateLimiter
from app.security import decrypt_secret


@lru_cache(maxsize=1)
def get_rate_limiter() -> RateLimiter:
    settings = get_settings()
    from app.db import SessionLocal

    return RateLimiter(SessionLocal, safety_margin=settings.rate_limit_safety_margin)


def build_gateway(credential: ApiCredential) -> PortalsGateway:
    context = CredentialContext(
        credential_id=credential.id,
        token=decrypt_secret(credential.encrypted_token),
        rate_limit_per_second=credential.rate_limit_per_second or 1,
    )
    return PortalsGateway(PortalsClient(context, rate_limiter=get_rate_limiter()))


async def get_primary_credential(session: AsyncSession, user_id) -> ApiCredential | None:
    result = await session.execute(
        select(ApiCredential)
        .where(ApiCredential.user_id == user_id, ApiCredential.status != "disabled")
        .order_by(ApiCredential.is_primary.desc(), ApiCredential.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
