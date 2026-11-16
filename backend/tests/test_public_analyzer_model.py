"""Real HTTP -> Redis -> pinned local model smoke test, fictional inputs only."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kavach.main import create_app
from test_public_analyzer import HEADERS, HOSTED, HOSTED_HEADERS, settings

pytestmark = pytest.mark.model


def test_real_anonymous_predictions_without_database(caplog, tmp_path):
    required = ("SMS_WORKER_PYTHON", "MODEL_DIR", "TEST_REDIS_URL")
    if any(not os.environ.get(name) for name in required):
        pytest.skip("real worker/model/Redis paths not configured")
    repo = Path(__file__).resolve().parents[2]
    config = settings(
        sms_worker_lock_path=tmp_path / "public-worker.lock",
        sms_worker_python=Path(os.environ["SMS_WORKER_PYTHON"]),
        model_dir=Path(os.environ["MODEL_DIR"]),
        model_manifest_path=repo / "deployment/models/sms_classifier.horizon.v1.json",
        redis_url=os.environ["TEST_REDIS_URL"],
        public_analyzer_ip_limit_per_minute=20,
    )
    app = create_app(config)
    with TestClient(app, client=("127.0.0.9", 54321)) as client:
        assert app.state.sms_worker.wait_until(("ready", "unverified", "lock_held"), 120) == "ready"
        for text in (
            "FICTIONAL TEST: Running ten minutes late for dinner.",
            "FICTIONAL TEST: Mega Sale at ShopFictional! Flat 50% off this weekend.",
            "FICTIONAL TEST: Your Northpay account is frozen. Confirm your PIN now.",
        ):
            response = client.post("/api/v1/public/analyze", json={"text": text}, headers=HEADERS)
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["prediction"] in {"fraud", "spam", "legitimate"}
            assert data["experimental"] is True and data["model_ms"] >= 0
            assert text not in response.text + caplog.text
        assert app.state.db_engine is None and app.state.ingestion is None


def test_hosted_mode_code_path_with_the_real_model_in_process(caplog, tmp_path):
    """The hosted configuration (C-15 gate satisfied inside this test process only: pilot, https
    origin, edge header, the reserved approval value) against the real pinned model on fictional
    text. It tests the gate and the plumbing; it is not an approval, and nothing listens on a
    network."""
    required = ("SMS_WORKER_PYTHON", "MODEL_DIR", "TEST_REDIS_URL")
    if any(not os.environ.get(name) for name in required):
        pytest.skip("real worker/model/Redis paths not configured")
    repo = Path(__file__).resolve().parents[2]
    config = settings(
        **HOSTED,
        sms_worker_lock_path=tmp_path / "hosted-worker.lock",
        sms_worker_python=Path(os.environ["SMS_WORKER_PYTHON"]),
        model_dir=Path(os.environ["MODEL_DIR"]),
        model_manifest_path=repo / "deployment/models/sms_classifier.horizon.v1.json",
        redis_url=os.environ["TEST_REDIS_URL"],
        public_analyzer_ip_limit_per_minute=20,
    )
    app = create_app(config)
    with TestClient(app, client=("10.0.0.7", 443)) as client:
        assert app.state.sms_worker.wait_until(("ready", "unverified", "lock_held"), 120) == "ready"
        for text in (
            "FICTIONAL TEST: Running ten minutes late for dinner.",
            "FICTIONAL TEST: Mega Sale at ShopFictional! Flat 50% off this weekend.",
            "FICTIONAL TEST: Your Northpay account is frozen. Confirm your PIN now.",
        ):
            response = client.post(
                "/api/v1/public/analyze", json={"text": text}, headers=HOSTED_HEADERS
            )
            assert response.status_code == 200
            assert response.json()["data"]["prediction"] in {"fraud", "spam", "legitimate"}
            assert text not in response.text + caplog.text
        # Without the edge's address the request fails closed instead of sharing the peer budget.
        no_edge = {name: v for name, v in HOSTED_HEADERS.items() if name != "X-Real-IP"}
        assert (
            client.post("/api/v1/public/analyze", json={"text": "FICTIONAL"}, headers=no_edge)
        ).status_code == 503
        assert app.state.auth is None and app.state.db_engine is None
        assert client.get("/api/v1/incidents").status_code == 404
