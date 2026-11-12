"""HTTP/security tests. Test doubles here never enter a runtime build."""

import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from redis import ConnectionError

from kavach.core.config import Settings
from kavach.main import create_app
from kavach.models.sms_worker import SmsInferenceResult, SmsModelEvidence, SmsWorkerSupervisor
from kavach.services.public_analyzer import PublicQuota

ORIGIN = "http://127.0.0.1:5184"
HEADERS = {"Origin": ORIGIN, "X-Kavach-Analyzer": "1"}
TEXT = "FICTIONAL TEST: dinner at six."


def settings(**overrides):
    return Settings(
        **(
            {
                "public_analyzer_only": True,
                "public_analyzer_mode": "local-experimental",
                "app_origin": ORIGIN,
                "redis_url": "redis://127.0.0.1:6379/15",
                "rate_limit_hmac_key": "test-only-public-key-" * 3,
                "sms_worker_enabled": True,
                "sms_model_authorization": "experimental-local-unvalidated",
                "sms_worker_python": Path(sys.executable),
                "model_dir": Path("/tmp/models"),
                "model_manifest_path": Path("/tmp/manifest.json"),
            }
            | overrides
        )
    )


@pytest.fixture
def app():
    worker = Mock(spec=SmsWorkerSupervisor)
    worker.classify.return_value = SmsInferenceResult(
        "complete",
        None,
        SmsModelEvidence("test-double", {}, "legitimate", False),
        4,
        0,
        5,
    )
    application = create_app(settings(), sms_worker=worker)
    application.state.public_quota = Mock()
    return application


@pytest.fixture
def client(app):
    with TestClient(app, client=("127.0.0.1", 54321)) as client:
        yield client


def test_class_only_no_state_and_no_private_routes(client, app, caplog):
    response = client.post("/api/v1/public/analyze", json={"text": TEXT}, headers=HEADERS)
    assert response.status_code == 200
    assert set(response.json()["data"]) == {
        "prediction",
        "experimental",
        "truncated",
        "model_ms",
        "total_ms",
    }
    assert TEXT not in response.text + caplog.text
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert app.state.db_engine is None and app.state.auth is None and app.state.ingestion is None
    assert app.state.sms_worker.classify.call_args.args[0] == TEXT
    for path in ("incidents", "system/models", "auth/session", "events/sms"):
        assert client.get(f"/api/v1/{path}").status_code == 404


@pytest.mark.parametrize(
    "headers", [{}, {"Origin": "https://evil.test", "X-Kavach-Analyzer": "1"}, {"Origin": ORIGIN}]
)
def test_origin_guard_precedes_body_and_quota(client, app, headers):
    response = client.post("/api/v1/public/analyze", content="not json", headers=headers)
    assert response.status_code == 403
    app.state.public_quota.reserve.assert_not_called()
    app.state.sms_worker.classify.assert_not_called()
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "body",
    [
        {"text": ""},
        {"text": " "},
        {"text": "x" * 501},
        {"text": 1},
        {"text": TEXT, "extra": TEXT},
        {"text": "\ud800"},
        [],
    ],
)
def test_invalid_input_never_reaches_model(client, app, body):
    response = client.post(
        "/api/v1/public/analyze",
        content=json.dumps(body),
        headers=HEADERS | {"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert TEXT not in response.text
    app.state.sms_worker.classify.assert_not_called()


def test_body_bound_and_media_type(client):
    assert (
        client.post(
            "/api/v1/public/analyze",
            content="x" * 32769,
            headers=HEADERS | {"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    assert client.post("/api/v1/public/analyze", content=TEXT, headers=HEADERS).status_code == 415


@pytest.mark.parametrize(
    ("reason", "status", "code"),
    [
        ("inference_saturated", 429, "CAPACITY_EXCEEDED"),
        ("worker_busy", 429, "CAPACITY_EXCEEDED"),
        ("inference_timeout", 503, "PROCESSING_TIMEOUT"),
        ("worker_crashed", 503, "DEPENDENCY_UNAVAILABLE"),
        ("model_not_deployed", 503, "DEPENDENCY_UNAVAILABLE"),
        ("worker_starting", 503, "DEPENDENCY_UNAVAILABLE"),
    ],
)
def test_explicit_failures(client, app, reason, status, code):
    app.state.sms_worker.classify.return_value = SmsInferenceResult(
        "unavailable", reason, None, None, 0, 0
    )
    response = client.post("/api/v1/public/analyze", json={"text": TEXT}, headers=HEADERS)
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert "prediction" not in response.text


def test_redis_failure_fails_closed(client, app):
    redis = Mock()
    redis.register_script.return_value.side_effect = ConnectionError("private error")
    app.state.public_quota = PublicQuota(redis, b"test key", "test", 5, 60)
    response = client.post("/api/v1/public/analyze", json={"text": TEXT}, headers=HEADERS)
    assert response.status_code == 503 and "private error" not in response.text
    app.state.sms_worker.classify.assert_not_called()


def test_forwarded_ip_is_not_trusted(client, app):
    client.post(
        "/api/v1/public/analyze",
        json={"text": TEXT},
        headers=HEADERS | {"X-Forwarded-For": "8.8.8.8"},
    )
    assert app.state.public_quota.reserve.call_args.args[0] == "127.0.0.1"


def test_saturation_rejects_before_body(client, app):
    slots = app.state.public_slots
    slots.acquire()
    slots.acquire()
    try:
        response = client.post("/api/v1/public/analyze", json={"text": TEXT}, headers=HEADERS)
        assert response.status_code == 429
        app.state.sms_worker.classify.assert_not_called()
    finally:
        slots.release()
        slots.release()


def test_disabled_by_default():
    with TestClient(create_app(Settings(public_analyzer_only=True))) as client:
        assert client.get("/api/v1/public/analyzer").json()["data"]["enabled"] is False
        assert client.post("/api/v1/public/analyze").json()["error"]["code"] == "ANALYZER_DISABLED"


@pytest.mark.parametrize(
    "overrides",
    [
        {"public_analyzer_mode": "hosted"},
        {"public_analyzer_mode": "hosted", "public_analyzer_hosted_approval": "c15-owner-approved"},
        {"app_env": "pilot", "app_origin": "https://example.test"},
        {"app_origin": "https://example.test"},
        {"sms_model_authorization": None},
        {"sms_worker_enabled": False},
        {"redis_url": None},
        {"rate_limit_hmac_key": None},
        {"database_url": "postgresql+psycopg://localhost/private"},
    ],
)
def test_gates_cannot_be_bypassed(overrides):
    with pytest.raises(ValidationError):
        settings(**overrides)


def test_built_public_host_headers_and_private_route_absence(tmp_path):
    (tmp_path / "index.html").write_text("<html>public app</html>")
    config = Settings(public_analyzer_only=True, public_frontend_dir=tmp_path, app_env="pilot")
    with TestClient(create_app(config)) as client:
        for path in ("/", "/analyze", "/examples"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
            assert response.headers["strict-transport-security"] == "max-age=31536000"
        for path in ("/admin", "/admin/login", "/api/v1/incidents", "/missing"):
            assert client.get(path).status_code == 404


def test_local_mode_does_not_relax_private_api_permissions():
    # The shared operator application still rejects anonymous callers; public-only omits routes.
    with TestClient(create_app(Settings())) as client:
        assert client.get("/api/v1/incidents").status_code in (401, 503)
        assert client.post("/api/v1/events/sms", json={"text": TEXT}).status_code in (401, 403, 503)
