"""Connectivity, privilege and lifecycle checks against real PostgreSQL and Redis."""

from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
import redis
from fastapi.testclient import TestClient
from psycopg import errors as pg_errors
from redis import Redis
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import ProgrammingError

from kavach.core.config import Settings
from kavach.core.redis_client import check_redis
from kavach.db.engine import check_database, create_session_factory
from kavach.main import create_app

from .conftest import required_url

pytestmark = pytest.mark.integration


def test_runtime_role_connects_to_disposable_test_database(runtime_engine: Engine) -> None:
    check_database(runtime_engine)
    with runtime_engine.connect() as connection:
        row = connection.execute(
            text("SELECT current_database(), current_user, current_setting('server_version_num')")
        ).one()
    assert row[0] == "kavach_test"
    assert row[1] == "kavach_app"
    assert int(row[2]) // 10_000 == 17


@pytest.mark.parametrize("engine_name", ["runtime_engine", "migration_engine"])
def test_application_roles_hold_no_cluster_privileges(
    engine_name: str, request: pytest.FixtureRequest
) -> None:
    engine: Engine = request.getfixturevalue(engine_name)
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls "
                "FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
    assert tuple(row) == (False, False, False, False, False)


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE runtime_must_not_create (id integer)",
        "CREATE TEMPORARY TABLE runtime_must_not_create_temp (id integer)",
        "CREATE SCHEMA runtime_must_not_create_schema",
    ],
)
def test_runtime_role_cannot_create_objects(runtime_engine: Engine, statement: str) -> None:
    with runtime_engine.connect() as connection:
        with pytest.raises(ProgrammingError) as error:
            connection.execute(text(statement))
        assert isinstance(error.value.orig, pg_errors.InsufficientPrivilege)


def test_unit_of_work_commits_or_rolls_back(migration_engine: Engine) -> None:
    table = f"m21_probe_{uuid4().hex[:12]}"
    sessions = create_session_factory(migration_engine)

    with pytest.raises(RuntimeError):
        with sessions.begin() as session:
            session.execute(text(f"CREATE TABLE {table} (id integer)"))
            raise RuntimeError("abort the unit of work")
    assert not inspect(migration_engine).has_table(table)

    try:
        with sessions.begin() as session:
            session.execute(text(f"CREATE TABLE {table} (id integer)"))
        assert inspect(migration_engine).has_table(table)
    finally:
        with sessions.begin() as session:
            session.execute(text(f"DROP TABLE IF EXISTS {table}"))


def test_redis_round_trip_with_expiry(redis_client: Redis) -> None:
    check_redis(redis_client)
    key = f"kavach:test:m21:{uuid4().hex}"
    try:
        assert redis_client.set(key, b"probe", ex=30) is True
        assert redis_client.get(key) == b"probe"
        assert 0 < redis_client.ttl(key) <= 30
    finally:
        redis_client.delete(key)
    assert redis_client.exists(key) == 0


def test_redis_requires_authentication() -> None:
    parts = urlsplit(required_url("TEST_REDIS_URL").get_secret_value())
    netloc = f"{parts.hostname}:{parts.port}" if parts.port else str(parts.hostname)
    anonymous = Redis.from_url(urlunsplit(parts._replace(netloc=netloc)), socket_timeout=2)
    try:
        with pytest.raises((redis.AuthenticationError, redis.ResponseError)):
            anonymous.ping()
    finally:
        anonymous.close()


def test_redis_persistence_is_disabled(redis_client: Redis) -> None:
    assert redis_client.config_get("save") == {"save": ""}
    assert redis_client.config_get("appendonly") == {"appendonly": "no"}


def test_application_lifecycle_against_real_services() -> None:
    settings = Settings(
        app_env="test",
        database_url=required_url("TEST_DATABASE_URL"),
        redis_url=required_url("TEST_REDIS_URL"),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        check_database(app.state.db_engine)
        check_redis(app.state.redis)
        with app.state.db_sessions.begin() as session:
            assert session.execute(text("SELECT 1")).scalar_one() == 1
    assert app.state.db_engine.pool.checkedout() == 0
