"""FastAPI dependencies enforcing origin, credential exclusivity, session, CSRF and role."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from kavach.auth.cookies import LOCAL_DEVELOPMENT_COOKIE, SECURE_COOKIE, CookiePolicy
from kavach.auth.service import ActiveSession, AuthService, DependencyUnavailable, SessionInvalid
from kavach.auth.tokens import presented_token_matches
from kavach.core.errors import ApiError

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
