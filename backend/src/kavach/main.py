"""Application factory; import does not load models or connect to external services."""

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from kavach.api.routes.auth import router as auth_router
from kavach.api.routes.events import router as events_router
from kavach.api.routes.health import router as health_router
from kavach.api.routes.incidents import router as incidents_router
from kavach.api.routes.simulator import router as simulator_router
from kavach.api.routes.system import router as system_router
from kavach.auth.cookies import cookie_policy_for
from kavach.auth.ingest_keys import IngestKeyService
from kavach.auth.passwords import PasswordService
from kavach.auth.service import AuthService, SessionPolicy
from kavach.auth.throttle import (
    BearerAttemptThrottle,
    LoginThrottle,
    ReadQuota,
    SubmissionQuota,
)
from kavach.core.clock import Clock, utc_now
from kavach.core.config import SMS_COMMIT_RESERVE_SECONDS, Settings, parse_audit_keys, parse_key_map
from kavach.core.errors import ApiError, api_error, http_error, unexpected_error, validation_error
from kavach.core.redis_client import create_redis_client
from kavach.core.telemetry import operational_event
from kavach.correlation.candidates import CandidateIndex
from kavach.db.engine import create_db_engine, create_session_factory
from kavach.models.manifest import ManifestInvalid, load_manifest
from kavach.models.sms_worker import SmsWorkerConfig, SmsWorkerSupervisor, worker_command
from kavach.privacy.audit import AuditWriter
from kavach.privacy.digests import KeyedDigester
from kavach.services.incidents import IncidentReadService
from kavach.services.ingestion import IngestionService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Starts the SMS worker in the background (never blocks startup); a no-op when disabled.
    app.state.sms_worker.start()
    try:
        yield
    finally:
        app.state.sms_worker.close()
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


def build_sms_worker(settings: Settings) -> SmsWorkerSupervisor:
    """The SMS worker supervisor from settings (design §10). Disabled unless enabled.

    In `pilot` an unusable manifest, interpreter or model directory refuses startup; elsewhere
    the worker is `unverified` and every SMS is stored with the stage unavailable.
    """
    if not settings.sms_worker_enabled:
        return SmsWorkerSupervisor(None)
    python, model_dir, manifest_path = (
        settings.sms_worker_python,
        settings.model_dir,
        settings.model_manifest_path,
    )
    assert python is not None and model_dir is not None and manifest_path is not None
    problem = None
    try:
        manifest = load_manifest(manifest_path)
    except ManifestInvalid:
        problem = "manifest_invalid"
    if problem is None and not (python.is_file() and os.access(python, os.X_OK)):
        problem = "worker_python_missing"
    if problem is None and not model_dir.is_dir():
        problem = "model_dir_missing"
    if problem is not None:
        if settings.app_env == "pilot":
            raise RuntimeError(f"The SMS worker cannot start: {problem}")
        operational_event("sms_worker.unverified", problem, None)
        return SmsWorkerSupervisor.refused(problem)
    return SmsWorkerSupervisor(
        SmsWorkerConfig(
            command=worker_command(python, manifest_path, model_dir, settings.sms_worker_threads),
            lock_path=model_dir / ".kavach-sms-worker.lock",
            manifest=manifest,
            max_inflight=settings.max_inflight_analyses,
            inference_timeout_s=settings.sms_inference_timeout_ms / 1000,
            start_timeout_s=settings.sms_worker_start_timeout_seconds,
            commit_reserve_s=SMS_COMMIT_RESERVE_SECONDS,
            # Never above the timeout itself, or every request would look deadline-exhausted.
            min_budget_s=min(0.25, settings.sms_inference_timeout_ms / 1000),
            max_rss_mb=settings.sms_worker_max_rss_mb,
            threads=settings.sms_worker_threads,
        )
    )


def build_ingestion_service(settings: Settings, app: FastAPI, clock: Clock) -> IngestionService:
    # Settings guarantees the ingestion group, and the auth group it needs, are complete.
    if (
        app.state.auth is None
        or settings.subscriber_hmac_keys is None
        or settings.subscriber_hmac_active_version is None
        or settings.payload_hmac_keys is None
        or settings.payload_hmac_active_version is None
    ):
        raise RuntimeError("Incomplete event ingestion configuration")
    return IngestionService(
        sessions=app.state.db_sessions,
        subscriber_digests=KeyedDigester(
            parse_key_map(settings.subscriber_hmac_keys, "SUBSCRIBER_HMAC_KEYS"),
            settings.subscriber_hmac_active_version,
        ),
        payload_digests=KeyedDigester(
            parse_key_map(settings.payload_hmac_keys, "PAYLOAD_HMAC_KEYS"),
            settings.payload_hmac_active_version,
        ),
        audit=app.state.auth.audit,
        clock=clock,
        retention=timedelta(days=settings.event_retention_days),
        deadline=settings.inference_timeout_seconds,
        candidates=CandidateIndex(app.state.redis, namespace=settings.app_env),
        # Only an enabled (or injected) worker changes SMS handling; disabled keeps M3 behaviour.
        sms_classifier=None if app.state.sms_worker.state == "disabled" else app.state.sms_worker,
    )


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock = utc_now,
    sms_worker: SmsWorkerSupervisor | None = None,
) -> FastAPI:
    """`sms_worker` lets tests inject a supervisor (for example one driving the test-only fake
    worker); production builds it from settings."""
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
    app.state.ingest_keys = (
        IngestKeyService(sessions=app.state.db_sessions, audit=app.state.auth.audit, clock=clock)
        if app.state.auth is not None
        else None
    )
    app.state.clock = clock
    app.state.sms_worker = sms_worker if sms_worker is not None else build_sms_worker(settings)
    rate_key = (
        settings.rate_limit_hmac_key.get_secret_value().encode()
        if settings.rate_limit_hmac_key is not None
        else None
    )
    app.state.bearer_throttle = (
        BearerAttemptThrottle(app.state.redis, rate_key, namespace=settings.app_env)
        if app.state.auth is not None and rate_key is not None
        else None
    )
    app.state.submission_quota = (
        SubmissionQuota(app.state.redis, rate_key, namespace=settings.app_env)
        if app.state.auth is not None and rate_key is not None
        else None
    )
    app.state.read_quota = (
        ReadQuota(app.state.redis, rate_key, namespace=settings.app_env)
        if app.state.auth is not None and rate_key is not None
        else None
    )
    app.state.ingestion = (
        build_ingestion_service(settings, app, clock) if settings.ingestion_configured else None
    )
    # Incident reads are session-authenticated, so they need the authentication configuration.
    app.state.incidents = (
        IncidentReadService(sessions=app.state.db_sessions, clock=clock)
        if app.state.auth is not None
        else None
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
    app.include_router(events_router)
    app.include_router(incidents_router)
    app.include_router(simulator_router)
    app.include_router(system_router)
    return app
