"""Real-service fixtures; the services come from deployment/compose.dev.yml (or CI)."""

import os
from collections.abc import Iterator

import pytest
from pydantic import SecretStr
from redis import Redis
from sqlalchemy import Engine

from kavach.core.redis_client import create_redis_client
from kavach.db.engine import create_db_engine


def required_url(name: str) -> SecretStr:
    # Integration tests are selected explicitly, so a missing service is a failure, not a skip.
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} is not set; start deployment/compose.dev.yml (see README)", False)
    return SecretStr(value)


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
