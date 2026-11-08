from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_settings = get_settings()

_SQLITE_PREFIX = "sqlite+aiosqlite:///"


def _sqlite_path(url: str) -> Path | None:
    if not url.startswith(_SQLITE_PREFIX):
        return None
    raw = url[len(_SQLITE_PREFIX) :]
    if not raw or raw == ":memory:":
        return None
    return Path(raw)


_db_path = _sqlite_path(_settings.database_url)
if _db_path is not None:
    _db_path.parent.mkdir(parents=True, exist_ok=True)

engine: AsyncEngine = create_async_engine(
    _settings.database_url,
    echo=_settings.db_echo,
    pool_pre_ping=True,
    future=True,
)


if _db_path is not None:

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def create_schema() -> None:
    from app import models

    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)


async def drop_schema() -> None:
    from app import models

    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.drop_all)
