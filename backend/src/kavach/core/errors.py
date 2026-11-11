"""Safe error envelopes: never serialize validation input, context or exception text."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class ApiError(Exception):
    """An expected failure with a documented error code and a message that is safe to return."""

    def __init__(
        self, status: int, code: str, message: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}


def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    request_id = str(request.state.request_id)
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}, "request_id": request_id},
        headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
    )


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Field paths can include attacker-controlled extra keys; omit them along with raw values.
    return error_response(request, 422, "VALIDATION_ERROR", "Request validation failed")


async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
    response = error_response(
        request,
        exc.status_code,
        codes.get(exc.status_code, "HTTP_ERROR"),
        "Request could not be served",
    )
    if exc.status_code == 405 and exc.headers and "Allow" in exc.headers:
        response.headers["Allow"] = exc.headers["Allow"]
    return response


async def api_error(request: Request, exc: ApiError) -> JSONResponse:
    response = error_response(request, exc.status, exc.code, exc.message)
    response.headers.update(exc.headers)
    return response


async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    return error_response(request, 500, "INTERNAL_ERROR", "An internal error occurred")
