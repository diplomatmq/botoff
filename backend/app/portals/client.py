from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.portals.errors import (
    CREDENTIAL_ERROR_CODES,
    CREDENTIAL_ERROR_MESSAGES,
    PortalsAuthError,
    PortalsError,
    PortalsNetworkError,
    PortalsNotFoundError,
    PortalsRateLimited,
    PortalsServerError,
    PortalsUnavailableError,
    PortalsValidationError,
)
from app.portals.rate_limiter import RateLimiter
from app.security import sanitize_payload

logger = logging.getLogger("portals.client")

_http_client: httpx.AsyncClient | None = None
_http_lock = asyncio.Lock()


async def get_http_client(settings: Settings) -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        async with _http_lock:
            if _http_client is None:
                _http_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(settings.portals_timeout_seconds),
                    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                    headers={"User-Agent": "portals-autoorder/1.0"},
                )
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


@dataclass(slots=True)
class CredentialContext:
    credential_id: uuid.UUID
    token: str
    rate_limit_per_second: int = 1


class PortalsClient:
    def __init__(
        self,
        credential: CredentialContext,
        *,
        rate_limiter: RateLimiter,
        settings: Settings | None = None,
    ) -> None:
        self.credential = credential
        self.rate_limiter = rate_limiter
        self.settings = settings or get_settings()
        self.last_rate_limit_headers: dict[str, int | None] = {}

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        retries: int | None = None,
        idempotent: bool = True,
    ) -> Any:
        attempts = retries if retries is not None else self.settings.portals_max_retries
        attempts = max(1, attempts)
        url = f"{self.settings.portals_base_url.rstrip('/')}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"partners {self.credential.token}",
            "Accept": "application/json",
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        clean_params = {k: v for k, v in (params or {}).items() if v is not None}

        last_error: PortalsError | None = None
        for attempt in range(1, attempts + 1):
            await self.rate_limiter.acquire(self.credential.credential_id, self.credential.rate_limit_per_second)
            started = time.perf_counter()
            try:
                client = await get_http_client(self.settings)
                response = await client.request(
                    method, url, params=clean_params or None, json=json_body, headers=headers
                )
            except httpx.TimeoutException as exc:
                last_error = PortalsNetworkError(f"Тайм-аут запроса к Portals: {exc}")
                await self.rate_limiter.report_error(self.credential.credential_id, "timeout")
                if attempt < attempts:
                    await self._backoff(attempt)
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                last_error = PortalsNetworkError(f"Сетевая ошибка при обращении к Portals: {exc}")
                await self.rate_limiter.report_error(self.credential.credential_id, "network error")
                if attempt < attempts:
                    await self._backoff(attempt)
                    continue
                raise last_error from exc

            duration_ms = int((time.perf_counter() - started) * 1000)
            self._capture_rate_headers(response)
            outcome = self._handle_response(response, json_body)

            if isinstance(outcome, PortalsRateLimited):
                await self.rate_limiter.report_error(
                    self.credential.credential_id, "rate limited", rate_limited=True
                )
                await self.rate_limiter.block_for(self.credential.credential_id, outcome.retry_after)
                last_error = outcome
                if attempt < attempts:
                    await asyncio.sleep(min(outcome.retry_after, 10.0))
                    continue
                raise outcome

            if isinstance(outcome, PortalsError):
                retryable = isinstance(outcome, (PortalsServerError, PortalsUnavailableError))
                await self.rate_limiter.report_error(self.credential.credential_id, str(outcome))
                last_error = outcome
                if retryable and idempotent and attempt < attempts:
                    await self._backoff(attempt)
                    continue
                raise outcome

            await self.rate_limiter.report_success(
                self.credential.credential_id,
                remaining=self.last_rate_limit_headers.get("remaining"),
                limit=self.last_rate_limit_headers.get("limit"),
            )
            logger.debug(
                "portals %s %s -> %s (%d ms)",
                method,
                path,
                response.status_code,
                duration_ms,
                extra={"sanitized_body": sanitize_payload(json_body)},
            )
            return outcome

        raise last_error or PortalsServerError("Не удалось выполнить запрос к Portals")

    def _capture_rate_headers(self, response: httpx.Response) -> None:
        def as_int(name: str) -> int | None:
            raw = response.headers.get(name)
            if raw is None:
                return None
            try:
                return int(float(raw))
            except ValueError:
                return None

        self.last_rate_limit_headers = {
            "limit": as_int("X-RateLimit-Limit"),
            "remaining": as_int("X-RateLimit-Remaining"),
            "reset": as_int("X-RateLimit-Reset"),
        }

    def _handle_response(self, response: httpx.Response, request_body: dict | None) -> Any:
        status = response.status_code
        if status in (204, 205):
            return None

        payload: Any = None
        if response.content:
            try:
                payload = response.json()
            except ValueError:
                payload = {"message": response.text[:500]}

        if 200 <= status < 300:
            return payload

        message = ""
        code = None
        if isinstance(payload, dict):
            message = str(payload.get("message") or payload.get("error") or "")
            code = payload.get("code")
        if not message:
            message = f"HTTP {status}"

        if status == 429:
            retry_after = 1.0
            header = response.headers.get("Retry-After")
            if header:
                try:
                    retry_after = float(header)
                except ValueError:
                    retry_after = 1.0
            elif self.last_rate_limit_headers.get("reset") is not None:
                retry_after = float(self.last_rate_limit_headers["reset"] or 1)
            return PortalsRateLimited(
                "Достигнут лимит запросов к Portals", retry_after=retry_after, code=code or "RATE_LIMITED"
            )

        if status == 401:
            return PortalsAuthError(
                CREDENTIAL_ERROR_MESSAGES.get(code or "", message),
                status=status,
                code=code or "PARTNER_INVALID_KEY",
                payload=sanitize_payload(payload),
            )

        if status == 403:
            if code in CREDENTIAL_ERROR_CODES:
                return PortalsAuthError(
                    CREDENTIAL_ERROR_MESSAGES.get(code, message), status=status, code=code, payload=sanitize_payload(payload)
                )
            return PortalsError(message, status=status, code=code, payload=sanitize_payload(payload))

        if status == 404:
            return PortalsNotFoundError(message, status=status, code=code, payload=sanitize_payload(payload))

        if status == 503:
            return PortalsUnavailableError(message, status=status, code=code, payload=sanitize_payload(payload))

        if 500 <= status < 600:
            return PortalsServerError(message, status=status, code=code, payload=sanitize_payload(payload))

        return PortalsValidationError(message, status=status, code=code, payload=sanitize_payload(payload))

    async def _backoff(self, attempt: int) -> None:
        base = self.settings.portals_backoff_base_seconds * (2 ** (attempt - 1))
        await asyncio.sleep(min(base, 15.0) + random.uniform(0, 0.3))


class PortalsGateway:
    def __init__(self, client: PortalsClient) -> None:
        self.client = client

    async def market_config(self) -> dict:
        return await self.client.request("GET", "/market/config")

    async def wallet(self) -> dict:
        return await self.client.request("GET", "/users/wallets/")

    async def collections_preview(self, sort_by: str | None = None, sort_order: str | None = None) -> dict:
        return await self.client.request(
            "GET", "/collections/preview", params={"sort_by": sort_by, "sort_order": sort_order}
        )

    async def offer_collections(self) -> dict:
        return await self.client.request("GET", "/collection-offers/collections")

    async def collection_floors(self) -> dict:
        return await self.client.request("GET", "/collections/floors")

    async def attribute_floors(self) -> dict:
        return await self.client.request("GET", "/collections/attribute-floors")

    async def backdrop_floors(self) -> dict:
        return await self.client.request("GET", "/collections/backdrops/floors")

    async def model_background_floors(self, models: list[str] | None = None) -> dict:
        names = [str(model).strip() for model in models or [] if str(model).strip()]
        return await self.client.request(
            "GET",
            "/collections/models/backgrounds/floors",
            params={"models": ",".join(names)} if names else None,
        )

    async def top_offer(self, collection_id: str, scope: str | None = None) -> dict | None:
        return await self.client.request(
            "GET", f"/collection-offers/{collection_id}/top", params={"scope": scope}, retries=2
        )

    async def offers_all(self, collection_id: str, scope: str | None = None, limit: int = 10) -> dict:
        return await self.client.request(
            "GET",
            f"/collection-offers/{collection_id}/all",
            params={"scope": scope, "limit": min(10, max(1, limit))},
            retries=2,
        )

    async def owned_nfts(self, collection_id: str, *, limit: int = 100, offset: int = 0) -> dict:
        return await self.client.request(
            "GET",
            "/nfts/owned",
            params={
                "collection_id": collection_id,
                "limit": min(100, max(1, limit)),
                "offset": max(0, offset),
            },
        )

    async def create_offer(
        self,
        *,
        collection_id: str,
        amount: str,
        max_nfts: int,
        attributes: list[dict] | None = None,
        expiration_days: int | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "collection_id": collection_id,
            "amount": amount,
            "max_nfts": max_nfts,
        }
        if attributes:
            body["attributes"] = attributes
        if expiration_days is not None:
            body["expiration_days"] = expiration_days
        return await self.client.request("POST", "/collection-offers/", json_body=body, idempotent=False)

    async def bulk_update_offers(self, offers: list[dict]) -> dict:
        return await self.client.request(
            "POST", "/collection-offers/bulk/update", json_body={"offers": offers}, retries=2
        )

    async def cancel_offer(self, offer_id: str) -> None:
        return await self.client.request(
            "POST", "/collection-offers/cancel", json_body={"id": offer_id}, retries=2
        )

    async def accept_offer(self, offer_id: str) -> dict:
        return await self.client.request("POST", f"/collection-offers/{offer_id}/accept", retries=1)
