from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import AuthContext, get_db, require_csrf
from app.models import CollectionCache
from app.money import money_str
from app.runtime import build_gateway, get_primary_credential
from app.schemas import CollectionOut, MessageOut, ModelOut
from app.services import audit, collections_service

router = APIRouter(prefix="/api/collections", tags=["collections"])


def collection_out(row: CollectionCache) -> CollectionOut:
    models = list(row.models or [])
    return CollectionOut(
        id=row.id,
        name=row.name,
        short_name=row.short_name,
        photo_url=row.photo_url,
        floor_price=money_str(row.floor_price) if row.floor_price is not None else None,
        max_offer=money_str(row.max_offer) if row.max_offer is not None else None,
        supply=row.supply,
        day_volume=money_str(row.day_volume) if row.day_volume is not None else None,
        market_cap=money_str(row.market_cap) if row.market_cap is not None else None,
        is_new=row.is_new,
        zero_commission=row.zero_commission,
        cashback_percent=money_str(row.cashback_percent) if row.cashback_percent is not None else None,
        points_multiplier=money_str(row.points_multiplier) if row.points_multiplier is not None else None,
        offers_supported=row.offers_supported,
        models_available=bool(models),
        models_count=len(models),
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[CollectionOut])
async def list_collections(
    search: str | None = Query(default=None, max_length=128),
    only_offers: bool = Query(default=False),
    sort_by: str = Query(default="name", pattern="^(name|floor_price)$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> list[CollectionOut]:
    rows = await collections_service.list_collections(
        session,
        search=search,
        only_offers=only_offers,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    return [collection_out(row) for row in rows]


@router.post("/refresh", response_model=MessageOut)
async def refresh_catalog(
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> MessageOut:
    credential = await get_primary_credential(session, context.user.id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сначала подключите API-ключ Portals")
    gateway = build_gateway(credential)
    report = await collections_service.refresh_catalog(session, gateway)
    await audit.record(
        session,
        action="catalog_refreshed",
        message=f"Каталог обновлён: коллекций {report.get('collections', 0)}, моделей {report.get('models', 0)}",
        actor=context.user.username,
        user_id=context.user.id,
    )
    return MessageOut(
        message=f"Обновлено коллекций: {report.get('collections', 0)}, моделей: {report.get('models', 0)}"
    )


@router.get("/{collection_id}/models", response_model=list[ModelOut])
async def list_models(
    collection_id: str,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> list[ModelOut]:
    rows = await collections_service.list_models(session, collection_id)
    return [
        ModelOut(
            name=row.name,
            photo_url=row.photo_url,
            floor_price=money_str(row.floor_price) if row.floor_price is not None else None,
            max_offer=money_str(row.max_offer) if row.max_offer is not None else None,
        )
        for row in rows
    ]


def attribute_out(rows: list[dict]) -> list[ModelOut]:
    result: list[ModelOut] = []
    for row in rows:
        photo = collections_service._photo_url(row)
        if not photo and row.get("photos"):
            photos_data = row.get("photos")
            if isinstance(photos_data, list) and photos_data:
                first = photos_data[0]
                photo = first if isinstance(first, str) else first.get("url") if isinstance(first, dict) else None
            elif isinstance(photos_data, dict):
                photo = photos_data.get("url")
        result.append(
            ModelOut(
                name=row["name"],
                photo_url=photo,
                floor_price=money_str(row["floor_price"]) if row.get("floor_price") is not None else None,
                max_offer=None,
            )
        )
    return result


@router.get("/{collection_id}/backdrops", response_model=list[ModelOut])
async def list_backdrops(
    collection_id: str,
    models: str | None = Query(default=None, max_length=4096),
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> list[ModelOut]:
    credential = await get_primary_credential(session, context.user.id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сначала подключите API-ключ Portals")
    gateway = build_gateway(credential)
    model_names = [item.strip() for item in (models or "").split(",") if item.strip()]
    rows = await collections_service.resolve_attribute_entries(
        session, gateway, collection_id, "backdrop", model_names=model_names
    )
    return attribute_out(rows)


@router.get("/{collection_id}/symbols", response_model=list[ModelOut])
async def list_symbols(
    collection_id: str,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> list[ModelOut]:
    credential = await get_primary_credential(session, context.user.id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сначала подключите API-ключ Portals")
    gateway = build_gateway(credential)
    rows = await collections_service.resolve_attribute_entries(session, gateway, collection_id, "symbol")
    return attribute_out(rows)


@router.post("/{collection_id}/models/refresh", response_model=MessageOut)
async def refresh_models(
    collection_id: str,
    context: AuthContext = Depends(require_csrf),
    session: AsyncSession = Depends(get_db),
) -> MessageOut:
    credential = await get_primary_credential(session, context.user.id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сначала подключите API-ключ Portals")
    gateway = build_gateway(credential)
    report = await collections_service.refresh_models(session, gateway)
    return MessageOut(message=f"Моделей загружено: {report.get('models', 0)}")
