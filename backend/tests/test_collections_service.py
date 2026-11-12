from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from app.models import CollectionCache
from app.services.collections_service import resolve_attribute_entries


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
