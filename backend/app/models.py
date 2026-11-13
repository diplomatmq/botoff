import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

MONEY = Numeric(38, 12)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
        nullable=False,
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    csrf_token: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiCredential(Base, TimestampMixin):
    __tablename__ = "api_credentials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(64), default="default", nullable=False)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_hint: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False, index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sender_id: Mapped[int | None] = mapped_column(Integer)
    rate_limit_per_second: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_check_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_check_message: Mapped[str | None] = mapped_column(String(512))


class ApiRequestState(Base):
    __tablename__ = "api_request_state"

    credential_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("api_credentials.id", ondelete="CASCADE"), primary_key=True
    )
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_request_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    limit_per_second: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    total_requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_rate_limited: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_message: Mapped[str | None] = mapped_column(String(512))
    remaining_hint: Mapped[int | None] = mapped_column(Integer)
    limit_hint: Mapped[int | None] = mapped_column(Integer)


class CollectionCache(Base, TimestampMixin):
    __tablename__ = "collections_cache"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    short_name: Mapped[str | None] = mapped_column(String(128), index=True)
    photo_url: Mapped[str | None] = mapped_column(Text)
    floor_price: Mapped[Decimal | None] = mapped_column(MONEY)
    max_offer: Mapped[Decimal | None] = mapped_column(MONEY)
    supply: Mapped[int | None] = mapped_column(Integer)
    day_volume: Mapped[Decimal | None] = mapped_column(MONEY)
    market_cap: Mapped[Decimal | None] = mapped_column(MONEY)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    zero_commission: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cashback_percent: Mapped[Decimal | None] = mapped_column(MONEY)
    points_multiplier: Mapped[Decimal | None] = mapped_column(MONEY)
    offers_supported: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    models: Mapped[list["ModelCache"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan", lazy="selectin"
    )


class ModelCache(Base, TimestampMixin):
    __tablename__ = "models_cache"
    __table_args__ = (UniqueConstraint("collection_id", "name", name="uq_models_collection_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections_cache.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    photo_url: Mapped[str | None] = mapped_column(Text)
    floor_price: Mapped[Decimal | None] = mapped_column(MONEY)
    max_offer: Mapped[Decimal | None] = mapped_column(MONEY)
    source: Mapped[str] = mapped_column(String(32), default="attribute_floors", nullable=False)

    collection: Mapped[CollectionCache] = relationship(back_populates="models")


class AutomationRule(Base, TimestampMixin):
    __tablename__ = "automation_rules"
    __table_args__ = (
        Index("ix_rules_active_state", "state", "enabled"),
        Index("ix_rules_user_collection", "user_id", "collection_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("api_credentials.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections_cache.id", ondelete="CASCADE"), nullable=False, index=True
    )
    collection_name: Mapped[str | None] = mapped_column(String(255))

    scope_mode: Mapped[str] = mapped_column(String(16), default="collection", nullable=False)
    models: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    backdrops: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    excluded_backdrops: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    symbols: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    scope_guard: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    strategy: Mapped[str] = mapped_column(String(24), default="floor_relative", nullable=False)
    hold_first_place: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pause_on_uncertainty: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    discount_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=Decimal("0"), nullable=False)
    max_price_percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    fixed_price: Mapped[Decimal | None] = mapped_column(MONEY)
    min_step: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00001"), nullable=False)
    max_price_per_offer: Mapped[Decimal | None] = mapped_column(MONEY)
    max_budget: Mapped[Decimal | None] = mapped_column(MONEY)
    max_active_offers: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_nfts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    expiration_days: Mapped[int | None] = mapped_column(Integer)

    check_interval_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="disabled", nullable=False, index=True)
    on_limit_behavior: Mapped[str] = mapped_column(String(16), default="keep", nullable=False)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_position_status: Mapped[str | None] = mapped_column(String(32))
    last_decision: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    locked_by: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    offers: Mapped[list["ManagedOffer"]] = relationship(
        back_populates="rule", passive_deletes=True, lazy="selectin"
    )


class ManagedOffer(Base, TimestampMixin):
    __tablename__ = "managed_offers"
    __table_args__ = (
        UniqueConstraint("external_offer_id", name="uq_managed_offers_external"),
        Index("ix_managed_offers_rule_status", "rule_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("api_credentials.id", ondelete="SET NULL")
    )

    external_offer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(16), default="broad", nullable=False)

    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    max_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    max_nfts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    current_nfts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expiration_days: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    position_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN", nullable=False)
    position_rank: Mapped[int | None] = mapped_column(Integer)
    last_action: Mapped[str | None] = mapped_column(String(64))
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    rule: Mapped[AutomationRule] = relationship(back_populates="offers")


class PurchasedGift(Base, TimestampMixin):
    __tablename__ = "purchased_gifts"
    __table_args__ = (
        UniqueConstraint("offer_id", "purchase_key", name="uq_purchased_gift_event"),
        Index("ix_purchased_gifts_user_purchased_at", "user_id", "purchased_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("managed_offers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    gift_id: Mapped[str | None] = mapped_column(String(128))
    purchase_key: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class OperationQueue(Base, TimestampMixin):
    __tablename__ = "operation_queue"
    __table_args__ = (
        Index(
            "uq_operation_dedupe_active",
            "dedupe_key",
            unique=True,
            postgresql_where=text("state in ('pending', 'running', 'retry')"),
            sqlite_where=text("state in ('pending', 'running', 'retry')"),
        ),
        Index("ix_operations_state_schedule", "state", "scheduled_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="CASCADE"), index=True
    )
    offer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("managed_offers.id", ondelete="SET NULL"), index=True
    )

    operation_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False)

    state: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    requires_verification: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    locked_by: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    attempts_log: Mapped[list["OperationAttempt"]] = relationship(
        back_populates="operation", cascade="all, delete-orphan", lazy="selectin"
    )


class OperationAttempt(Base):
    __tablename__ = "operation_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    operation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("operation_queue.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    request_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    operation: Mapped[OperationQueue] = relationship(back_populates="attempts_log")


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(16), default="broad", nullable=False)
    floor_price: Mapped[Decimal | None] = mapped_column(MONEY)
    best_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    offers_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    offers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class AccountBudgetState(Base):
    __tablename__ = "account_budget_state"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    balance: Mapped[Decimal | None] = mapped_column(MONEY)
    frozen_funds: Mapped[Decimal | None] = mapped_column(MONEY)
    available: Mapped[Decimal | None] = mapped_column(MONEY)
    source: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    reserved_by_rules: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor: Mapped[str] = mapped_column(String(64), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(48))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class NotificationSettings(Base, TimestampMixin):
    __tablename__ = "notification_settings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    events: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    min_interval_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    max_per_hour: Mapped[int] = mapped_column(Integer, default=60, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    event: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class ApplicationSetting(Base):
    __tablename__ = "application_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UserSetting(Base, TimestampMixin):
    """Per-user override of an application setting.

    Falls back to ``application_settings`` and then to ``DEFAULTS`` when absent,
    so each account keeps its own automation and trader configuration.
    """

    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
