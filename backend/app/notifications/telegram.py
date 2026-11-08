from __future__ import annotations

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger("portals.telegram")


async def send_message(chat_id: str, text: str) -> bool:
    settings = get_settings()
    if not settings.telegram_bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            )
        if response.status_code >= 400:
            logger.warning("telegram send failed: %s", response.status_code)
            return False
        return True
    except httpx.HTTPError as exc:
        logger.warning("telegram send error: %s", exc)
        return False
