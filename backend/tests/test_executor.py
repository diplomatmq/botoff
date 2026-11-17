from __future__ import annotations

import time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.enums import OfferStatus
from app.services import executor


@pytest.mark.asyncio
async def test_create_offer_sends_amount_with_two_decimal_places(monkeypatch):
    gateway = SimpleNamespace(
        create_offer=AsyncMock(return_value={"id": "external-1", "amount": "1.23"})
    )
    operation = SimpleNamespace(
        payload={"collection_id": "collection-1", "amount": "1.23999", "max_nfts": 1},
        rule_id=None,
        user_id=None,
    )
    monkeypatch.setattr(executor, "_find_existing_managed_offer", AsyncMock(return_value=None))
    monkeypatch.setattr(executor, "_persist_created_offer", AsyncMock())

    outcome = await executor._execute_create(
        SimpleNamespace(),
        operation,
        gateway,
        SimpleNamespace(sender_id=None),
        time.perf_counter(),
    )

    assert outcome.ok is True
    gateway.create_offer.assert_awaited_once()
    assert gateway.create_offer.await_args.kwargs["amount"] == "1.23"
    assert operation.payload["amount"] == "1.23"


@pytest.mark.asyncio
async def test_update_offer_sends_and_persists_amount_with_two_decimal_places(monkeypatch):
    row = SimpleNamespace(
        status=OfferStatus.PENDING.value,
        external_offer_id="external-1",
        amount=Decimal("1.00"),
        max_nfts=1,
        last_action=None,
        last_action_at=None,
        last_error=None,
    )
    gateway = SimpleNamespace(
        bulk_update_offers=AsyncMock(return_value={"updated": ["external-1"], "failed": []})
    )
    operation = SimpleNamespace(
        payload={"amount": "1.23999"},
        offer_id="local-1",
    )
    monkeypatch.setattr(executor, "_find_managed_offer", AsyncMock(return_value=row))

    outcome = await executor._execute_update(
        SimpleNamespace(),
        operation,
        gateway,
        time.perf_counter(),
    )

    assert outcome.ok is True
    gateway.bulk_update_offers.assert_awaited_once_with(
        [{"id": "external-1", "amount": "1.23"}]
    )
    assert row.amount == Decimal("1.23")
    assert operation.payload["amount"] == "1.23"
