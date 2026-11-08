from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    admin,
    auth,
    collections,
    credentials,
    dashboard,
    events,
    history,
    notifications,
    offers,
    operations,
    rules,
    settings as settings_api,
    system,
)
from app.bootstrap import bootstrap
from app.config import get_settings
from app.db import SessionLocal, create_schema
from app.logging_config import configure_logging
from app.portals.client import close_http_client
from app.portals.errors import PortalsError

logger = logging.getLogger("portals.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.auto_create_schema:
        await create_schema()
    async with SessionLocal() as session:
        try:
            await bootstrap(session)
            await session.commit()
        except Exception:  # noqa: BLE001
            await session.rollback()
            logger.exception("bootstrap failed")
    logger.info("api started (environment=%s, debug=%s)", settings.environment, settings.debug)
    yield
    await close_http_client()
    logger.info("api stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=system.APP_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.debug else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.debug else None,
    )

    origins = settings.cors_origin_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.exception_handler(PortalsError)
    async def portals_error_handler(request: Request, exc: PortalsError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"detail": str(exc), "code": exc.code, "status": exc.status},
        )

    for router in (
        auth.router,
        admin.router,
        credentials.router,
        collections.router,
        rules.router,
        offers.router,
        operations.router,
        history.router,
        settings_api.router,
        notifications.router,
        dashboard.router,
        system.router,
        events.router,
    ):
        app.include_router(router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
