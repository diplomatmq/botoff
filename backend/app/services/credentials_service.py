from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import AuditAction, CredentialStatus
from app.models import ApiCredential, ApiRequestState
from app.portals.client import CredentialContext, PortalsClient
from app.portals.errors import CREDENTIAL_ERROR_CODES, PortalsAuthError, PortalsError
from app.portals.rate_limiter import RateLimiter, utcnow
from app.security import decrypt_secret, encrypt_secret, mask_token
from app.services import audit


async def _ensure_state(session: AsyncSession, credential_id) -> None:
    state = await session.get(ApiRequestState, credential_id)
    if state is None:
        session.add(
            ApiRequestState(
                credential_id=credential_id,
                window_started_at=utcnow(),
                window_count=0,
                limit_per_second=1,
            )
        )
        await session.flush()


async def create_credential(
    session: AsyncSession,
    *,
    user_id,
    token: str,
    label: str = "default",
    rate_limit_per_second: int = 1,
    actor: str = "user",
) -> ApiCredential:
    token = token.strip()
    existing = (
        await session.execute(select(ApiCredential).where(ApiCredential.user_id == user_id))
    ).scalars().all()
    for item in existing:
        item.is_primary = False

    credential = ApiCredential(
        user_id=user_id,
        label=label[:64] or "default",
        encrypted_token=encrypt_secret(token),
        token_hint=mask_token(token),
        status=CredentialStatus.ACTIVE.value,
        is_primary=True,
        rate_limit_per_second=max(1, rate_limit_per_second),
    )
    session.add(credential)
    await session.flush()
    await _ensure_state(session, credential.id)
    await audit.record(
        session,
        action=AuditAction.CREDENTIAL_CREATED.value,
        message=f"API-ключ подключён ({credential.token_hint})",
        actor=actor,
        user_id=user_id,
        entity_type="api_credential",
        entity_id=credential.id,
    )
    return credential


async def disable_credential(session: AsyncSession, credential: ApiCredential, *, user_id, actor: str = "user") -> None:
    credential.status = CredentialStatus.DISABLED.value
    credential.is_primary = False
    await audit.record(
        session,
        action=AuditAction.CREDENTIAL_DISABLED.value,
        message="Интеграция с Portals отключена",
        actor=actor,
        user_id=user_id,
        entity_type="api_credential",
        entity_id=credential.id,
    )


async def check_credential(
    session: AsyncSession,
    credential: ApiCredential,
    *,
    rate_limiter: RateLimiter,
    user_id=None,
    actor: str = "user",
) -> tuple[bool, str]:
    context = CredentialContext(
        credential_id=credential.id,
        token=decrypt_secret(credential.encrypted_token),
        rate_limit_per_second=credential.rate_limit_per_second or 1,
    )
    client = PortalsClient(context, rate_limiter=rate_limiter)
    ok = False
    message = ""
    try:
        payload = await client.request("GET", "/market/config", retries=2)
        wallet = await client.request("GET", "/users/wallets/", retries=2)
        balance = "—"
        if isinstance(wallet, dict) and wallet.get("balance") is not None:
            balance = str(wallet["balance"])
        tier = ""
        if isinstance(payload, dict):
            tier = str(payload.get("subscription") or payload.get("plan") or "")
        message = f"Подключение успешно. Баланс: {balance} GRAM"
        if tier:
            message += f", тариф: {tier}"
        ok = True
    except PortalsAuthError as exc:
        message = exc.message
        credential.status = CredentialStatus.INVALID.value
    except PortalsError as exc:
        message = str(exc)
    finally:
        credential.last_checked_at = datetime.now(UTC)
        credential.last_check_ok = ok
        credential.last_check_message = message[:500]
        await audit.record(
            session,
            action=AuditAction.CREDENTIAL_CHECKED.value,
            message=f"Проверка ключа {credential.token_hint}: {'успех' if ok else 'ошибка'} — {message}",
            actor=actor,
            user_id=user_id,
            entity_type="api_credential",
            entity_id=credential.id,
            level="info" if ok else "warning",
        )
        await session.flush()
    return ok, message


def classify_error_code(code: str | None) -> str | None:
    if code in CREDENTIAL_ERROR_CODES:
        return code
    return None
