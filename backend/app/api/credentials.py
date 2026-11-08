from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import AuthContext, as_uuid, get_db, require_csrf
from app.enums import CredentialStatus
from app.models import ApiCredential
from app.runtime import get_rate_limiter
from app.schemas import CredentialCreate, CredentialOut, CredentialRateLimitUpdate, MessageOut
from app.services import credentials_service

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


def credential_out(credential: ApiCredential) -> CredentialOut:
    return CredentialOut(
        id=str(credential.id),
        label=credential.label,
        token_hint=credential.token_hint,
        status=credential.status,
        is_primary=credential.is_primary,
        rate_limit_per_second=credential.rate_limit_per_second,
        sender_id=credential.sender_id,
        last_checked_at=credential.last_checked_at,
        last_check_ok=credential.last_check_ok,
        last_check_message=credential.last_check_message,
    )


async def _own_credential(session: AsyncSession, user_id, credential_id: str) -> ApiCredential:
    credential = await session.get(ApiCredential, as_uuid(credential_id, "Ключ не найден"))
    if credential is None or credential.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ключ не найден")
    return credential


@router.get("", response_model=list[CredentialOut])
async def list_credentials(
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> list[CredentialOut]:
    rows = (
        await session.execute(
            select(ApiCredential)
            .where(ApiCredential.user_id == context.user.id)
            .order_by(ApiCredential.created_at.desc())
        )
    ).scalars().all()
    return [credential_out(row) for row in rows]


@router.post("", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
async def create_credential(
    payload: CredentialCreate,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> CredentialOut:
    credential = await credentials_service.create_credential(
        session,
        user_id=context.user.id,
        token=payload.token,
        label=payload.label,
        rate_limit_per_second=payload.rate_limit_per_second,
        actor=context.user.username,
    )
    return credential_out(credential)


@router.patch("/{credential_id}", response_model=CredentialOut)
async def update_credential(
    credential_id: str,
    payload: CredentialRateLimitUpdate,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> CredentialOut:
    credential = await _own_credential(session, context.user.id, credential_id)
    credential.rate_limit_per_second = payload.rate_limit_per_second
    await session.flush()
    return credential_out(credential)


@router.post("/{credential_id}/check", response_model=CredentialOut)
async def check_credential(
    credential_id: str,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> CredentialOut:
    credential = await _own_credential(session, context.user.id, credential_id)
    await credentials_service.check_credential(
        session,
        credential,
        rate_limiter=get_rate_limiter(),
        user_id=context.user.id,
        actor=context.user.username,
    )
    return credential_out(credential)


@router.post("/{credential_id}/activate", response_model=CredentialOut)
async def activate_credential(
    credential_id: str,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> CredentialOut:
    credential = await _own_credential(session, context.user.id, credential_id)
    others = (
        await session.execute(
            select(ApiCredential).where(ApiCredential.user_id == context.user.id)
        )
    ).scalars().all()
    for item in others:
        item.is_primary = False
    credential.status = CredentialStatus.ACTIVE.value
    credential.is_primary = True
    await session.flush()
    return credential_out(credential)


@router.delete("/{credential_id}", response_model=MessageOut)
async def disable_credential(
    credential_id: str,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> MessageOut:
    credential = await _own_credential(session, context.user.id, credential_id)
    await credentials_service.disable_credential(
        session, credential, user_id=context.user.id, actor=context.user.username
    )
    return MessageOut(message="Ключ отключён")
