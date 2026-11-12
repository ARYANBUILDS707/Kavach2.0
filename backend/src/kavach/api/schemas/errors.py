"""The documented error envelope (API.md "Status and conventions"), declared for OpenAPI so
clients type errors from the schema. `core.errors` produces exactly this shape."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel

ERROR_DESCRIPTIONS = {
    400: "INVALID_CURSOR",
    401: "SESSION_EXPIRED, INVALID_CREDENTIALS or MIXED_CREDENTIALS",
    403: "FORBIDDEN or CSRF_REJECTED",
    404: "NOT_FOUND (missing, expired and inaccessible are identical)",
    409: "EVENT_ID_CONFLICT (same event ID, different payload)",
    413: "PAYLOAD_TOO_LARGE (body above 32 KiB)",
    422: "VALIDATION_ERROR (no field values are echoed)",
    429: "RATE_LIMITED or CAPACITY_EXCEEDED, with Retry-After",
    503: "DEPENDENCY_UNAVAILABLE or PROCESSING_TIMEOUT",
}


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
    request_id: UUID


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """The listed statuses plus a `default`, so FastAPI adds no foreign 422 body."""
    responses: dict[int | str, dict[str, Any]] = {
        status: {"model": ErrorResponse, "description": ERROR_DESCRIPTIONS[status]}
        for status in statuses
    }
    responses["default"] = {"model": ErrorResponse, "description": "Error envelope"}
    return responses
