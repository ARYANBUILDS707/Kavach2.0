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
from kavach.auth.dependencies import IngestPrincipalDep, require_source, unavailable
from kavach.auth.ingest_keys import IngestPrincipal
from kavach.core.errors import ApiError
from kavach.core.telemetry import security_event
from kavach.services.ingestion import (
    EventIdConflict,
    IngestionService,
    IngestionUnavailable,
    Receipt,
    UnknownAudioReference,
)

MAX_BODY_BYTES = 32 * 1024  # API.md: JSON request at most 32 KiB

router = APIRouter(prefix="/api/v1/events", tags=["events"])


def ingestion_service(request: Request) -> IngestionService:
    service: IngestionService | None = request.app.state.ingestion
    if service is None:
        raise unavailable("Event ingestion is not configured")
    return service


IngestionServiceDep = Annotated[IngestionService, Depends(ingestion_service)]


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
    except (ValueError, UnicodeDecodeError):
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
    principal: IngestPrincipalDep,
    service: IngestionServiceDep,
) -> ReceiptResponse:
    return await submit(request, response, principal, service, SMSEvent)


@router.post(
    "/call", status_code=201, response_model=ReceiptResponse, openapi_extra=request_body(CallEvent)
)
async def ingest_call(
    request: Request,
    response: Response,
    principal: IngestPrincipalDep,
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
