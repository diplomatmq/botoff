from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.enums import OfferStatus
from app.models import AutomationRule, ManagedOffer
from app.services.offers_service import (
    offer_entries,
    offer_matches_rule,
    offer_matches_scope,
    row_matches_scope,
    rule_scopes,
    scope_signature,
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
        excluded_backdrops=overrides.pop("excluded_backdrops", []),
        symbols=overrides.pop("symbols", []),
    )
    for key, value in overrides.items():
        setattr(rule, key, value)
    return rule


def test_rule_scope_kind_broad_and_trait():
    assert rule_scope_kind(make_rule()) == "broad"
    assert rule_scope_kind(make_rule(models=["Cat"])) == "trait"
    assert rule_uses_attributes(make_rule(backdrops=["Blue"])) is True
    assert rule_uses_attributes(make_rule(excluded_backdrops=["Black"])) is True


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


def test_model_rule_ignores_competitor_narrowed_to_backdrop():
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
    # The rule keeps every backdrop, so offers narrowed to a specific backdrop are ignored.
    assert offer_matches_rule(matching, rule) is False
    assert offer_matches_rule(other_model, rule) is False


def test_model_rule_ignores_offer_scoped_only_to_backdrop():
    rule = make_rule(models=["Cat"])
    backdrop_only = {"scope": {"backdrops": ["Black"]}}
    assert offer_matches_rule(backdrop_only, rule) is False


def test_rule_excluded_backdrops_are_not_competitors():
    rule = make_rule(models=["Cat"], backdrops=["White"], excluded_backdrops=["Black"])
    black_only = {
        "attributes": [
            {"type": "model", "value": "Cat"},
            {"type": "backdrop", "value": "Black"},
        ]
    }
    white_only = {
        "attributes": [
            {"type": "model", "value": "Cat"},
            {"type": "backdrop", "value": "White"},
        ]
    }
    assert offer_matches_rule(black_only, rule) is False
    assert offer_matches_rule(white_only, rule) is True


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


def test_rule_with_several_models_splits_into_one_scope_per_model():
    scopes = rule_scopes(make_rule(models=["Cat", "Dog"], backdrops=["Blue"]))
    assert [scope.models for scope in scopes] == [("Cat",), ("Dog",)]
    assert all(scope.backdrops == ("Blue",) for scope in scopes)
    assert [scope.label for scope in scopes] == ["Cat", "Dog"]


def test_rule_without_models_keeps_a_single_scope():
    scopes = rule_scopes(make_rule(backdrops=["Blue"]))
    assert len(scopes) == 1
    assert scopes[0].label == "вся коллекция"


def test_scope_signature_differs_per_model():
    cat, dog = rule_scopes(make_rule(models=["Cat", "Dog"]))
    assert scope_signature(cat) != scope_signature(dog)


def test_row_matches_only_its_own_model_scope():
    row = ManagedOffer(
        collection_id="c",
        external_offer_id="1",
        status=OfferStatus.PENDING.value,
        scope={"models": ["Cat"], "backdrops": [], "symbols": []},
    )
    cat, dog = rule_scopes(make_rule(models=["Cat", "Dog"]))
    assert row_matches_scope(row, cat) is True
    assert row_matches_scope(row, dog) is False


def test_competitors_are_filtered_by_the_scope_model():
    cat, dog = rule_scopes(make_rule(models=["Cat", "Dog"]))
    cat_offer = {"scope": {"models": ["Cat"]}}
    dog_offer = {"scope": {"models": ["Dog"]}}
    assert offer_matches_scope(cat_offer, cat) is True
    assert offer_matches_scope(cat_offer, dog) is False
    assert offer_matches_scope(dog_offer, dog) is True


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
