"""Service-free authentication tests: tokens, passwords, configuration, audit HMAC, throttle
key privacy, and real Redis outages (closed port and a socket that never answers)."""

import json
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from redis import Redis

from kavach.auth.cookies import cookie_policy_for
from kavach.auth.passwords import PasswordService, validate_new_password
from kavach.auth.throttle import LoginThrottle
from kavach.auth.tokens import (
    csrf_token_for,
    new_session_token,
    presented_token_matches,
    token_digest,
)
from kavach.core.config import Settings
from kavach.main import create_app
from kavach.privacy.audit import AuditWriter

ORIGIN = "https://kavach.test"
SECRET = "do-not-leak-" + "k" * 32


def auth_settings(**override: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "database_url": "postgresql+psycopg://kavach_app:unused@127.0.0.1:1/kavach_test",
        "redis_url": "redis://:unused@127.0.0.1:1/15",
        "app_origin": ORIGIN,
        "rate_limit_hmac_key": SECRET,
        "audit_hmac_keys": json.dumps({"v1": SECRET}),
        "audit_hmac_active_version": "v1",
    }
    return Settings(**(values | override))


# --- tokens -------------------------------------------------------------------------------


def test_session_tokens_are_random_and_stored_only_as_digests() -> None:
    first, second = new_session_token(), new_session_token()
    assert first != second and len(first) == 43
    assert len(token_digest(first)) == 32
    assert presented_token_matches(first, token_digest(first))
    for candidate in (None, "", second, first + "x", "a" * 129):
        assert not presented_token_matches(candidate, token_digest(first))


def test_csrf_tokens_are_bound_to_one_session() -> None:
    token = new_session_token()
    assert csrf_token_for(token) == csrf_token_for(token)
    assert csrf_token_for(token) != csrf_token_for(new_session_token())
    assert csrf_token_for(token) not in token


# --- passwords ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def passwords() -> PasswordService:
    return PasswordService()


def test_password_verification(passwords: PasswordService) -> None:
    encoded = passwords.hash("correct horse battery")
    assert encoded.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert passwords.verify(encoded, "correct horse battery")
    assert not passwords.verify(encoded, "wrong password")
    assert not passwords.verify("not-an-argon2-hash", "anything")


def test_unknown_user_never_verifies_even_against_the_dummy(passwords: PasswordService) -> None:
    assert passwords.verify(None, "anything") is False


def test_weaker_parameters_need_rehash(passwords: PasswordService) -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash("pw")
    assert passwords.needs_rehash(weak)
    assert not passwords.needs_rehash(passwords.hash("pw"))


@pytest.mark.parametrize("password", ["short", "x" * 257, "Analyst.One", "ANALYST.ONE"])
def test_new_password_policy(password: str) -> None:
    with pytest.raises(ValueError):
        validate_new_password("analyst.one", password)
    validate_new_password("analyst.one", "a long enough passphrase")


# --- configuration ------------------------------------------------------------------------


def test_complete_configuration_enables_auth() -> None:
    settings = auth_settings()
    assert settings.auth_configured
    assert SECRET not in repr(settings)


@pytest.mark.parametrize(
    "override",
    [
        {"rate_limit_hmac_key": None},
        {"redis_url": None},
        {"audit_hmac_active_version": "v2"},
        {"rate_limit_hmac_key": "too-short"},
        {"audit_hmac_keys": "not json " + SECRET},
        {"audit_hmac_keys": json.dumps({"v1": "short"})},
        {"app_origin": "https://kavach.test/"},
        {"app_origin": "https://kavach.test/app"},
        {"app_origin": "HTTPS://KAVACH.TEST"},
        {"app_origin": "https://kavach.test:443"},
        {"app_origin": "http://kavach.test"},
        {"app_origin": "http://localhost:8000"},
        {"session_idle_minutes": 600},
    ],
)
def test_invalid_auth_configuration_fails_without_echoing_secrets(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError) as error:
        auth_settings(**override)
    assert SECRET not in str(error.value)


def test_partial_auth_configuration_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Authentication requires"):
        Settings(app_env="test", rate_limit_hmac_key=SECRET)


def test_plain_http_origin_only_for_local_development() -> None:
    settings = auth_settings(app_env="development", app_origin="http://localhost:8000")
    assert cookie_policy_for(settings.app_origin or "").name == "kavach_dev_session"
    assert cookie_policy_for(settings.app_origin or "").secure is False
    assert auth_settings(app_env="development", app_origin="http://127.0.0.1:8000")
    secure = cookie_policy_for(ORIGIN)
    assert (secure.name, secure.secure) == ("__Host-kavach_session", True)


# --- audit signing ------------------------------------------------------------------------


def audit_row(writer: AuditWriter) -> dict[str, Any]:
    now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    fields: dict[str, Any] = {
        "id": uuid4(),
        "actor_user_id": uuid4(),
        "actor_ingest_key_id": None,
        "actor_kind": "user",
        "action": "auth.login",
        "resource_type": "session",
        "resource_id": uuid4(),
        "request_id": uuid4(),
        "outcome": "success",
        "created_at": now,
        "key_version": "v1",
        "expires_at": now + timedelta(days=30),
    }
    return fields | {"record_hmac": writer.sign(fields)}


def test_audit_hmac_detects_modification_and_unknown_keys() -> None:
    writer = AuditWriter({"v1": b"k" * 32, "v2": b"j" * 32}, "v1", timedelta(days=30))
    row = audit_row(writer)
    assert len(row["record_hmac"]) == 32
    assert writer.verify(row)
    for field, value in (("action", "auth.logout"), ("outcome", "denied"), ("key_version", "v2")):
        assert not writer.verify(row | {field: value})
    assert not AuditWriter({"v9": b"x" * 32}, "v9", timedelta(days=1)).verify(row)


def test_audit_signature_ignores_timezone_representation() -> None:
    writer = AuditWriter({"v1": b"k" * 32}, "v1", timedelta(days=30))
    row = audit_row(writer)
    shifted = row["created_at"].astimezone(datetime.now().astimezone().tzinfo)
    assert writer.verify(row | {"created_at": shifted})


# --- throttle keys ------------------------------------------------------------------------


def test_throttle_keys_contain_neither_username_nor_ip() -> None:
    throttle = LoginThrottle(Redis(host="127.0.0.1", port=1), b"k" * 32, "test")
    keys = throttle._keys("analyst.one", "203.0.113.7")
    assert all(key.startswith("kavach:test:ratelimit:login:") for key in keys)
    assert not any("analyst" in key or "203.0.113" in key for key in keys)
    other = LoginThrottle(Redis(host="127.0.0.1", port=1), b"j" * 32, "test")
    assert other._keys("analyst.one", "203.0.113.7") != keys


# --- routes without services --------------------------------------------------------------


@pytest.fixture
def unconfigured() -> Iterator[TestClient]:
    with TestClient(create_app(Settings(app_env="test")), base_url=ORIGIN) as client:
        yield client


def test_auth_routes_fail_closed_when_unconfigured(unconfigured: TestClient) -> None:
    login = unconfigured.post(
        "/api/v1/auth/login",
        json={"username": "a", "password": "b"},
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 503
    assert login.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert unconfigured.get("/api/v1/auth/session").status_code == 503


def test_session_cookie_with_bearer_is_rejected(unconfigured: TestClient) -> None:
    unconfigured.cookies.set("__Host-kavach_session", "x")
    response = unconfigured.get(
        "/api/v1/auth/session", headers={"Authorization": "Bearer kvk_example"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MIXED_CREDENTIALS"


class CountingPasswords(PasswordService):
    def __init__(self) -> None:
        super().__init__(PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1))
        self.verifications = 0

    def verify(self, encoded_hash: str | None, password: str) -> bool:
        self.verifications += 1
        return super().verify(encoded_hash, password)


def login_with_redis(redis_url: str) -> tuple[int, dict[str, Any], float, CountingPasswords]:
    app = create_app(auth_settings(redis_url=redis_url))
    counting = CountingPasswords()
    app.state.auth.passwords = counting
    with TestClient(app, base_url=ORIGIN) as client:
        started = time.monotonic()
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "analyst.one", "password": SECRET},
            headers={"Origin": ORIGIN},
        )
        elapsed = time.monotonic() - started
    assert "set-cookie" not in response.headers
    assert SECRET not in response.text
    return response.status_code, response.json(), elapsed, counting


def test_login_fails_closed_when_redis_refuses_connections() -> None:
    status, body, elapsed, counting = login_with_redis("redis://:unused@127.0.0.1:1/15")
    assert (status, body["error"]["code"]) == (503, "DEPENDENCY_UNAVAILABLE")
    assert counting.verifications == 0
    assert elapsed < 1.5


@pytest.fixture
def black_hole() -> Iterator[int]:
    """A TCP listener that accepts connections and never replies (a hung Redis)."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        server.settimeout(0.1)
        while not stop.is_set():
            try:
                held.append(server.accept()[0])
            except TimeoutError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield server.getsockname()[1]
    stop.set()
    thread.join()
    for connection in held:
        connection.close()
    server.close()


def test_login_fails_closed_within_the_time_budget_when_redis_hangs(black_hole: int) -> None:
    status, body, elapsed, counting = login_with_redis(f"redis://:unused@127.0.0.1:{black_hole}/15")
    assert (status, body["error"]["code"]) == (503, "DEPENDENCY_UNAVAILABLE")
    assert counting.verifications == 0
    # One connect plus one 0.5 s read timeout, no retries.
    assert 0.4 < elapsed < 1.5


def test_login_rejects_untrusted_origin_before_anything_else() -> None:
    app = create_app(auth_settings())
    with TestClient(app, base_url=ORIGIN) as client:
        for headers in ({}, {"Origin": "https://evil.example"}, {"Origin": ORIGIN + "/"}):
            response = client.post(
                "/api/v1/auth/login", json={"username": "a", "password": "b"}, headers=headers
            )
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "CSRF_REJECTED"


@pytest.mark.parametrize(
    "body",
    [
        {"username": "a" * 81, "password": "p"},
        {"username": "a", "password": SECRET + "x" * 256},
        {"username": "a", "password": ""},
        {"username": "a", "password": SECRET, "remember_me": True},
        {"username": 7, "password": SECRET},
    ],
)
def test_invalid_login_bodies_are_rejected_without_echo(body: dict[str, Any]) -> None:
    app = create_app(auth_settings())
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post("/api/v1/auth/login", json=body, headers={"Origin": ORIGIN})
    assert response.status_code == 422
    assert SECRET not in response.text and "aaaa" not in response.text


def test_login_with_a_bearer_credential_is_rejected() -> None:
    app = create_app(auth_settings())
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "a", "password": "b"},
            headers={"Origin": ORIGIN, "Authorization": "Bearer kvk_example"},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MIXED_CREDENTIALS"


def test_secrets_do_not_leak_into_redis_url_errors() -> None:
    settings = auth_settings(redis_url=f"redis://:{SECRET}@127.0.0.1:1/15")
    assert SECRET not in repr(settings)
    assert isinstance(settings.redis_url, SecretStr)
