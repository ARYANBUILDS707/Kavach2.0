"""Browser authentication routes: thin adapters over AuthService (API.md, D03, C-06)."""

from fastapi import APIRouter, Depends, Request, Response

from kavach.api.schemas.auth import LoginRequest, SessionData, SessionResponse, SessionUser
from kavach.auth.dependencies import (
    AuthServiceDep,
    CookiePolicyDep,
    CsrfCheckedSession,
    CurrentSession,
    SessionTokenDep,
    reject_bearer_on_login,
    reject_mixed_credentials,
    require_trusted_origin,
    unavailable,
)
from kavach.auth.service import (
    ActiveSession,
    DependencyUnavailable,
    InvalidCredentials,
    LoginThrottled,
)
from kavach.auth.tokens import csrf_token_for
from kavach.core.errors import ApiError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def session_response(request: Request, session: ActiveSession, csrf_token: str) -> SessionResponse:
    return SessionResponse(
        data=SessionData(
            user=SessionUser(
                id=session.user_id, display_name=session.display_name, role=session.role
            ),
            expires_at=session.expires_at,
            csrf_token=csrf_token,
        ),
        request_id=request.state.request_id,
    )


@router.post(
    "/login",
    response_model=SessionResponse,
    dependencies=[Depends(require_trusted_origin), Depends(reject_bearer_on_login)],
)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    auth: AuthServiceDep,
    policy: CookiePolicyDep,
    previous_token: SessionTokenDep,
) -> SessionResponse:
    try:
        issued = auth.login(
            username=body.username,
            password=body.password.get_secret_value(),
            client_ip=request.client.host if request.client else "unknown",
            request_id=request.state.request_id,
            previous_token=previous_token,
        )
    except InvalidCredentials:
        raise ApiError(401, "INVALID_CREDENTIALS", "Invalid username or password") from None
    except LoginThrottled as throttled:
        raise ApiError(
            429,
            "RATE_LIMITED",
            "Too many sign-in attempts; try again later",
            {"Retry-After": str(throttled.retry_after_seconds)},
        ) from None
    except DependencyUnavailable:
        raise unavailable("Sign-in is temporarily unavailable") from None
    response.set_cookie(
        policy.name,
        issued.token,
        max_age=int(auth.policy.absolute.total_seconds()),
        path="/",
        secure=policy.secure,
        httponly=True,
        samesite="lax",
    )
    return session_response(request, issued.session, issued.csrf_token)


@router.get(
    "/session",
    response_model=SessionResponse,
    dependencies=[Depends(reject_mixed_credentials)],
)
def get_session(
    request: Request, session: CurrentSession, token: SessionTokenDep
) -> SessionResponse:
    # current_session succeeded, so the cookie is present; the CSRF token is re-derived from it.
    return session_response(request, session, csrf_token_for(token or ""))


@router.post(
    "/logout",
    status_code=204,
    dependencies=[Depends(require_trusted_origin), Depends(reject_mixed_credentials)],
)
def logout(
    request: Request,
    session: CsrfCheckedSession,
    auth: AuthServiceDep,
    policy: CookiePolicyDep,
) -> Response:
    try:
        auth.logout(session, request.state.request_id)
    except DependencyUnavailable:
        raise unavailable("Sign-out is temporarily unavailable") from None
    response = Response(status_code=204)
    response.delete_cookie(
        policy.name, path="/", secure=policy.secure, httponly=True, samesite="lax"
    )
    return response
