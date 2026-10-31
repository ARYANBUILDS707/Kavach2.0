"""Authentication against real PostgreSQL and Redis: sessions, cookies, CSRF, Origin, roles,
throttling across processes, outages, audit and log redaction (M2.3)."""

import hashlib
import json
import logging
import multiprocessing
import secrets
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

import pytest
from argon2 import PasswordHasher
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from redis import Redis
from sqlalchemy import Engine, func, select, update

from kavach.auth.accounts import AccountService
from kavach.auth.dependencies import require_role
from kavach.auth.passwords import PasswordService
from kavach.auth.service import ActiveSession
from kavach.db.models import AuditRecord, User, UserSession
from kavach.main import create_app

from .auth_support import ORIGIN, FakeClock, auth_settings, failed_logins_in_process, login

pytestmark = pytest.mark.integration

SECURE_COOKIE = "__Host-kavach_session"


@dataclass(frozen=True)
class Account:
    id: UUID
    username: str
    password: str


@pytest.fixture
def keys() -> tuple[str, str]:
    return secrets.token_urlsafe(32), json.dumps({"v1": secrets.token_urlsafe(32)})


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def clean_throttle(redis_client: Redis) -> Iterator[None]:
    def clear() -> None:
        for key in redis_client.scan_iter("kavach:test:ratelimit:*"):
            redis_client.delete(key)

    clear()
    yield
    clear()


@pytest.fixture
def app(
    migrated_schema: None, keys: tuple[str, str], clock: FakeClock, clean_throttle: None
) -> FastAPI:
    application = create_app(auth_settings(*keys), clock=clock)

    @application.get("/_test/admin-only")
    def admin_only(session: Annotated[ActiveSession, Depends(require_role("admin"))]) -> dict:
        return {"role": session.role}

    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url=ORIGIN) as test_client:
        yield test_client


@pytest.fixture
def accounts(app: FastAPI, clock: FakeClock) -> AccountService:
    return AccountService(
        sessions=app.state.db_sessions,
        passwords=app.state.auth.passwords,
        audit=app.state.auth.audit,
        clock=clock,
    )


@pytest.fixture
def make_user(accounts: AccountService) -> Callable[..., Account]:
    def make(role: str = "analyst") -> Account:
        username = f"user.{uuid4().hex[:12]}"
        password = f"pw-{uuid4().hex}"
        user_id = accounts.provision_user(
            username=username, display_name="Synthetic Analyst", role=role, password=password
        )
        return Account(user_id, username, password)

    return make


@pytest.fixture
def user(make_user: Callable[..., Account]) -> Account:
    return make_user()


def set_cookie_attributes(response: Response) -> dict[str, str]:
    (header,) = response.headers.get_list("set-cookie")
    attributes: dict[str, str] = {}
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        attributes[name.lower() if attributes else name] = value
    return attributes


def logged_in(client: TestClient, account: Account) -> dict[str, Any]:
    response = login(client, account.username, account.password)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def session_rows(engine: Engine, user_id: UUID) -> list[Any]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                select(UserSession).where(UserSession.user_id == user_id).order_by("created_at")
            ).mappings()
        )


# --- login, cookies and storage -----------------------------------------------------------


def test_login_issues_a_secure_host_only_session(
    client: TestClient, user: Account, clock: FakeClock
) -> None:
    response = login(client, user.username.upper(), user.password)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user"] == {
        "id": str(user.id),
        "display_name": "Synthetic Analyst",
        "role": "analyst",
    }
    assert datetime.fromisoformat(data["expires_at"]) == clock.now + timedelta(minutes=30)
    assert len(data["csrf_token"]) == 43
    cookie = set_cookie_attributes(response)
    assert set(cookie) >= {SECURE_COOKIE, "httponly", "secure", "path", "samesite", "max-age"}
    assert (cookie["path"], cookie["samesite"].lower(), cookie["max-age"]) == ("/", "lax", "28800")
    assert "domain" not in cookie
    assert response.headers["Cache-Control"] == "no-store"


def test_only_digests_of_session_and_csrf_tokens_are_stored(
    client: TestClient, user: Account, migration_engine: Engine
) -> None:
    data = logged_in(client, user)
    token = client.cookies[SECURE_COOKIE]
    (row,) = session_rows(migration_engine, user.id)
    assert row["token_digest"] == hashlib.sha256(token.encode()).digest()
    assert row["csrf_digest"] == hashlib.sha256(data["csrf_token"].encode()).digest()
    assert token.encode() not in row.values() and data["csrf_token"] not in row.values()


def test_invalid_credentials_are_indistinguishable(
    client: TestClient, make_user: Callable[..., Account], accounts: AccountService
) -> None:
    known, inactive = make_user(), make_user()
    accounts.deactivate_user(inactive.username)
    responses = [
        login(client, known.username, "wrong password!"),
        login(client, "nobody." + uuid4().hex, known.password),
        login(client, inactive.username, inactive.password),
    ]
    for response in responses:
        assert response.status_code == 401
        assert response.json()["error"] == {
            "code": "INVALID_CREDENTIALS",
            "message": "Invalid username or password",
        }
        assert "set-cookie" not in response.headers


def test_login_rotates_any_presented_session(
    client: TestClient, user: Account, migration_engine: Engine
) -> None:
    logged_in(client, user)
    first = client.cookies[SECURE_COOKIE]
    logged_in(client, user)
    second = client.cookies[SECURE_COOKIE]
    assert first != second
    rows = session_rows(migration_engine, user.id)
    assert [row["revoked_at"] is not None for row in rows] == [True, False]
    client.cookies.set(SECURE_COOKIE, first)
    assert client.get("/api/v1/auth/session").json()["error"]["code"] == "SESSION_EXPIRED"


def test_successful_login_rehashes_weaker_password_hashes(
    client: TestClient, user: Account, migration_engine: Engine
) -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(user.password)
    with migration_engine.begin() as connection:
        connection.execute(update(User).where(User.id == user.id).values(password_hash=weak))
    logged_in(client, user)
    with migration_engine.connect() as connection:
        stored = connection.execute(select(User.password_hash).where(User.id == user.id)).scalar()
    assert stored != weak
    assert not PasswordService().needs_rehash(stored)


# --- session lifetime ---------------------------------------------------------------------


def test_session_reports_the_earlier_deadline_and_expires_when_idle(
    client: TestClient, user: Account, clock: FakeClock
) -> None:
    started = clock.now
    data = logged_in(client, user)
    clock.advance(minutes=10)
    session = client.get("/api/v1/auth/session")
    assert session.status_code == 200
    assert datetime.fromisoformat(session.json()["data"]["expires_at"]) == started + timedelta(
        minutes=40
    )
    assert session.json()["data"]["csrf_token"] == data["csrf_token"]
    clock.advance(minutes=30)
    expired = client.get("/api/v1/auth/session")
    assert expired.status_code == 401
    assert expired.json()["error"]["code"] == "SESSION_EXPIRED"


def test_absolute_expiry_ends_an_active_session(
    client: TestClient, user: Account, clock: FakeClock
) -> None:
    started = clock.now
    logged_in(client, user)
    while clock.now + timedelta(minutes=25) < started + timedelta(hours=8):
        clock.advance(minutes=25)
        assert client.get("/api/v1/auth/session").status_code == 200
    last = client.get("/api/v1/auth/session").json()["data"]["expires_at"]
    assert datetime.fromisoformat(last) == started + timedelta(hours=8)
    clock.now = started + timedelta(hours=8)
    assert client.get("/api/v1/auth/session").status_code == 401


def test_last_seen_is_written_at_most_once_a_minute(
    client: TestClient, user: Account, clock: FakeClock, migration_engine: Engine
) -> None:
    started = clock.now
    logged_in(client, user)
    clock.advance(seconds=30)
    client.get("/api/v1/auth/session")
    assert session_rows(migration_engine, user.id)[0]["last_seen_at"] == started
    clock.advance(seconds=31)
    client.get("/api/v1/auth/session")
    assert session_rows(migration_engine, user.id)[0]["last_seen_at"] == clock.now


@pytest.mark.parametrize("action", ["deactivate", "reset"])
def test_deactivation_and_password_reset_revoke_sessions(
    client: TestClient, user: Account, accounts: AccountService, action: str
) -> None:
    logged_in(client, user)
    if action == "deactivate":
        accounts.deactivate_user(user.username)
    else:
        accounts.reset_password(user.username, "a brand new passphrase")
    assert client.get("/api/v1/auth/session").status_code == 401
    assert login(client, user.username, user.password).status_code == 401
    if action == "reset":
        assert login(client, user.username, "a brand new passphrase").status_code == 200


# --- logout, CSRF, Origin, credentials ---------------------------------------------------


def logout(client: TestClient, csrf: str | None, origin: str | None = ORIGIN) -> Response:
    headers = {key: value for key, value in (("Origin", origin), ("X-CSRF-Token", csrf)) if value}
    return client.post("/api/v1/auth/logout", headers=headers)


def test_logout_requires_origin_and_the_session_bound_csrf_token(
    client: TestClient, make_user: Callable[..., Account], app: FastAPI
) -> None:
    other = make_user()
    with TestClient(app, base_url=ORIGIN) as other_client:
        other_csrf = logged_in(other_client, other)["csrf_token"]
    me = make_user()
    csrf = logged_in(client, me)["csrf_token"]
    for response in (
        logout(client, csrf, origin=None),
        logout(client, csrf, origin="https://evil.example"),
        logout(client, None),
        logout(client, "forged-token"),
        logout(client, other_csrf),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CSRF_REJECTED"
    assert client.get("/api/v1/auth/session").status_code == 200


def test_logout_revokes_the_session_and_clears_the_cookie(
    client: TestClient, user: Account
) -> None:
    csrf = logged_in(client, user)["csrf_token"]
    token = client.cookies[SECURE_COOKIE]
    response = logout(client, csrf)
    assert response.status_code == 204
    assert response.content == b""
    assert "X-Request-ID" in response.headers
    cookie = set_cookie_attributes(response)
    assert cookie[SECURE_COOKIE] in ('""', "") and cookie["max-age"] == "0"
    assert "secure" in cookie and "httponly" in cookie
    client.cookies.set(SECURE_COOKIE, token)
    assert client.get("/api/v1/auth/session").status_code == 401
    assert logout(client, csrf).status_code == 401


def test_session_with_bearer_credential_is_rejected(client: TestClient, user: Account) -> None:
    logged_in(client, user)
    response = client.get("/api/v1/auth/session", headers={"Authorization": "Bearer kvk_x"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MIXED_CREDENTIALS"


def test_missing_or_forged_session_cookie(client: TestClient) -> None:
    assert client.get("/api/v1/auth/session").status_code == 401
    client.cookies.set(SECURE_COOKIE, secrets.token_urlsafe(32))
    assert client.get("/api/v1/auth/session").json()["error"]["code"] == "SESSION_EXPIRED"


# --- roles --------------------------------------------------------------------------------


def test_roles_are_enforced_server_side_and_reread_every_request(
    app: FastAPI, make_user: Callable[..., Account], migration_engine: Engine
) -> None:
    for role, expected in (("viewer", 403), ("analyst", 403), ("admin", 200)):
        account = make_user(role)
        with TestClient(app, base_url=ORIGIN) as client:
            logged_in(client, account)
            assert client.get("/api/v1/auth/session").json()["data"]["user"]["role"] == role
            response = client.get("/_test/admin-only")
            assert response.status_code == expected
            if expected == 403:
                assert response.json()["error"]["code"] == "FORBIDDEN"
                with migration_engine.begin() as connection:
                    connection.execute(
                        update(User).where(User.id == account.id).values(role="admin")
                    )
                assert client.get("/_test/admin-only").status_code == 200


def test_anonymous_requests_cannot_reach_role_protected_routes(client: TestClient) -> None:
    assert client.get("/_test/admin-only").status_code == 401


# --- audit and telemetry ------------------------------------------------------------------


def audit_rows(engine: Engine, **where: Any) -> list[Any]:
    query = select(AuditRecord).where(
        *(getattr(AuditRecord, column) == value for column, value in where.items())
    )
    with engine.connect() as connection:
        return list(connection.execute(query).mappings())


def test_successful_authentication_and_provisioning_are_audited(
    client: TestClient, user: Account, app: FastAPI, migration_engine: Engine
) -> None:
    csrf = logged_in(client, user)["csrf_token"]
    assert logout(client, csrf).status_code == 204
    writer = app.state.auth.audit
    (provisioned,) = audit_rows(migration_engine, resource_id=user.id, action="user.provision")
    assert (provisioned["actor_kind"], provisioned["actor_user_id"]) == ("system", None)
    sessions = audit_rows(migration_engine, actor_user_id=user.id)
    assert sorted(row["action"] for row in sessions) == ["auth.login", "auth.logout"]
    for row in [provisioned, *sessions]:
        assert writer.verify(row)
        assert row["outcome"] == "success"
    tampered = dict(sessions[0]) | {"action": "auth.something_else"}
    assert not writer.verify(tampered)


def test_denied_logins_emit_telemetry_not_audit_rows(
    client: TestClient, user: Account, migration_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    before = len(audit_rows(migration_engine))
    with caplog.at_level(logging.WARNING, logger="kavach.security"):
        assert login(client, user.username, "wrong password!").status_code == 401
    assert len(audit_rows(migration_engine)) == before
    (record,) = [r for r in caplog.records if r.name == "kavach.security"]
    assert "event=auth.login_denied reason=invalid_credentials" in record.getMessage()


def test_credentials_never_reach_logs_or_error_bodies(
    client: TestClient, user: Account, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    bodies = [login(client, user.username, "wrong password!").text]
    data = logged_in(client, user)
    token = client.cookies[SECURE_COOKIE]
    bodies.append(client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN}).text)
    assert logout(client, data["csrf_token"]).status_code == 204
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert caplog.records, "expected some log output to inspect"
    for secret in (user.password, "wrong password!", user.username, token, data["csrf_token"]):
        assert secret not in logged
        assert all(secret not in body for body in bodies)


# --- shared throttling --------------------------------------------------------------------


def test_five_failures_block_the_account_and_ip_even_with_the_right_password(
    client: TestClient, user: Account, redis_client: Redis
) -> None:
    for _ in range(5):
        assert login(client, user.username, "wrong password!").status_code == 401
    blocked = login(client, user.username, user.password)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert 1 <= int(blocked.headers["Retry-After"]) <= 900
    assert "set-cookie" not in blocked.headers
    keys = list(redis_client.scan_iter("kavach:test:ratelimit:*"))
    assert len(keys) == 2
    for key in keys:
        assert user.username.encode() not in key and b"testclient" not in key
        assert 0 < redis_client.ttl(key) <= 900


def test_success_resets_the_account_counter(client: TestClient, user: Account) -> None:
    for _ in range(4):
        login(client, user.username, "wrong password!")
    assert login(client, user.username, user.password).status_code == 200
    statuses = [login(client, user.username, "wrong password!").status_code for _ in range(5)]
    assert statuses == [401] * 5


def test_ip_ceiling_spans_usernames(client: TestClient) -> None:
    for _ in range(30):
        assert login(client, "nobody." + uuid4().hex, "wrong password!").status_code == 401
    assert login(client, "fresh." + uuid4().hex, "wrong password!").status_code == 429


def test_throttle_holds_across_separate_processes(user: Account, keys: tuple[str, str]) -> None:
    with ProcessPoolExecutor(2, mp_context=multiprocessing.get_context("spawn")) as pool:
        runs = [pool.submit(failed_logins_in_process, user.username, 6, *keys) for _ in range(2)]
        statuses = [status for run in runs for status in run.result(timeout=120)]
    assert len(statuses) == 12
    assert statuses.count(401) == 5
    assert statuses.count(429) == 7


# --- dependency outages with the real stack -----------------------------------------------


def test_redis_outage_fails_closed_without_creating_sessions(
    migrated_schema: None, keys: tuple[str, str], user: Account, migration_engine: Engine
) -> None:
    app = create_app(auth_settings(*keys, redis_url="redis://:unused@127.0.0.1:1/15"))
    with TestClient(app, base_url=ORIGIN) as client:
        response = login(client, user.username, user.password)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert session_rows(migration_engine, user.id) == []


def test_database_outage_returns_503(
    migrated_schema: None, keys: tuple[str, str], clean_throttle: None
) -> None:
    settings = auth_settings(
        *keys, database_url="postgresql+psycopg://kavach_app:unused@127.0.0.1:1/kavach_test"
    )
    with TestClient(create_app(settings), base_url=ORIGIN) as client:
        response = login(client, "user.x", "some password")
        assert (response.status_code, response.json()["error"]["code"]) == (
            503,
            "DEPENDENCY_UNAVAILABLE",
        )
        client.cookies.set(SECURE_COOKIE, secrets.token_urlsafe(32))
        assert client.get("/api/v1/auth/session").status_code == 503


# --- local development cookie -------------------------------------------------------------


def test_local_development_uses_a_non_secure_dev_cookie(
    migrated_schema: None, keys: tuple[str, str], user: Account, clean_throttle: None
) -> None:
    origin = "http://localhost:8000"
    settings = auth_settings(*keys, app_env="development", app_origin=origin)
    with TestClient(create_app(settings), base_url=origin) as client:
        response = login(client, user.username, user.password, origin=origin)
        assert response.status_code == 200
        cookie = set_cookie_attributes(response)
        assert "kavach_dev_session" in cookie and "secure" not in cookie
        assert client.get("/api/v1/auth/session").status_code == 200


def test_session_count_matches_logins(
    client: TestClient, user: Account, migration_engine: Engine
) -> None:
    for _ in range(3):
        client.cookies.clear()
        logged_in(client, user)
    with migration_engine.connect() as connection:
        count = connection.execute(
            select(func.count()).select_from(UserSession).where(UserSession.user_id == user.id)
        ).scalar_one()
    assert count == 3
