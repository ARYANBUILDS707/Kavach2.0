"""Application factory; import does not load models or connect to external services."""

import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from kavach.api.routes.health import router as health_router
from kavach.core.config import Settings
from kavach.core.errors import http_error, unexpected_error, validation_error


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
    )
    app.state.settings = settings

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
