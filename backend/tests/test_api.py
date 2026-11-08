from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ApiCredential, AutomationRule, CollectionCache, NotificationSettings, User
from app.security import hash_password

RULE_PAYLOAD = {
    "name": "Тестовое правило",
    "collection_id": "col-test",
    "strategy": "hold_first_place",
    "hold_first_place": True,
    "discount_percent": "0",
    "min_step": "0.00001",
    "max_nfts": 1,
    "check_interval_seconds": 60,
    "state": "disabled",
}


async def _add_collection(collection_id: str = "col-test") -> None:
    async with SessionLocal() as session:
        session.add(CollectionCache(id=collection_id, name="Test Collection", offers_supported=True))
        await session.commit()


async def test_protected_endpoint_requires_auth(client):
    response = await client.get("/api/rules")
    assert response.status_code == 401


async def test_login_rejects_wrong_password(client):
    response = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "nope"}
    )
    assert response.status_code == 401


async def test_login_returns_csrf_and_session(client):
    response = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin-password-123"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == "admin"
    assert body["csrf_token"]
    assert "portals_session" in client.cookies


async def test_admin_can_create_and_disable_user(auth_client):
    created = await auth_client.post(
        "/api/admin/users",
        json={
            "username": "operator",
            "password": "operator-password-123",
            "telegram_chat_id": "123456",
            "telegram_enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["username"] == "operator"
    assert body["telegram_chat_id"] == "123456"
    assert body["is_admin"] is False

    updated = await auth_client.patch(
        f"/api/admin/users/{body['id']}",
        json={"telegram_chat_id": "654321", "telegram_enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["telegram_chat_id"] == "654321"
    assert updated.json()["telegram_enabled"] is False

    disabled = await auth_client.delete(f"/api/admin/users/{body['id']}")
    assert disabled.status_code == 200
    users = (await auth_client.get("/api/admin/users")).json()
    assert next(user for user in users if user["id"] == body["id"])["is_active"] is False

    async with SessionLocal() as session:
        settings = (
            await session.execute(
                select(NotificationSettings).where(NotificationSettings.user_id == UUID(body["id"]))
            )
        ).scalar_one()
        assert settings.telegram_chat_id == "654321"


async def test_non_admin_cannot_use_admin_api(auth_client, client):
    async with SessionLocal() as session:
        user = User(
            username="operator",
            password_hash=hash_password("operator-password-123"),
            is_admin=False,
            is_active=True,
        )
        session.add(user)
        await session.commit()

    await client.post("/api/auth/logout")
    response = await client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "operator-password-123"},
    )
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    assert (await client.get("/api/admin/users")).status_code == 403


async def test_mutation_without_csrf_is_rejected(client):
    await client.post("/api/auth/login", json={"username": "admin", "password": "admin-password-123"})
    response = await client.post("/api/settings/emergency-stop", json={"enabled": True})
    assert response.status_code == 403


async def test_rule_creation_requires_known_collection(auth_client):
    response = await auth_client.post("/api/rules", json=RULE_PAYLOAD)
    assert response.status_code == 400


async def test_rule_crud_roundtrip(auth_client):
    await _add_collection()
    created = await auth_client.post("/api/rules", json=RULE_PAYLOAD)
    assert created.status_code == 201, created.text
    rule = created.json()
    assert rule["collection_name"] == "Test Collection"
    assert rule["enabled"] is False

    listed = await auth_client.get("/api/rules")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = await auth_client.put(
        f"/api/rules/{rule['id']}", json={**RULE_PAYLOAD, "name": "Обновлённое"}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Обновлённое"

    deleted = await auth_client.delete(f"/api/rules/{rule['id']}")
    assert deleted.status_code == 200
    assert (await auth_client.get("/api/rules")).json() == []


async def test_rules_are_isolated_between_users(auth_client):
    async with SessionLocal() as session:
        other = User(username="intruder", password_hash="x", is_admin=False)
        session.add(other)
        await session.flush()
        session.add(CollectionCache(id="col-test", name="Test Collection"))
        await session.flush()
        foreign = AutomationRule(
            user_id=other.id,
            name="Чужое правило",
            collection_id="col-test",
            models=[],
            backdrops=[],
            symbols=[],
            discount_percent=Decimal("0"),
            min_step=Decimal("0.00001"),
        )
        session.add(foreign)
        await session.commit()
        foreign_id = str(foreign.id)

    listed = await auth_client.get("/api/rules")
    assert listed.json() == []
    assert (await auth_client.get(f"/api/rules/{foreign_id}")).status_code == 404
    assert (await auth_client.delete(f"/api/rules/{foreign_id}")).status_code == 404


async def test_live_mode_requires_explicit_confirmation(auth_client):
    response = await auth_client.put("/api/settings", json={"mode": "live"})
    assert response.status_code == 400

    confirmed = await auth_client.put(
        "/api/settings", json={"mode": "live", "confirm_live": True}
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["mode"] == "live"


async def test_emergency_stop_blocks_automation(auth_client):
    await auth_client.put("/api/settings", json={"automation_enabled": True})
    response = await auth_client.post(
        "/api/settings/emergency-stop", json={"enabled": True, "reason": "тест"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["emergency_stop"] is True
    assert body["automation_enabled"] is False
    assert body["emergency_stop_reason"] == "тест"

    activate = await auth_client.put("/api/settings", json={"automation_enabled": True})
    assert activate.status_code == 400


async def test_credential_token_is_stored_encrypted(auth_client):
    token = "prt_live_abcdefghij0123456789"
    response = await auth_client.post(
        "/api/credentials", json={"token": token, "label": "main", "rate_limit_per_second": 1}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["token_hint"] != token
    assert token not in body["token_hint"]

    async with SessionLocal() as session:
        stored = (await session.execute(select(ApiCredential))).scalars().one()
        assert stored.encrypted_token != token
        assert token not in stored.encrypted_token


async def test_response_never_leaks_api_token(auth_client):
    token = "prt_live_secret_do_not_leak"
    await auth_client.post("/api/credentials", json={"token": token, "label": "main"})
    listed = await auth_client.get("/api/credentials")
    assert token not in listed.text
    history = await auth_client.get("/api/history")
    assert token not in history.text


async def test_dashboard_and_system_status(auth_client):
    dashboard = await auth_client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["mode"] in {"dry_run", "live"}

    status = await auth_client.get("/api/system/status")
    assert status.status_code == 200
    assert status.json()["database"] == "ok"
