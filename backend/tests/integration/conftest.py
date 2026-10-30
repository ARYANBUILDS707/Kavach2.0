"""Real-service fixtures; the services come from deployment/compose.dev.yml (or CI)."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from redis import Redis
from sqlalchemy import Connection, Engine

import kavach.db
from kavach.core.redis_client import create_redis_client
from kavach.db.engine import create_db_engine

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
