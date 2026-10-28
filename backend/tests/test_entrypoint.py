import pytest
from fastapi.testclient import TestClient
from uvicorn import Config


def test_uvicorn_factory_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    config = Config("kavach.main:create_app", factory=True, log_config=None)
    config.load()

    with TestClient(config.loaded_app) as client:
        for path in ("/health", "/api/v1/health"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.json()["data"] == {
                "status": "ok",
                "scope": "liveness",
                "analysis_ready": False,
            }
