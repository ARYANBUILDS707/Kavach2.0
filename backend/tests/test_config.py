import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kavach.core.config import Settings
from kavach.main import create_app


def test_configuration_uses_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    settings = Settings()
    assert settings.app_env == "test"
    assert settings.log_level == "WARNING"


@pytest.mark.parametrize(("key", "value"), [("APP_ENV", "typo"), ("LOG_LEVEL", "verbose")])
def test_invalid_configuration_fails_startup(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    monkeypatch.setenv(key, value)
    with pytest.raises(ValidationError):
        create_app()


def test_pilot_does_not_expose_development_docs() -> None:
    with TestClient(create_app(Settings(app_env="pilot", log_level="INFO"))) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/health").json()["data"]["analysis_ready"] is False
