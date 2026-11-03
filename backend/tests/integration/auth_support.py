"""Shared helpers for authentication integration tests, including the separate-process worker
used to prove that login throttling holds across processes."""

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from kavach.auth.accounts import AccountError, AccountService
from kavach.auth.dependencies import IngestPrincipalDep, require_role, require_source
from kavach.auth.service import ActiveSession
from kavach.core.config import Settings
from kavach.main import create_app

ORIGIN = "https://kavach.test"
# Test-only operator, bootstrapped once per test session in the disposable kavach_test database.
OPERATOR_USERNAME = "operator.root"
OPERATOR_PASSWORD = "operator test passphrase"


@dataclass(frozen=True)
class Account:
    id: UUID
    username: str
    password: str


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


def add_test_probes(app: FastAPI) -> FastAPI:
    """Test-only routes exercising the dependencies that real routes will use from M3 on."""

    @app.get("/_test/admin-only")
    def admin_only(session: Annotated[ActiveSession, Depends(require_role("admin"))]) -> dict:
        return {"role": session.role}

    @app.get("/_test/ingest/{source}")
    def ingest_probe(source: str, principal: IngestPrincipalDep) -> dict:
        require_source(principal, source)
        return {"key_id": str(principal.key_id), "source": principal.source}

    return app


def ensure_operator(accounts: AccountService) -> UUID:
    """The bootstrap admin used as the acting operator; created on first use."""
    try:
        return accounts.bootstrap_admin(
            username=OPERATOR_USERNAME, display_name="Test Operator", password=OPERATOR_PASSWORD
        )
    except AccountError:
        return accounts.authenticate_operator(OPERATOR_USERNAME, OPERATOR_PASSWORD)


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
