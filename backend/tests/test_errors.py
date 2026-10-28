import pytest
from fastapi.testclient import TestClient

from kavach.core.config import Settings
from kavach.main import create_app


@pytest.mark.parametrize("payload", [None, [], "raw-sensitive-input", 123])
def test_non_object_payloads_are_rejected(schema_client: TestClient, payload: object) -> None:
    response = schema_client.post("/_test/sms", json=payload)
    assert response.status_code == 422
    assert "raw-sensitive-input" not in response.text


def test_validation_errors_do_not_echo_sensitive_input(
    schema_client: TestClient, sms_payload: dict[str, object], caplog: pytest.LogCaptureFixture
) -> None:
    secret = "SYNTHETIC_SECRET_MARKER"
    sms_payload[secret] = secret
    sms_payload["text"] = secret
    response = schema_client.post("/_test/sms", json=sms_payload)
    assert response.status_code == 422
    assert secret not in response.text
    assert secret not in caplog.text
    assert "input" not in response.json()["error"]
    assert response.headers["X-Request-ID"] == response.json()["request_id"]


def test_malformed_json_does_not_echo_body(schema_client: TestClient) -> None:
    response = schema_client.post(
        "/_test/sms",
        content='{"secret":"SYNTHETIC_SECRET_MARKER"',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "SYNTHETIC_SECRET_MARKER" not in response.text


def test_unknown_route_uses_safe_envelope(client: TestClient) -> None:
    response = client.get("/unknown-sensitive-path")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert "unknown-sensitive-path" not in response.text


def test_unexpected_exception_is_sanitized() -> None:
    app = create_app(Settings(app_env="test", log_level="INFO"))

    @app.get("/_test/error")
    def fail() -> None:
        raise RuntimeError("SYNTHETIC_SECRET_MARKER")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_test/error")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "SYNTHETIC_SECRET_MARKER" not in response.text
    assert response.headers["X-Request-ID"] == response.json()["request_id"]
