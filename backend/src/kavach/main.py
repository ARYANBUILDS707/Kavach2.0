"""Application factory; import does not load models or connect to external services."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from kavach.api.routes.auth import router as auth_router
from kavach.api.routes.health import router as health_router
from kavach.auth.cookies import cookie_policy_for
from kavach.auth.passwords import PasswordService
from kavach.auth.service import AuthService, SessionPolicy
from kavach.auth.throttle import LoginThrottle
from kavach.core.clock import Clock, utc_now
from kavach.core.config import Settings, parse_audit_keys
from kavach.core.errors import ApiError, api_error, http_error, unexpected_error, validation_error
from kavach.core.redis_client import create_redis_client
from kavach.db.engine import create_db_engine, create_session_factory
from kavach.privacy.audit import AuditWriter


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    if app.state.db_engine is not None:
        app.state.db_engine.dispose()
    if app.state.redis is not None:
        app.state.redis.close()


def build_auth_service(settings: Settings, app: FastAPI, clock: Clock) -> AuthService:
    # Settings guarantees the whole group is present whenever APP_ORIGIN is set.
    if (
        app.state.db_sessions is None
        or app.state.redis is None
        or settings.rate_limit_hmac_key is None
        or settings.audit_hmac_keys is None
        or settings.audit_hmac_active_version is None
    ):
        raise RuntimeError("Incomplete authentication configuration")
    return AuthService(
        sessions=app.state.db_sessions,
        passwords=PasswordService(),
        throttle=LoginThrottle(
            app.state.redis,
            settings.rate_limit_hmac_key.get_secret_value().encode(),
            namespace=settings.app_env,
        ),
        audit=AuditWriter(
            parse_audit_keys(settings.audit_hmac_keys),
            settings.audit_hmac_active_version,
            timedelta(days=settings.audit_retention_days),
        ),
        policy=SessionPolicy(
            idle=timedelta(minutes=settings.session_idle_minutes),
            absolute=timedelta(hours=settings.session_max_hours),
        ),
        clock=clock,
    )


def create_app(settings: Settings | None = None, *, clock: Clock = utc_now) -> FastAPI:
    settings = settings or Settings()
    logging.getLogger("kavach").setLevel(settings.log_level)
    app = FastAPI(
        title="KAVACH V4 Backend",
        version="0.1.0",
        description="Foundation only. Liveness does not imply fraud-analysis readiness.",
        docs_url="/docs" if settings.app_env != "pilot" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.app_env != "pilot" else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    # Clients are created lazily; liveness never depends on PostgreSQL or Redis.
    app.state.db_engine = create_db_engine(settings.database_url) if settings.database_url else None
    app.state.db_sessions = (
        create_session_factory(app.state.db_engine) if app.state.db_engine is not None else None
    )
    app.state.redis = create_redis_client(settings.redis_url) if settings.redis_url else None
    # Without the full authentication configuration the auth routes answer 503.
    app.state.auth = build_auth_service(settings, app, clock) if settings.app_origin else None
    app.state.cookie_policy = (
        cookie_policy_for(settings.app_origin) if settings.app_origin else None
    )

    @app.middleware("http")
    async def request_metadata(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = uuid4()
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        response.headers["Cache-Control"] = "no-store"
        return response

    app.add_exception_handler(ApiError, api_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(Exception, unexpected_error)
    app.include_router(health_router)
    app.include_router(auth_router)
    return app
