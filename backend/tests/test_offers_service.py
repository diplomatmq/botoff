from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.enums import OfferStatus
from app.models import AutomationRule, ManagedOffer
from app.services.offers_service import (
    offer_entries,
    offer_matches_rule,
    sender_matches,
    rule_attributes,
    rule_committed_amount,
    rule_scope_kind,
    rule_uses_attributes,
    snapshot_is_stale,
    _as_utc,
    portals_gift_url,
)


def make_rule(**overrides) -> AutomationRule:
    rule = AutomationRule(
        name="r",
        collection_id="col-1",
        models=overrides.pop("models", []),
        backdrops=overrides.pop("backdrops", []),
        symbols=overrides.pop("symbols", []),
    )
    for key, value in overrides.items():
        setattr(rule, key, value)
    return rule


def test_rule_scope_kind_broad_and_trait():
    assert rule_scope_kind(make_rule()) == "broad"
    assert rule_scope_kind(make_rule(models=["Cat"])) == "trait"
    assert rule_uses_attributes(make_rule(backdrops=["Blue"])) is True


def test_rule_attributes_are_built_from_selections():
    attributes = rule_attributes(make_rule(models=["Cat"], backdrops=["Blue"], symbols=["Star"]))
    assert {"type": "model", "value": "Cat"} in attributes
    assert {"type": "backdrop", "value": "Blue"} in attributes
    assert {"type": "symbol", "value": "Star"} in attributes


def test_broad_offer_matches_any_rule():
    assert offer_matches_rule({"scope": {}}, make_rule(models=["Cat"])) is True


def test_attribute_offer_must_overlap_rule_selection():
    rule = make_rule(models=["Cat"])
    matching = {"scope": {"models": ["Cat"]}}
    other = {"scope": {"models": ["Dog"]}}
    assert offer_matches_rule(matching, rule) is True
    assert offer_matches_rule(other, rule) is False


def test_model_rule_considers_competitor_with_specific_backdrop():
    rule = make_rule(models=["Cat"])
    matching = {
        "attributes": [
            {"type": "model", "value": "Cat"},
            {"type": "backdrop", "value": "Black"},
        ]
    }
    other_model = {
        "attributes": [
            {"type": "model", "value": "Dog"},
            {"type": "backdrop", "value": "Black"},
        ]
    }
    assert offer_matches_rule(matching, rule) is True
    assert offer_matches_rule(other_model, rule) is False


def test_model_rule_ignores_offer_scoped_only_to_backdrop():
    rule = make_rule(models=["Cat"])
    backdrop_only = {"scope": {"backdrops": ["Black"]}}
    assert offer_matches_rule(backdrop_only, rule) is False


def test_committed_amount_counts_pending_only():
    pending = ManagedOffer(
        collection_id="c",
        external_offer_id="1",
        amount=Decimal("2"),
        max_nfts=3,
        status=OfferStatus.PENDING.value,
        scope={},
    )
    canceled = ManagedOffer(
        collection_id="c",
        external_offer_id="2",
        amount=Decimal("100"),
        max_nfts=1,
        status=OfferStatus.CANCELED.value,
        scope={},
    )
    assert rule_committed_amount([pending, canceled]) == Decimal("6")


def test_snapshot_is_stale_by_ttl():
    assert snapshot_is_stale(None) is True
    assert snapshot_is_stale(datetime.now(UTC) - timedelta(seconds=5), ttl_seconds=60) is False
    assert snapshot_is_stale(datetime.now(UTC) - timedelta(seconds=120), ttl_seconds=60) is True
    naive = datetime.utcnow() - timedelta(seconds=120)
    assert snapshot_is_stale(naive, ttl_seconds=60) is True


def test_as_utc_normalizes_naive_and_offset_datetimes():
    naive = datetime(2026, 11, 7, 23, 0)
    offset = datetime.fromisoformat("2026-11-07T23:00:00+03:00")
    assert _as_utc(naive) == datetime(2026, 11, 7, 23, 0, tzinfo=UTC)
    assert _as_utc(offset) == datetime(2026, 11, 7, 20, 0, tzinfo=UTC)


def test_portals_gift_url_uses_telegram_collection_link():
    assert portals_gift_url({"name": "Durov's Cap", "external_collection_number": 42}) == (
        "https://t.me/nft/Durov_s_Cap-42"
    )
    assert portals_gift_url({"tg_id": "MadPumpkin-9501"}) == "https://t.me/nft/MadPumpkin-9501"


def test_offer_entries_accepts_object_response():
    entries = offer_entries({"offers": [{"id": "1", "amount": "3.84"}], "total_count": 1})
    assert entries[0]["offers"] == [{"id": "1", "amount": "3.84"}]
    assert entries[0]["total_count"] == 1
    assert offer_entries([{"offers": [{"id": "2"}]}])[0]["offers"][0]["id"] == "2"


def test_sender_matches_normalizes_api_identifier_type():
    assert sender_matches("123", 123) is True
    assert sender_matches(123, 123) is True
    assert sender_matches("456", 123) is False
    assert sender_matches("123", None) is False
