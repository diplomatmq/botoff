from enum import StrEnum


class ScopeMode(StrEnum):
    COLLECTION = "collection"
    MODELS = "models"


class Strategy(StrEnum):
    FIXED = "fixed"
    FLOOR_RELATIVE = "floor_relative"
    HOLD_FIRST_PLACE = "hold_first_place"
    MODELS_ONLY = "models_only"
    SAFE_PAUSE = "safe_pause"


class RuleState(StrEnum):
    DISABLED = "disabled"
    DRY_RUN = "dry_run"
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class OnLimitBehavior(StrEnum):
    KEEP = "keep"
    PAUSE = "pause"
    CANCEL = "cancel"


class CredentialStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    INVALID = "invalid"


class OfferStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELED = "canceled"
    UNKNOWN = "unknown"


class PositionStatus(StrEnum):
    FIRST_CONFIRMED = "FIRST_CONFIRMED"
    OUTBID = "OUTBID"
    LIMIT_REACHED = "LIMIT_REACHED"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    DATA_INCOMPLETE = "DATA_INCOMPLETE"
    STALE_DATA = "STALE_DATA"
    API_ERROR = "API_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    ATTRIBUTE_OFFERS_UNAVAILABLE = "ATTRIBUTE_OFFERS_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class OperationType(StrEnum):
    CREATE_OFFER = "create_offer"
    UPDATE_OFFER = "update_offer"
    CANCEL_OFFER = "cancel_offer"
    SYNC_OFFER = "sync_offer"
    ACCEPT_OFFER = "accept_offer"


class OperationState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    RETRY = "retry"
    DEAD = "dead"
    CANCELLED = "cancelled"


class AutomationMode(StrEnum):
    DRY_RUN = "dry_run"
    LIVE = "live"


class AuditAction(StrEnum):
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    PASSWORD_CHANGED = "password_changed"
    CREDENTIAL_CREATED = "credential_created"
    CREDENTIAL_REPLACED = "credential_replaced"
    CREDENTIAL_DISABLED = "credential_disabled"
    CREDENTIAL_CHECKED = "credential_checked"
    RULE_CREATED = "rule_created"
    RULE_UPDATED = "rule_updated"
    RULE_DELETED = "rule_deleted"
    RULE_STATE_CHANGED = "rule_state_changed"
    OFFER_CREATED = "offer_created"
    OFFER_UPDATED = "offer_updated"
    OFFER_CANCELLED = "offer_cancelled"
    OFFER_ACCEPTED = "offer_accepted"
    SETTINGS_UPDATED = "settings_updated"
    EMERGENCY_STOP = "emergency_stop"
    EMERGENCY_STOP_RELEASED = "emergency_stop_released"
    MODE_CHANGED = "mode_changed"
