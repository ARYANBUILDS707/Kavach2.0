"""Application factory; import does not load models or connect to external services."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from kavach.api.routes.health import router as health_router
from kavach.core.config import Settings
from kavach.core.errors import http_error, unexpected_error, validation_error
from kavach.core.redis_client import create_redis_client
from kavach.db.engine import create_db_engine, create_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    if app.state.db_engine is not None:
        app.state.db_engine.dispose()
    if app.state.redis is not None:
        app.state.redis.close()


def create_app(settings: Settings | None = None) -> FastAPI:
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

    @app.middleware("http")
    async def request_metadata(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = uuid4()
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        response.headers["Cache-Control"] = "no-store"
        return response

    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(Exception, unexpected_error)
    app.include_router(health_router)
    return app
