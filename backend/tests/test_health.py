from uuid import UUID

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("path", ["/health", "/api/v1/health"])
def test_health_reports_liveness_only(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"status": "ok", "scope": "liveness", "analysis_ready": False}
    assert str(UUID(body["request_id"])) == response.headers["X-Request-ID"]
    assert response.headers["Cache-Control"] == "no-store"


def test_request_ids_are_generated_not_trusted(client: TestClient) -> None:
    first = client.get("/health", headers={"X-Request-ID": "untrusted"})
    second = client.get("/health")
    assert first.json()["request_id"] != "untrusted"
    assert first.json()["request_id"] != second.json()["request_id"]


def test_production_application_has_no_test_harness(client: TestClient) -> None:
    assert set(client.get("/openapi.json").json()["paths"]) == {
        "/health",
        "/api/v1/health",
        "/api/v1/auth/login",
        "/api/v1/auth/session",
        "/api/v1/auth/logout",
        "/api/v1/events/sms",
        "/api/v1/events/call",
        "/api/v1/events/{event_id}",
        "/api/v1/simulator/scenarios",
        "/api/v1/system/models",
    }
    for path in ["/_test/sms", "/_test/call"]:
        assert client.post(path, json={}).status_code == 404
    # The real ingestion routes exist (M3.1) but fail closed without configuration.
    for path in ["/api/v1/events/sms", "/api/v1/events/call"]:
        assert client.post(path, json={}).status_code == 503


def test_health_rejects_mutations(client: TestClient) -> None:
    response = client.post("/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert "GET" in response.headers["Allow"]
