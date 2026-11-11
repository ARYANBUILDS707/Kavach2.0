"""Real-service fixtures; the services come from deployment/compose.dev.yml (or CI)."""

import io
import json
import os
import secrets
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis import Redis
from sqlalchemy import Connection, Engine

import kavach.db
from kavach.auth.accounts import AccountService
from kavach.cli import main as cli
from kavach.core.redis_client import create_redis_client
from kavach.db.engine import create_db_engine
from kavach.main import create_app

from .auth_support import (
    ORIGIN,
    Account,
    FakeClock,
    add_test_probes,
    auth_settings,
    ensure_operator,
)

MIGRATIONS_DIR = Path(kavach.db.__file__).parent / "migrations"
# The only database these tests may migrate destructively (created by the dev bootstrap).
DISPOSABLE_DATABASE = "kavach_test"


def required_url(name: str) -> SecretStr:
    # Integration tests are selected explicitly, so a missing service is a failure, not a skip.
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} is not set; start deployment/compose.dev.yml (see README)", False)
    return SecretStr(value)


def alembic_config(*, allow_downgrade: bool = False) -> Config:
    # Built in code (no alembic.ini) so Alembic does not reconfigure logging inside pytest.
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["database_url"] = required_url(
        "TEST_MIGRATION_DATABASE_URL"
    ).get_secret_value()
    if allow_downgrade:
        config.attributes["allow_destructive_downgrade"] = DISPOSABLE_DATABASE
    return config


@pytest.fixture(scope="session")
def migrated_schema() -> None:
    """Rebuild the schema from empty once per session on the disposable test database."""
    command.downgrade(alembic_config(allow_downgrade=True), "base")
    command.upgrade(alembic_config(), "head")


def rolled_back(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def runtime_tx(migrated_schema: None, runtime_engine: Engine) -> Iterator[Connection]:
    """A kavach_app transaction that is always rolled back."""
    yield from rolled_back(runtime_engine)


@pytest.fixture
def owner_tx(migrated_schema: None, migration_engine: Engine) -> Iterator[Connection]:
    """A kavach_migrator transaction that is always rolled back."""
    yield from rolled_back(migration_engine)


@pytest.fixture
def retention_engine() -> Iterator[Engine]:
    engine = create_db_engine(required_url("TEST_RETENTION_DATABASE_URL"))
    yield engine
    engine.dispose()


@pytest.fixture
def runtime_engine() -> Iterator[Engine]:
    engine = create_db_engine(required_url("TEST_DATABASE_URL"))
    yield engine
    engine.dispose()


@pytest.fixture
def migration_engine() -> Iterator[Engine]:
    engine = create_db_engine(required_url("TEST_MIGRATION_DATABASE_URL"))
    yield engine
    engine.dispose()


@pytest.fixture
def redis_client() -> Iterator[Redis]:
    client = create_redis_client(required_url("TEST_REDIS_URL"))
    yield client
    client.close()


# --- authentication fixtures shared by the M2.3/M2.4 tests ---------------------------------


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
    return add_test_probes(create_app(auth_settings(*keys), clock=clock))


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
def operator_id(accounts: AccountService) -> UUID:
    return ensure_operator(accounts)


@pytest.fixture
def make_user(accounts: AccountService, operator_id: UUID) -> Callable[..., Account]:
    def make(role: str = "analyst") -> Account:
        username = f"user.{uuid4().hex[:12]}"
        password = f"pw-{uuid4().hex}"
        user_id = accounts.provision_user(
            actor_id=operator_id,
            username=username,
            display_name="Synthetic Analyst",
            role=role,
            password=password,
        )
        return Account(user_id, username, password)

    return make


@pytest.fixture
def user(make_user: Callable[..., Account]) -> Account:
    return make_user()


@pytest.fixture
def run_cli(keys: tuple[str, str], clock: FakeClock, migrated_schema: None) -> Callable[..., Any]:
    settings = auth_settings(
        *keys, retention_database_url=os.environ["TEST_RETENTION_DATABASE_URL"]
    )

    def run(argv: list[str], *stdin_lines: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = cli(
            [*argv, "--stdin"],
            stdin=io.StringIO("".join(f"{line}\n" for line in stdin_lines)),
            out=out,
            err=err,
            clock=clock,
            settings=settings,
        )
        return code, out.getvalue(), err.getvalue()

    return run
