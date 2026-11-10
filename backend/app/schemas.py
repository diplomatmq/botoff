from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.enums import AutomationMode, OnLimitBehavior, RuleState, ScopeMode, Strategy

MIN_OFFER = Decimal("0.5")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    is_admin: bool
    last_login_at: datetime | None = None


class AdminUserOut(UserOut):
    is_active: bool
    telegram_enabled: bool
    telegram_chat_id: str | None


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=10, max_length=256)
    is_admin: bool = False
    telegram_chat_id: str | None = Field(default=None, max_length=64)
    telegram_enabled: bool = False


class AdminUserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=10, max_length=256)
    is_admin: bool | None = None
    is_active: bool | None = None
    telegram_chat_id: str | None = Field(default=None, max_length=64)
    telegram_enabled: bool | None = None


class CredentialCreate(BaseModel):
    token: str = Field(min_length=8, max_length=512)
    label: str = Field(default="default", max_length=64)
    rate_limit_per_second: int = Field(default=1, ge=1, le=100)


class CredentialRateLimitUpdate(BaseModel):
    rate_limit_per_second: int = Field(ge=1, le=100)


class CredentialOut(BaseModel):
    id: str
    label: str
    token_hint: str
    status: str
    is_primary: bool
    rate_limit_per_second: int
    sender_id: int | None
    last_checked_at: datetime | None
    last_check_ok: bool | None
    last_check_message: str | None


class RuleBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    collection_id: str = Field(min_length=1, max_length=64)
    scope_mode: ScopeMode = ScopeMode.COLLECTION
    models: list[str] = Field(default_factory=list)
    backdrops: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    scope_guard: bool = True

    strategy: Strategy = Strategy.FLOOR_RELATIVE
    hold_first_place: bool = False
    pause_on_uncertainty: bool = True

    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=95)
    max_price_percent: Decimal | None = Field(default=None, ge=5, le=100)
    fixed_price: Decimal | None = Field(default=None, gt=0)
    min_step: Decimal = Field(default=Decimal("0.00001"), gt=0)
    max_price_per_offer: Decimal | None = Field(default=None, gt=0)
    max_budget: Decimal | None = Field(default=None, gt=0)
    max_active_offers: int = Field(default=1, ge=1, le=10)
    max_nfts: int = Field(default=1, ge=1, le=50)
    expiration_days: int | None = None

    check_interval_seconds: int = Field(default=60, ge=5, le=86400)
    on_limit_behavior: OnLimitBehavior = OnLimitBehavior.KEEP
    credential_id: str | None = None

    @field_validator("expiration_days")
    @classmethod
    def _validate_expiration(cls, value: int | None) -> int | None:
        if value is None or value == 0:
            return None
        if value not in (1, 7):
            raise ValueError("Срок действия оффера может быть только 1 или 7 дней")
        return value

    @field_validator("models", "backdrops", "symbols")
    @classmethod
    def _clean_attributes(cls, value: list[str]) -> list[str]:
        return sorted({item.strip() for item in value if item and item.strip()})

    @model_validator(mode="after")
    def _validate_consistency(self) -> RuleBase:
        if self.strategy == Strategy.FIXED and self.fixed_price is None:
            raise ValueError("Для стратегии фиксированного оффера укажите цену")
        if self.strategy == Strategy.MODELS_ONLY and not (self.models or self.backdrops or self.symbols):
            raise ValueError("Для стратегии «только выбранные модели» выберите атрибуты")
        if self.max_nfts > 50:
            raise ValueError("Количество NFT не может превышать 50")
        return self


class RuleCreate(RuleBase):
    state: RuleState = RuleState.DISABLED


class RuleUpdate(RuleBase):
    state: RuleState | None = None


class RuleOut(BaseModel):
    id: str
    name: str
    collection_id: str
    collection_name: str | None
    scope_mode: str
    models: list[str]
    backdrops: list[str]
    symbols: list[str]
    scope_guard: bool
    strategy: str
    hold_first_place: bool
    pause_on_uncertainty: bool
    discount_percent: str
    max_price_percent: str | None
    fixed_price: str | None
    min_step: str
    max_price_per_offer: str | None
    max_budget: str | None
    max_active_offers: int
    max_nfts: int
    expiration_days: int | None
    check_interval_seconds: int
    enabled: bool
    state: str
    on_limit_behavior: str
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_error: str | None
    last_position_status: str | None
    last_decision: dict[str, Any] | None
    active_offers: int = 0
    created_at: datetime
    updated_at: datetime


class RuleStateChange(BaseModel):
    state: RuleState | None = None
    enabled: bool | None = None


class CollectionOut(BaseModel):
    id: str
    name: str
    short_name: str | None
    photo_url: str | None
    floor_price: str | None
    max_offer: str | None
    supply: int | None
    day_volume: str | None
    market_cap: str | None
    is_new: bool
    zero_commission: bool
    cashback_percent: str | None
    points_multiplier: str | None
    offers_supported: bool
    models_available: bool
    models_count: int
    updated_at: datetime


class ModelOut(BaseModel):
    name: str
    photo_url: str | None
    floor_price: str | None
    max_offer: str | None


class OfferOut(BaseModel):
    id: str
    rule_id: str | None
    rule_name: str | None
    source: str
    rebid_count: int
    collection_id: str
    collection_name: str | None
    external_offer_id: str
    scope: dict[str, Any]
    scope_kind: str
    amount: str
    max_amount: str | None
    max_nfts: int
    current_nfts: int
    status: str
    position_status: str
    position_rank: int | None
    last_action: str | None
    last_action_at: datetime | None
    last_synced_at: datetime | None
    last_error: str | None
    created_at: datetime


class PurchasedGiftOut(BaseModel):
    id: str
    offer_id: str
    collection_id: str
    collection_name: str
    gift_id: str | None
    amount: str
    purchased_at: datetime
    portals_url: str | None = None
    raw: dict[str, Any] | None


class OperationOut(BaseModel):
    id: str
    operation_type: str
    state: str
    attempts: int
    max_attempts: int
    scheduled_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    last_error: str | None
    requires_verification: bool
    result: dict[str, Any] | None
    rule_id: str | None
    offer_id: str | None
    created_at: datetime


class HistoryEntryOut(BaseModel):
    id: str
    action: str
    level: str
    message: str
    actor: str
    entity_type: str | None
    entity_id: str | None
    details: dict[str, Any] | None
    duration_ms: int | None
    created_at: datetime


class SettingsOut(BaseModel):
    automation_enabled: bool
    emergency_stop: bool
    emergency_stop_reason: str | None
    mode: AutomationMode
    default_min_step: str
    throughput: dict[str, Any] | None
    notifications_paused: bool
    smart_trader_enabled: bool
    smart_trader_min_spread_percent: str
    smart_trader_max_rebids_per_offer: int | None
    smart_trader_excluded_collections: list[str]
    smart_trader_excluded_models: list[str]
    smart_trader_excluded_backdrops: list[str]
    smart_trader_attribute_collection_id: str | None


class SettingsUpdate(BaseModel):
    automation_enabled: bool | None = None
    mode: AutomationMode | None = None
    default_min_step: Decimal | None = Field(default=None, gt=0)
    confirm_live: bool = False
    smart_trader_enabled: bool | None = None
    smart_trader_min_spread_percent: Decimal | None = Field(default=None, ge=0, le=100)
    smart_trader_max_rebids_per_offer: int | None = Field(default=None, ge=0, le=100000)
    smart_trader_excluded_collections: list[str] | None = None
    smart_trader_excluded_models: list[str] | None = None
    smart_trader_excluded_backdrops: list[str] | None = None
    smart_trader_attribute_collection_id: str | None = Field(default=None, max_length=64)

    @field_validator(
        "smart_trader_excluded_collections",
        "smart_trader_excluded_models",
        "smart_trader_excluded_backdrops",
    )
    @classmethod
    def _clean_trader_exclusions(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return sorted({item.strip() for item in value if item and item.strip()})


class EmergencyStopRequest(BaseModel):
    enabled: bool
    reason: str | None = Field(default=None, max_length=255)
    cancel_offers: bool = False


class NotificationSettingsOut(BaseModel):
    in_app_enabled: bool
    telegram_enabled: bool
    telegram_chat_id: str | None
    events: dict[str, Any]
    min_interval_seconds: int
    max_per_hour: int


class NotificationSettingsUpdate(BaseModel):
    in_app_enabled: bool | None = None
    telegram_enabled: bool | None = None
    telegram_chat_id: str | None = Field(default=None, max_length=64)
    events: dict[str, bool] | None = None
    min_interval_seconds: int | None = Field(default=None, ge=0, le=86400)
    max_per_hour: int | None = Field(default=None, ge=1, le=1000)


class NotificationOut(BaseModel):
    id: str
    level: str
    event: str
    title: str
    message: str
    read_at: datetime | None
    created_at: datetime


class DashboardSummary(BaseModel):
    api_status: str
    api_message: str | None
    api_last_check: datetime | None
    worker_state: str
    worker_last_tick: datetime | None
    mode: str
    automation_enabled: bool
    emergency_stop: bool
    active_rules: int
    paused_rules: int
    error_rules: int
    active_offers: int
    first_place_confirmed: int
    outbid_offers: int
    limit_reached_offers: int
    insufficient_funds_offers: int
    unknown_position_offers: int
    balance: str | None
    frozen_funds: str | None
    balance_source: str
    queue: dict[str, int]
    rate_limit: dict[str, Any] | None
    throughput: dict[str, Any] | None
    recent_events: list[HistoryEntryOut]


class SystemStatus(BaseModel):
    app_version: str
    environment: str
    database: str
    portals_reachable: bool
    credential_status: str | None
    credential_hint: str | None
    requests_total: int
    errors_total: int
    rate_limited_total: int
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error_message: str | None
    remaining_limit: int | None
    limit_per_second: int | None
    worker: dict[str, Any]
    queue: dict[str, int]
    offers_synced_at: datetime | None
    unsynced_offers: int


class MessageOut(BaseModel):
    ok: bool = True
    message: str


class DryRunPreview(BaseModel):
    rule_id: str
    action: str
    status: str
    reason: str
    target_price: str | None
    cap: str | None
    floor_price: str | None
    competitor_amount: str | None
    own_amount: str | None
    own_rank: int | None
    total_offers: int
    detail: dict[str, Any]
