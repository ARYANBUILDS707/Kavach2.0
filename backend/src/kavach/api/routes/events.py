"""Event ingestion routes (API.md "Event requests and receipts"): thin adapters over
IngestionService.

Two credentials reach `POST /events/sms`: a source-scoped Bearer ingestion key (M3.1), or an
admin browser session (MVP-B4: Origin, session, active account, admin role, CSRF, per-admin
limit, then `source=simulator` and the synthetic `ui-` identifiers). `/events/call` and receipt
reads remain key-only.

No route declares a body parameter: FastAPI 0.162 reads a declared body *before* resolving any
dependency, so the body is read by `bounded_json` inside the handler, after every credential
check. The request schema is documented through `openapi_extra` instead.
"""

import json
import time
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool

from kavach.api.schemas.errors import error_responses
from kavach.api.schemas.events import (
    SIMULATOR_SOURCE,
    AdminEventReceipt,
    AdminReceiptResponse,
    CallEvent,
    EventReceipt,
    ReceiptResponse,
    SMSEvent,
    has_browser_identifiers,
)
from kavach.auth.dependencies import (
    IngestPrincipalDep,
    auth_service,
    cookie_policy,
    current_session,
    has_session_cookie,
    ingest_key_service,
    rate_limited,
    require_csrf,
    require_ingest_key,
    require_source,
    require_trusted_origin,
    session_token,
    unavailable,
)
from kavach.auth.ingest_keys import IngestPrincipal
from kavach.auth.throttle import SubmissionQuota, ThrottleUnavailable
from kavach.core.errors import ApiError
from kavach.core.telemetry import security_event
from kavach.services.ingestion import (
    AnalysisRejected,
    EventIdConflict,
    IngestionService,
    IngestionUnavailable,
    ProcessingTimeout,
    Receipt,
    SessionSubmitter,
    Submitter,
    UnknownAudioReference,
)

MAX_BODY_BYTES = 32 * 1024  # API.md: JSON request at most 32 KiB
# Retry-After for analysis rejections: a slot frees within one inference (tens of ms); a
# starting or restarting worker needs its startup (about 6 s measured, M4-I.1).
CAPACITY_RETRY_AFTER_SECONDS = 1
WORKER_RETRY_AFTER_SECONDS = 10

router = APIRouter(prefix="/api/v1/events", tags=["events"])


def ingestion_service(request: Request) -> IngestionService:
    service: IngestionService | None = request.app.state.ingestion
    if service is None:
        raise unavailable("Event ingestion is not configured")
    return service


IngestionServiceDep = Annotated[IngestionService, Depends(ingestion_service)]


def require_submission_quota(request: Request, principal: IngestPrincipalDep) -> IngestPrincipal:
    """D08: 30 submissions per minute per key, checked before the body is read.

    Every authenticated submission counts, including idempotent replays and rejected bodies.
    If Redis cannot enforce the limit the submission is refused (503), never let through.
    """
    quota: SubmissionQuota = request.app.state.submission_quota
    try:
        reservation = quota.acquire(str(principal.key_id), str(request.state.request_id))
    except ThrottleUnavailable:
        security_event("ingest.quota", "throttle_unavailable", request.state.request_id)
        raise unavailable("Event ingestion is temporarily unavailable") from None
    if not reservation.allowed:
        security_event("ingest.quota", "rate_limited", request.state.request_id)
        raise rate_limited(reservation.retry_after_seconds, "Too many event submissions")
    return principal


SubmittingPrincipal = Annotated[IngestPrincipal, Depends(require_submission_quota)]


def require_admin_session_submitter(request: Request) -> SessionSubmitter:
    """MVP-B4, in this order and before the body is read: exact Origin, a valid session of an
    active account, the admin role (re-read from the database), the CSRF token, then the
    per-admin submission limit (30 per minute; Redis down fails closed)."""
    require_trusted_origin(request)
    session = current_session(session_token(request, cookie_policy(request)), auth_service(request))
    if session.role != "admin":
        security_event("ingest.session_forbidden", "role", request.state.request_id)
        raise ApiError(403, "FORBIDDEN", "You do not have access to this resource")
    require_csrf(request, session)
    quota: SubmissionQuota = request.app.state.submission_quota
    try:
        reservation = quota.acquire_for_user(str(session.user_id), str(request.state.request_id))
    except ThrottleUnavailable:
        security_event("ingest.quota", "throttle_unavailable", request.state.request_id)
        raise unavailable("Event ingestion is temporarily unavailable") from None
    if not reservation.allowed:
        security_event("ingest.quota", "rate_limited", request.state.request_id)
        raise rate_limited(reservation.retry_after_seconds, "Too many event submissions")
    return SessionSubmitter(user_id=session.user_id)


def require_submitter(request: Request) -> Submitter:
    """Exactly one credential: both is 401 MIXED_CREDENTIALS; none (or a Bearer only) takes the
    unchanged key path, whose missing-credential answer is 401 INVALID_CREDENTIALS."""
    if has_session_cookie(request):
        if "authorization" in request.headers:
            raise ApiError(401, "MIXED_CREDENTIALS", "Use exactly one authentication mechanism")
        return require_admin_session_submitter(request)
    return require_submission_quota(
        request, require_ingest_key(request, ingest_key_service(request))
    )


def not_found() -> ApiError:
    # Missing and other-source events are indistinguishable.
    return ApiError(404, "NOT_FOUND", "Request could not be served")


def invalid() -> ApiError:
    # The same safe envelope as RequestValidationError: no field paths or input values.
    return ApiError(422, "VALIDATION_ERROR", "Request validation failed")


async def bounded_json(request: Request) -> Any:
    """Read at most MAX_BODY_BYTES, whatever Content-Length claims."""
    declared = request.headers.get("content-length")
    too_large = ApiError(413, "PAYLOAD_TOO_LARGE", "The request body is too large")
    if declared is not None and (not declared.isdigit() or int(declared) > MAX_BODY_BYTES):
        raise too_large
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise too_large
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError, RecursionError):
        # RecursionError: pathologically deep nesting fits easily inside 32 KiB.
        raise invalid() from None


def receipt_response(request: Request, receipt: Receipt) -> ReceiptResponse:
    return ReceiptResponse(
        data=EventReceipt(
            event_id=receipt.event_id,
            external_event_id=receipt.external_event_id,
            source=receipt.source,
            kind=receipt.kind,
            analysis_status=receipt.analysis_status,
            received_at=receipt.received_at,
            processing_ms=receipt.processing_ms,
            replayed=receipt.replayed,
            warnings=receipt.warnings,
        ),
        request_id=request.state.request_id,
    )


def check_scope(submitter: Submitter, event: SMSEvent | CallEvent, request: Request) -> None:
    if isinstance(submitter, SessionSubmitter):
        if event.source != SIMULATOR_SOURCE:
            security_event("ingest.source_forbidden", "session_source", request.state.request_id)
            raise ApiError(403, "FORBIDDEN", "Browser submissions must use the simulator source")
        if not has_browser_identifiers(event):
            raise invalid()
        return
    if event.source != submitter.source:
        security_event("ingest.source_forbidden", "source_mismatch", request.state.request_id)
    require_source(submitter, event.source)


async def submit(
    request: Request,
    response: Response,
    submitter: Submitter,
    service: IngestionService,
    model: type[SMSEvent] | type[CallEvent],
) -> ReceiptResponse | AdminReceiptResponse:
    started = time.monotonic()
    # The first read of the body: every credential check has already passed.
    payload = await bounded_json(request)
    try:
        event = model.model_validate(payload, context={"now": service.clock()})
    except ValidationError:
        raise invalid() from None
    check_scope(submitter, event, request)
    try:
        receipt = await run_in_threadpool(
            service.ingest, event, submitter, request.state.request_id, started
        )
    except AnalysisRejected as rejection:
        # Nothing was stored; a same-ID retry is analyzed afresh (design §6.4).
        if rejection.saturated:
            raise ApiError(
                429,
                "CAPACITY_EXCEEDED",
                "Analysis capacity is full; retry with the same event ID",
                {"Retry-After": str(CAPACITY_RETRY_AFTER_SECONDS)},
            ) from None
        raise ApiError(
            503,
            "DEPENDENCY_UNAVAILABLE",
            "SMS analysis is starting; retry with the same event ID",
            {"Retry-After": str(WORKER_RETRY_AFTER_SECONDS)},
        ) from None
    except UnknownAudioReference:
        raise ApiError(
            422, "UNKNOWN_AUDIO_REFERENCE", "The audio reference is not an approved sample"
        ) from None
    except EventIdConflict:
        raise ApiError(
            409, "EVENT_ID_CONFLICT", "This event ID was already used with a different payload"
        ) from None
    except IngestionUnavailable:
        raise unavailable("Event ingestion is temporarily unavailable") from None
    except ProcessingTimeout:
        raise ApiError(
            503,
            "PROCESSING_TIMEOUT",
            "Processing did not finish in time; retry with the same event ID",
        ) from None
    if receipt.replayed:
        response.status_code = 200
    if isinstance(submitter, SessionSubmitter):
        # No Location: receipt reads are key-only, so a browser navigates by `incident_ids`.
        return admin_receipt_response(request, receipt)
    if not receipt.replayed:
        response.headers["Location"] = f"/api/v1/events/{receipt.event_id}"
    return receipt_response(request, receipt)


def admin_receipt_response(request: Request, receipt: Receipt) -> AdminReceiptResponse:
    base = receipt_response(request, receipt).data
    return AdminReceiptResponse(
        data=AdminEventReceipt(**base.model_dump(), incident_ids=list(receipt.incident_ids)),
        request_id=request.state.request_id,
    )


def request_body(model: type[BaseModel]) -> dict[str, Any]:
    """Document the request body in OpenAPI; it is read and validated by the route itself."""
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }


@router.post(
    "/sms",
    status_code=201,
    # Ingestion keys get ReceiptResponse; an admin browser session gets AdminReceiptResponse.
    response_model=ReceiptResponse | AdminReceiptResponse,
    responses={
        200: {"model": ReceiptResponse | AdminReceiptResponse, "description": "Replay"},
        **error_responses(401, 403, 409, 413, 422, 429, 503),
    },
    openapi_extra=request_body(SMSEvent),
)
async def ingest_sms(
    request: Request,
    response: Response,
    submitter: Annotated[Submitter, Depends(require_submitter)],
    service: IngestionServiceDep,
) -> ReceiptResponse | AdminReceiptResponse:
    return await submit(request, response, submitter, service, SMSEvent)


@router.post(
    "/call", status_code=201, response_model=ReceiptResponse, openapi_extra=request_body(CallEvent)
)
async def ingest_call(
    request: Request,
    response: Response,
    principal: SubmittingPrincipal,
    service: IngestionServiceDep,
) -> ReceiptResponse:
    return await submit(request, response, principal, service, CallEvent)


@router.get("/{event_id}", response_model=ReceiptResponse)
def get_receipt(
    event_id: str, request: Request, principal: IngestPrincipalDep, service: IngestionServiceDep
) -> ReceiptResponse:
    """Own-source receipts only; another source's event and a missing one are the same 404."""
    try:
        parsed = UUID(event_id)
    except ValueError:
        raise not_found() from None
    try:
        receipt = service.receipt(parsed, principal)
    except IngestionUnavailable:
        raise unavailable("Receipt lookup is temporarily unavailable") from None
    if receipt is None:
        raise not_found()
    return receipt_response(request, receipt)
