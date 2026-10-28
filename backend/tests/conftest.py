"""HTTP schema harnesses exist only in tests; they are not ingestion endpoints."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi import Response
from fastapi.testclient import TestClient

from kavach.api.schemas.events import CallEvent, SMSEvent
from kavach.core.config import Settings
from kavach.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(Settings(app_env="test", log_level="INFO"))) as test_client:
        yield test_client


@pytest.fixture
def schema_client() -> Iterator[TestClient]:
    app = create_app(Settings(app_env="test", log_level="INFO"))

    @app.post("/_test/sms", status_code=204)
    def validate_sms(event: SMSEvent) -> Response:
        return Response(status_code=204)

    @app.post("/_test/call", status_code=204)
    def validate_call(event: CallEvent) -> Response:
        return Response(status_code=204)

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sms_payload() -> dict[str, object]:
    return {
        "event_id": "sms_001",
        "subscriber_token": "demo_user_A",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "simulator",
        "text": "Synthetic demonstration message",
    }


@pytest.fixture
def call_payload() -> dict[str, object]:
    return {
        "event_id": "call_001",
        "subscriber_token": "demo_user_A",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "simulator",
        "audio_reference": "controlled_sample_09",
    }
