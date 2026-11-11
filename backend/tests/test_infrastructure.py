"""Service-free checks of database/Redis configuration and client lifecycle."""

import pytest
import redis
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import OperationalError

from kavach.core.config import Settings
from kavach.core.redis_client import check_redis, create_redis_client
from kavach.db.engine import check_database, create_db_engine
from kavach.main import create_app

PASSWORD = "do-not-leak-7f3a"
DATABASE_URL = f"postgresql+psycopg://kavach_app:{PASSWORD}@127.0.0.1:1/kavach_test"
REDIS_URL = f"redis://:{PASSWORD}@127.0.0.1:1/15"


def test_service_urls_are_optional_until_used() -> None:
    settings = Settings(app_env="test")
    assert settings.database_url is None
    assert settings.redis_url is None
    app = create_app(settings)
    assert app.state.db_engine is None
    assert app.state.db_sessions is None
    assert app.state.redis is None


def test_service_urls_are_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    settings = Settings()
    assert settings.database_url is not None
    assert settings.database_url.get_secret_value() == DATABASE_URL
    assert settings.redis_url is not None
    assert settings.redis_url.get_secret_value() == REDIS_URL


def test_service_credentials_are_not_rendered() -> None:
    settings = Settings(database_url=DATABASE_URL, redis_url=REDIS_URL)
    assert PASSWORD not in repr(settings)
    assert PASSWORD not in str(settings)
    engine = create_db_engine(SecretStr(DATABASE_URL))
    assert PASSWORD not in repr(engine)
    assert PASSWORD not in str(engine.url)


@pytest.mark.parametrize(
    "url",
    [
        f"postgresql://kavach_app:{PASSWORD}@127.0.0.1/kavach_test",
        f"postgresql+asyncpg://kavach_app:{PASSWORD}@127.0.0.1/kavach_test",
        f"sqlite:///{PASSWORD}.db",
        f"postgresql+psycopg://kavach_app:{PASSWORD}@127.0.0.1",
        f"not a url {PASSWORD}",
    ],
)
def test_invalid_database_url_fails_without_echoing_it(url: str) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(database_url=url)
    assert PASSWORD not in str(error.value)


@pytest.mark.parametrize(
    "url",
    [
        f"http://:{PASSWORD}@127.0.0.1:6379/0",
        f"unix:///tmp/{PASSWORD}.sock",
        f"redis://:{PASSWORD}@/0",
        f"redis://:{PASSWORD}@[::1/0",
    ],
)
def test_invalid_redis_url_fails_without_echoing_it(url: str) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(redis_url=url)
    assert PASSWORD not in str(error.value)


def test_configured_clients_do_not_connect_at_startup() -> None:
    # Both URLs point at a closed port; startup and liveness must still succeed.
    app = create_app(Settings(app_env="test", database_url=DATABASE_URL, redis_url=REDIS_URL))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert app.state.db_engine.pool.checkedout() == 0
    assert app.state.db_sessions is not None


def test_unreachable_database_raises() -> None:
    engine = create_db_engine(SecretStr(DATABASE_URL))
    try:
        with pytest.raises(OperationalError) as error:
            check_database(engine)
        assert PASSWORD not in str(error.value)
    finally:
        engine.dispose()


def test_unreachable_redis_raises() -> None:
    client = create_redis_client(SecretStr(REDIS_URL))
    try:
        with pytest.raises(redis.ConnectionError) as error:
            check_redis(client)
        assert PASSWORD not in str(error.value)
    finally:
        client.close()
