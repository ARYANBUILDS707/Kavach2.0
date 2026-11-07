"""Event ingestion routes (API.md "Event requests and receipts"): thin adapters over
IngestionService. Authentication is a source-scoped Bearer ingestion key; the admin session
path is not part of M3.1."""

import json
import time
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool

from kavach.api.schemas.events import CallEvent, EventReceipt, ReceiptResponse, SMSEvent
from kavach.auth.dependencies import (
    IngestPrincipalDep,
    rate_limited,
    require_source,
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


async def submit(
    request: Request,
    response: Response,
    principal: IngestPrincipal,
    service: IngestionService,
    model: type[SMSEvent] | type[CallEvent],
) -> ReceiptResponse:
    started = time.monotonic()
    payload = await bounded_json(request)
    try:
        event = model.model_validate(payload, context={"now": service.clock()})
    except ValidationError:
        raise invalid() from None
    if event.source != principal.source:
        security_event("ingest.source_forbidden", "source_mismatch", request.state.request_id)
    require_source(principal, event.source)
    try:
        receipt = await run_in_threadpool(
            service.ingest, event, principal, request.state.request_id, started
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
    else:
        response.headers["Location"] = f"/api/v1/events/{receipt.event_id}"
    return receipt_response(request, receipt)


def request_body(model: type[BaseModel]) -> dict[str, Any]:
    """Document the request body in OpenAPI; it is read and validated by the route itself."""
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }


@router.post(
    "/sms", status_code=201, response_model=ReceiptResponse, openapi_extra=request_body(SMSEvent)
)
async def ingest_sms(
    request: Request,
    response: Response,
    principal: SubmittingPrincipal,
    service: IngestionServiceDep,
) -> ReceiptResponse:
    return await submit(request, response, principal, service, SMSEvent)


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
