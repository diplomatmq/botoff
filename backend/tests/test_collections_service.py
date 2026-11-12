from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from app.api.collections import attribute_out
from app.models import CollectionCache
from app.portals.errors import PortalsError, PortalsServerError
from app.services.collections_service import resolve_attribute_entries


def _empty_model_session() -> Mock:
    """Session whose cached-model query returns an empty list."""
    result = Mock()
    result.scalars.return_value.all.return_value = []
    session = Mock()
    session.get = AsyncMock(return_value=CollectionCache(id="collection-1", name="Collection One"))
    session.execute = AsyncMock(return_value=result)
    return session


def test_attribute_out_formats_string_floor_prices():
    rows = attribute_out(
        [
            {"name": "Black", "floor_price": "10.5"},
            {"name": "Blue", "floor_price": None},
        ]
    )

    assert [row.name for row in rows] == ["Black", "Blue"]
    assert rows[0].floor_price == "10.5"
    assert rows[1].floor_price is None


@pytest.mark.asyncio
async def test_resolve_returns_empty_without_raising_when_sources_respond_empty():
    session = _empty_model_session()
    gateway = Mock()
    gateway.attribute_floors = AsyncMock(return_value={"attribute_floors": {}})
    gateway.backdrop_floors = AsyncMock(return_value={"floorPrices": {}})

    rows = await resolve_attribute_entries(session, gateway, "collection-1", "backdrop")

    assert rows == []


@pytest.mark.asyncio
async def test_resolve_raises_when_every_source_fails():
    session = _empty_model_session()
    gateway = Mock()
    gateway.attribute_floors = AsyncMock(
        side_effect=PortalsServerError("Internal Server Error", status=500)
    )
    gateway.backdrop_floors = AsyncMock(
        side_effect=PortalsServerError("Internal Server Error", status=500)
    )

    with pytest.raises(PortalsError):
        await resolve_attribute_entries(session, gateway, "collection-1", "backdrop")


@pytest.mark.asyncio
async def test_resolve_backdrops_uses_selected_models_when_collection_attributes_are_empty():
    session = Mock()
    session.get = AsyncMock(
        return_value=CollectionCache(id="collection-1", name="Collection One")
    )
    gateway = Mock()
    gateway.attribute_floors = AsyncMock(return_value={"attribute_floors": {}})
    gateway.model_background_floors = AsyncMock(
        return_value={"model_backgrounds": {"Model One": {"Black": "1.25", "Blue": "2"}}}
    )
    gateway.backdrop_floors = AsyncMock()

    rows = await resolve_attribute_entries(
        session,
        gateway,
        "collection-1",
        "backdrop",
        model_names=["Model One"],
    )

    assert {row["name"] for row in rows} == {"Black", "Blue"}
    gateway.model_background_floors.assert_awaited_once_with(["Model One"])
    gateway.backdrop_floors.assert_not_awaited()
