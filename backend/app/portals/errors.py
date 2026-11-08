from __future__ import annotations

from typing import Any


class PortalsError(Exception):
    def __init__(self, message: str, *, status: int | None = None, code: str | None = None, payload: Any = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.payload = payload

    def __str__(self) -> str:
        prefix = f"[{self.status} {self.code}] " if self.status or self.code else ""
        return f"{prefix}{self.message}"


class PortalsAuthError(PortalsError):
    pass


class PortalsRateLimited(PortalsError):
    def __init__(self, message: str, *, retry_after: float = 1.0, status: int = 429, code: str | None = None):
        super().__init__(message, status=status, code=code)
        self.retry_after = retry_after


class PortalsValidationError(PortalsError):
    pass


class PortalsNotFoundError(PortalsError):
    pass


class PortalsServerError(PortalsError):
    pass


class PortalsNetworkError(PortalsError):
    pass


class PortalsUnavailableError(PortalsError):
    pass


CREDENTIAL_ERROR_CODES = {
    "PARTNER_INVALID_KEY",
    "PARTNER_KEY_DISABLED",
    "PARTNER_USER_BANNED",
    "PARTNER_SUBSCRIPTION_REQUIRED",
    "PARTNER_SUBSCRIPTION_EXPIRED",
}

CREDENTIAL_ERROR_MESSAGES = {
    "PARTNER_INVALID_KEY": "Ключ не существует или был перевыпущен.",
    "PARTNER_KEY_DISABLED": "Ключ отключён.",
    "PARTNER_USER_BANNED": "Аккаунт заблокирован.",
    "PARTNER_SUBSCRIPTION_REQUIRED": "Тариф не выбран — выберите тариф на странице Partner API.",
    "PARTNER_SUBSCRIPTION_EXPIRED": "Подписка истекла после неудачного продления.",
}


def is_trait_unavailable(error: PortalsError) -> bool:
    if error.status != 403:
        return False
    if error.code in CREDENTIAL_ERROR_CODES:
        return False
    text = (error.message or "").lower()
    return "attribute" in text or "trait" in text
