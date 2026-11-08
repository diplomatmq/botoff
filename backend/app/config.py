from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.secrets_store import apply_generated_secrets


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Portals Auto-Order Manager"
    environment: str = "production"
    debug: bool = False
    log_level: str = "INFO"

    database_url: str = "sqlite+aiosqlite:///./data/portals.db"
    db_echo: bool = False
    auto_create_schema: bool = False

    secret_key: str = ""
    encryption_key: str = ""
    secrets_file: str = "data/secrets.json"
    session_ttl_hours: int = 72
    cookie_secure: bool = False
    cookie_domain: str | None = None
    cors_origins: str = ""
    trust_proxy_headers: bool = False

    admin_username: str = "admin"
    admin_password: str = "admin"
    allow_registration: bool = False

    portals_base_url: str = "https://portal-market.com/partners"
    portals_api_token: str = ""
    portals_timeout_seconds: float = 30.0
    portals_max_retries: int = 4
    portals_backoff_base_seconds: float = 1.5
    portals_default_rps: int = 1
    rate_limit_safety_margin: float = 0.05

    min_offer_amount: Decimal = Decimal("0.5")
    price_quantum: Decimal = Decimal("0.00001")

    default_check_interval_seconds: int = 60
    min_check_interval_seconds: int = 5

    worker_enabled: bool = True
    worker_poll_interval_seconds: float = 2.0
    worker_lease_seconds: int = 120
    worker_max_concurrency: int = 2
    operation_max_attempts: int = 5

    scheduler_target_utilization: float = 0.7

    telegram_bot_token: str = ""
    telegram_default_chat_id: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    apply_generated_secrets(settings)
    return settings
