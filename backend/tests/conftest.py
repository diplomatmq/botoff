from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="portals-tests-"))

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ENCRYPTION_KEY"] = "test-encryption-key"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin-password-123"
os.environ["COOKIE_SECURE"] = "false"
os.environ["AUTO_CREATE_SCHEMA"] = "true"
os.environ["WORKER_ENABLED"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.bootstrap import bootstrap
from app.db import SessionLocal, create_schema, drop_schema, engine
from app.main import app

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin-password-123"


@pytest_asyncio.fixture
async def db():
    await drop_schema()
    await create_schema()
    async with SessionLocal() as session:
        await bootstrap(session)
        await session.commit()
    try:
        yield
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


@pytest_asyncio.fixture
async def auth_client(client):
    response = await client.post(
        "/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    client.headers["X-CSRF-Token"] = body["csrf_token"]
    yield client


@pytest_asyncio.fixture
async def session(db):
    async with SessionLocal() as db_session:
        yield db_session
