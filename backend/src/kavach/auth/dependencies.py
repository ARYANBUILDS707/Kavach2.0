"""FastAPI dependencies enforcing origin, credential exclusivity, session, CSRF, role and
ingestion-key source scope."""

import hmac
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from kavach.auth.cookies import LOCAL_DEVELOPMENT_COOKIE, SECURE_COOKIE, CookiePolicy
from kavach.auth.ingest_keys import (
    IngestKeyService,
    IngestKeysUnavailable,
    IngestPrincipal,
    InvalidIngestKey,
)
from kavach.auth.service import ActiveSession, AuthService, DependencyUnavailable, SessionInvalid
from kavach.auth.throttle import BearerAttemptThrottle, ThrottleUnavailable
from kavach.auth.tokens import presented_token_matches
from kavach.core.errors import ApiError
from kavach.core.telemetry import security_event

SESSION_COOKIE_NAMES = (SECURE_COOKIE.name, LOCAL_DEVELOPMENT_COOKIE.name)


def unavailable(message: str) -> ApiError:
    return ApiError(503, "DEPENDENCY_UNAVAILABLE", message)


def auth_service(request: Request) -> AuthService:
    service: AuthService | None = request.app.state.auth
    if service is None:
        raise unavailable("Authentication is not configured")
    return service


def cookie_policy(request: Request) -> CookiePolicy:
    policy: CookiePolicy | None = request.app.state.cookie_policy
    if policy is None:
        raise unavailable("Authentication is not configured")
    return policy


def require_trusted_origin(request: Request) -> None:
    """State-changing browser requests must come from exactly the configured origin."""
    expected = request.app.state.settings.app_origin
    if expected is None:
        raise unavailable("Authentication is not configured")
    if request.headers.get("origin") != expected:
        raise ApiError(403, "CSRF_REJECTED", "Cross-site request rejected")


def has_session_cookie(request: Request) -> bool:
    return any(name in request.cookies for name in SESSION_COOKIE_NAMES)


def reject_mixed_credentials(request: Request) -> None:
    """A browser session and a Bearer credential are never accepted on the same request."""
    if "authorization" in request.headers and has_session_cookie(request):
        raise ApiError(401, "MIXED_CREDENTIALS", "Use exactly one authentication mechanism")


def reject_bearer_on_login(request: Request) -> None:
    """Password login is a browser mechanism; it never combines with a Bearer credential."""
    if "authorization" in request.headers:
        raise ApiError(401, "MIXED_CREDENTIALS", "Use exactly one authentication mechanism")


AuthServiceDep = Annotated[AuthService, Depends(auth_service)]
CookiePolicyDep = Annotated[CookiePolicy, Depends(cookie_policy)]


def session_token(request: Request, policy: CookiePolicyDep) -> str | None:
    return request.cookies.get(policy.name)


SessionTokenDep = Annotated[str | None, Depends(session_token)]


def current_session(token: SessionTokenDep, auth: AuthServiceDep) -> ActiveSession:
    try:
        return auth.authenticate(token)
    except SessionInvalid:
        raise ApiError(401, "SESSION_EXPIRED", "Your session has expired; sign in again") from None
    except DependencyUnavailable:
        raise unavailable("Session validation is temporarily unavailable") from None


CurrentSession = Annotated[ActiveSession, Depends(current_session)]


def require_csrf(request: Request, session: CurrentSession) -> ActiveSession:
    if not presented_token_matches(request.headers.get("x-csrf-token"), session.csrf_digest):
        raise ApiError(403, "CSRF_REJECTED", "Cross-site request rejected")
    return session


CsrfCheckedSession = Annotated[ActiveSession, Depends(require_csrf)]


def require_role(*roles: str) -> Callable[[ActiveSession], ActiveSession]:
    """Server-side role check; the role is re-read from the database on every request."""

    def check(session: CurrentSession) -> ActiveSession:
        if session.role not in roles:
            raise ApiError(403, "FORBIDDEN", "You do not have access to this resource")
        return session

    return check


def ingest_key_service(request: Request) -> IngestKeyService:
    service: IngestKeyService | None = request.app.state.ingest_keys
    if service is None:
        raise unavailable("API key authentication is not configured")
    return service


IngestKeyServiceDep = Annotated[IngestKeyService, Depends(ingest_key_service)]


def rate_limited(retry_after_seconds: int, message: str) -> ApiError:
    return ApiError(429, "RATE_LIMITED", message, {"Retry-After": str(retry_after_seconds)})


def require_ingest_key(request: Request, keys: IngestKeyServiceDep) -> IngestPrincipal:
    """Machine authentication: exactly `Authorization: Bearer kvk_...` and no session cookie.

    Presented credentials are throttled per client IP (M3.2): each attempt is reserved in
    Redis before the key is checked and refunded if the key is valid, so only rejected
    credentials accumulate. If Redis cannot confirm the reservation the request fails closed.
    """
    if has_session_cookie(request):
        raise ApiError(401, "MIXED_CREDENTIALS", "Use exactly one authentication mechanism")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    rejected = ApiError(
        401, "INVALID_CREDENTIALS", "Invalid or expired API key", {"WWW-Authenticate": "Bearer"}
    )
    if scheme.lower() != "bearer" or not token.strip():
        raise rejected
    throttle: BearerAttemptThrottle = request.app.state.bearer_throttle
    client_ip = request.client.host if request.client else "unknown"
    try:
        reservation = throttle.reserve(client_ip)
    except ThrottleUnavailable:
        security_event("ingest.key_rejected", "throttle_unavailable", request.state.request_id)
        raise unavailable("API key validation is temporarily unavailable") from None
    if not reservation.allowed:
        security_event("ingest.key_rejected", "throttled", request.state.request_id)
        raise rate_limited(reservation.retry_after_seconds, "Too many invalid API key attempts")
    try:
        principal = keys.authenticate(token.strip(), request.state.request_id)
    except InvalidIngestKey:
        raise rejected from None
    except IngestKeysUnavailable:
        throttle.release(client_ip)
        raise unavailable("API key validation is temporarily unavailable") from None
    throttle.release(client_ip)
    return principal


IngestPrincipalDep = Annotated[IngestPrincipal, Depends(require_ingest_key)]


def require_source(principal: IngestPrincipal, source: str) -> None:
    """A key may only act for the single source it was issued for."""
    if not hmac.compare_digest(principal.source.encode(), source.encode()):
        raise ApiError(403, "FORBIDDEN", "This API key is not authorized for that source")
