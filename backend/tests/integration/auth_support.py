"""Shared helpers for authentication integration tests, including the separate-process worker
used to prove that login throttling holds across processes."""

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from httpx import Response

from kavach.core.config import Settings
from kavach.main import create_app

ORIGIN = "https://kavach.test"


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def auth_settings(rate_limit_key: str, audit_keys: str, **override: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "database_url": os.environ["TEST_DATABASE_URL"],
        "redis_url": os.environ["TEST_REDIS_URL"],
        "app_origin": ORIGIN,
        "rate_limit_hmac_key": rate_limit_key,
        "audit_hmac_keys": audit_keys,
        "audit_hmac_active_version": "v1",
    }
    return Settings(**(values | override))


def login(
    client: TestClient, username: str, password: str, *, origin: str | None = ORIGIN
) -> Response:
    headers = {"Origin": origin} if origin else {}
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}, headers=headers
    )


def failed_logins_in_process(
    username: str, attempts: int, rate_limit_key: str, audit_keys: str
) -> list[int]:
    """Runs in a separate OS process with its own app, connection pools and Redis client."""
    app = create_app(auth_settings(rate_limit_key, audit_keys))
    with TestClient(app, base_url=ORIGIN) as client:
        return [login(client, username, "wrong password!").status_code for _ in range(attempts)]
