"""Anonymous, bounded, no-persistence SMS inference. Never touches admin dependencies."""

import asyncio
import ipaddress
import time

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from kavach.api.schemas.errors import ErrorResponse
from kavach.api.schemas.public_analyzer import (
    PublicAnalyzerStatus,
    PublicPredictionResponse,
    PublicSmsInput,
    PublicStatusResponse,
)
from kavach.core.errors import ApiError
from kavach.services.public_analyzer import analyze

router = APIRouter(
    prefix="/api/v1/public",
    tags=["public analyzer"],
    responses={"default": {"model": ErrorResponse}},
)
MAX_BODY_BYTES = 32 * 1024


@router.get("/analyzer", response_model=PublicStatusResponse)
def status(request: Request) -> PublicStatusResponse:
    settings = request.app.state.settings
    return PublicStatusResponse(
        data=PublicAnalyzerStatus(
            enabled=settings.public_analyzer_mode != "disabled",
            max_chars=settings.public_analyzer_max_chars,
        ),
        request_id=request.state.request_id,
    )


@router.post(
    "/analyze",
    response_model=PublicPredictionResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": PublicSmsInput.model_json_schema()}},
        }
    },
)
async def analyze_sms(request: Request) -> PublicPredictionResponse:
    settings = request.app.state.settings
    if settings.public_analyzer_mode == "disabled":
        raise ApiError(503, "ANALYZER_DISABLED", "Public analysis is disabled")
    if (
        request.headers.get("origin") != settings.app_origin
        or request.headers.get("x-kavach-analyzer") != "1"
    ):
        raise ApiError(403, "FORBIDDEN", "Same-origin analyzer requests only")
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "JSON is required")
    # Never trust caller-supplied forwarding headers. The deployed service must use a verified
    # trusted proxy configuration at the ASGI server/edge, not arbitrary X-Forwarded-For input.
    try:
        client_ip = str(ipaddress.ip_address(request.client.host if request.client else ""))
    except ValueError:
        raise ApiError(503, "DEPENDENCY_UNAVAILABLE", "Client address unavailable") from None
    quota = request.app.state.public_quota
    if quota is None:
        raise ApiError(503, "DEPENDENCY_UNAVAILABLE", "Analysis temporarily unavailable")
    await run_in_threadpool(quota.reserve, client_ip, str(request.state.request_id))
    # Hold a slot before reading any body. Slow clients and threadpool waiting cannot accumulate
    # unbounded raw messages. The worker has its own independent admission and killable deadline.
    slots = request.app.state.public_slots
    if not slots.acquire(blocking=False):
        raise ApiError(429, "CAPACITY_EXCEEDED", "Analyzer is busy", {"Retry-After": "2"})
    try:
        body = bytearray()
        try:
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_BODY_BYTES:
                        raise ApiError(413, "PAYLOAD_TOO_LARGE", "Request body is too large")
                    body.extend(chunk)
        except TimeoutError:
            raise ApiError(408, "REQUEST_TIMEOUT", "Request body timed out") from None
        try:
            payload = PublicSmsInput.model_validate_json(body)
        except ValidationError:
            raise ApiError(
                422, "VALIDATION_ERROR", "Enter a nonempty SMS within the limit"
            ) from None
        finally:
            body.clear()
        if len(payload.text) > settings.public_analyzer_max_chars:
            raise ApiError(422, "VALIDATION_ERROR", "SMS exceeds the configured character limit")
        deadline = time.monotonic() + settings.inference_timeout_seconds
        result = await run_in_threadpool(
            analyze, request.app.state.sms_worker, payload.text, deadline
        )
        return PublicPredictionResponse(data=result, request_id=request.state.request_id)
    finally:
        slots.release()
