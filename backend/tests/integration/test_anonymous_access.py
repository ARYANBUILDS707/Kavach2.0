"""Login-free public site (decision C-14): the API stays closed to anonymous callers.

The public website is static and calls no API. These tests inventory every route the production
application registers and prove that each one either appears on a short, reviewed allowlist of
intentionally open routes or refuses a caller with no credentials, so a new endpoint cannot become
public by accident. They run against real PostgreSQL and Redis with the production app factory
(no test probes) and send a valid Origin and a well-formed body, so a refusal is about identity,
not about a malformed request.
"""

import json
import re
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from starlette.routing import Route

from kavach.db.models import Event
from kavach.main import create_app

from .auth_support import ORIGIN, auth_settings

pytestmark = pytest.mark.integration

# Routes that are open to a caller with no credentials on purpose, and why.
OPEN_ROUTES = {
    ("GET", "/health"): "process liveness only",
    ("GET", "/api/v1/health"): "process liveness only",
    ("POST", "/api/v1/auth/login"): "sign-in itself; refuses wrong credentials, throttled",
    (
        "POST",
        "/api/v1/auth/logout",
    ): "clears a cookie; works on no session and needs a valid Origin",
    # Interactive API documentation: served in development and test only; `pilot` (hosted) turns
    # all three off (test_config.py asserts 404s there).
    ("GET", "/openapi.json"): "development and test only",
    ("GET", "/docs"): "development and test only",
    ("GET", "/docs/oauth2-redirect"): "development and test only",
}
# What an anonymous caller gets from each route that is not open (status, error code).
CLOSED_ROUTES = {
    ("GET", "/api/v1/auth/session"): (401, "SESSION_EXPIRED"),
    ("GET", "/api/v1/incidents"): (401, "SESSION_EXPIRED"),
    ("GET", "/api/v1/incidents/{incident_id}"): (401, "SESSION_EXPIRED"),
    ("GET", "/api/v1/system/models"): (401, "SESSION_EXPIRED"),
    ("GET", "/api/v1/simulator/scenarios"): (401, "SESSION_EXPIRED"),
    # Receipt reads belong to an ingestion key (own source only), never to a browser visitor.
    ("GET", "/api/v1/events/{event_id}"): (401, "INVALID_CREDENTIALS"),
}
SMS_BODY = {
    "event_id": "anon-probe-1",
    "subscriber_token": "sub_anonymous_probe",
    "timestamp": "2031-01-01T12:00:00Z",
    "source": "simulator",
    "text": "FICTIONAL TEST: anonymous probe, must never be stored.",
}
CALL_BODY = {k: v for k, v in SMS_BODY.items() if k != "text"}
BODIES = {"/api/v1/events/sms": SMS_BODY, "/api/v1/events/call": CALL_BODY}


@pytest.fixture
def production_app(migrated_schema: None, keys: tuple[str, str], clean_throttle: None) -> FastAPI:
    return create_app(auth_settings(*keys))


@pytest.fixture
def anonymous(production_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(production_app, base_url=ORIGIN) as client:
        yield client


def flatten(routes: list, prefix: str = "") -> Iterator[tuple[str, str]]:
    """Every (method, path) the application can answer, including routers included by prefix.

    An unrecognised kind of route fails the test instead of being skipped: a route this inventory
    cannot see is exactly the one that could be public by accident.
    """
    for route in routes:
        original = getattr(route, "original_router", None)
        if isinstance(route, APIRoute):
            for method in sorted(route.methods - {"HEAD"}):
                yield method, prefix + route.path
        elif original is not None:
            yield from flatten(original.routes, prefix + route.include_context.prefix)
        elif isinstance(route, Route):
            for method in sorted((route.methods or set()) - {"HEAD"}):
                yield method, prefix + route.path
        else:
            raise AssertionError(
                f"unrecognised route type {type(route).__name__}: extend the inventory"
            )


def registered_routes(app: FastAPI) -> list[tuple[str, str]]:
    return sorted(set(flatten(list(app.routes))))


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid4()), path)


def test_every_registered_route_is_deliberately_open_or_refuses_anonymous_callers(
    production_app: FastAPI,
) -> None:
    registered = registered_routes(production_app)
    assert registered, "the inventory found no routes"
    classified = set(OPEN_ROUTES) | set(CLOSED_ROUTES) | {("POST", p) for p in BODIES}
    unreviewed = [route for route in registered if route not in classified]
    assert unreviewed == [], f"new routes need a decision about anonymous access: {unreviewed}"
    stale = sorted(classified - set(registered))
    assert stale == [], f"allowlist entries for routes that no longer exist: {stale}"


@pytest.mark.parametrize(("method", "path"), sorted(CLOSED_ROUTES))
def test_read_routes_refuse_an_anonymous_caller_with_no_cookie_and_no_cache(
    anonymous: TestClient, method: str, path: str
) -> None:
    response = anonymous.request(method, concrete(path))
    status, code = CLOSED_ROUTES[(method, path)]
    assert (response.status_code, response.json()["error"]["code"]) == (status, code)
    assert "set-cookie" not in response.headers
    assert response.headers.get("cache-control") == "no-store"


@pytest.mark.parametrize("path", sorted(BODIES))
def test_event_submission_refuses_an_anonymous_caller_even_with_a_valid_origin_and_body(
    anonymous: TestClient, path: str
) -> None:
    for headers in ({}, {"Origin": ORIGIN}, {"Origin": ORIGIN, "X-CSRF-Token": "guessed"}):
        response = anonymous.post(path, json=BODIES[path], headers=headers)
        assert response.status_code in (401, 403), (headers, response.status_code)
        body = response.text
        assert "anonymous probe" not in body, "the message text must never be echoed back"
        assert "set-cookie" not in response.headers


def test_anonymous_submissions_store_nothing(
    anonymous: TestClient, migration_engine: Engine
) -> None:
    def count() -> int:
        with migration_engine.connect() as connection:
            return connection.execute(select(func.count()).select_from(Event)).scalar_one()

    before = count()
    anonymous.post("/api/v1/events/sms", json=SMS_BODY, headers={"Origin": ORIGIN})
    anonymous.post("/api/v1/events/call", json=CALL_BODY, headers={"Origin": ORIGIN})
    assert count() == before


def test_open_routes_stay_harmless_to_anonymous_callers(anonymous: TestClient) -> None:
    for path in ("/health", "/api/v1/health"):
        body = anonymous.get(path).json()["data"]
        assert body == {"status": "ok", "scope": "liveness", "analysis_ready": False}
    refused = anonymous.post(
        "/api/v1/auth/login",
        json={"username": "nobody", "password": "wrong passphrase value"},
        headers={"Origin": ORIGIN},
    )
    assert refused.status_code == 401 and "set-cookie" not in refused.headers
    # Logout with no session changes nothing and still needs the right Origin.
    assert (
        anonymous.post("/api/v1/auth/logout", headers={"Origin": "https://evil.test"}).status_code
        == 403
    )


def test_no_other_website_is_granted_browser_access_to_the_api(anonymous: TestClient) -> None:
    for path in ("/api/v1/incidents", "/api/v1/system/models", "/api/v1/auth/session"):
        for method in ("GET", "OPTIONS"):
            response = anonymous.request(
                method,
                path,
                headers={
                    "Origin": "https://evil.test",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert not any(name.lower().startswith("access-control-") for name in response.headers)


def test_health_reveals_no_configuration(anonymous: TestClient) -> None:
    text = json.dumps(anonymous.get("/health").json()).lower()
    for word in ("database", "redis", "postgres", "model", "version", "password", "key"):
        assert word not in text
