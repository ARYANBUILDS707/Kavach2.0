from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kavach.api.schemas.events import CallEvent, SMSEvent


def test_sms_valid_input_and_optional_sender(
    schema_client: TestClient, sms_payload: dict[str, object]
) -> None:
    assert schema_client.post("/_test/sms", json=sms_payload).status_code == 204
    sms_payload.update(kind="sms", sender_id="DEMO")
    assert schema_client.post("/_test/sms", json=sms_payload).status_code == 204


@pytest.mark.parametrize("reference", ["controlled_sample_09", None])
def test_call_with_reference_or_metadata_only(
    schema_client: TestClient, call_payload: dict[str, object], reference: str | None
) -> None:
    call_payload.update(kind="call", audio_reference=reference)
    assert schema_client.post("/_test/call", json=call_payload).status_code == 204


def test_call_without_optional_reference(
    schema_client: TestClient, call_payload: dict[str, object]
) -> None:
    del call_payload["audio_reference"]
    assert schema_client.post("/_test/call", json=call_payload).status_code == 204


@pytest.mark.parametrize("field", ["event_id", "subscriber_token", "timestamp", "source", "text"])
def test_sms_required_fields(
    schema_client: TestClient, sms_payload: dict[str, object], field: str
) -> None:
    del sms_payload[field]
    assert schema_client.post("/_test/sms", json=sms_payload).status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_id", ""),
        ("event_id", "a" * 129),
        ("event_id", "bad id"),
        ("event_id", "id\n"),
        ("event_id", 123),
        ("event_id", True),
        ("subscriber_token", ""),
        ("subscriber_token", "9876543210"),
        ("subscriber_token", "+919876543210"),
        ("subscriber_token", "987-654-3210"),
        ("subscriber_token", "x" * 129),
        ("source", ""),
        ("source", "x" * 65),
        ("source", "../../private"),
        ("source", []),
        ("timestamp", "not-a-date"),
        ("timestamp", "2026-10-27"),
        ("timestamp", "2026-10-27T10:00:00"),
        ("timestamp", "2026-10-27 10:00:00Z"),
        ("timestamp", "2026-02-30T10:00:00Z"),
        ("timestamp", 1793095200),
        ("timestamp", None),
        ("text", ""),
        ("text", " \n\t"),
        ("text", "x" * 4097),
        ("text", 123),
        ("text", None),
        ("sender_id", "x" * 65),
        ("sender_id", " "),
        ("kind", "call"),
        ("kind", "voice"),
        ("kind", None),
        ("audio_reference", "sample_1"),
        ("sms_score", 0.99),
        ("arbitrary_metadata", {}),
    ],
)
def test_invalid_sms_input_is_rejected(
    schema_client: TestClient, sms_payload: dict[str, object], field: str, value: object
) -> None:
    sms_payload[field] = value
    response = schema_client.post("/_test/sms", json=sms_payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("audio_reference", "../private.wav"),
        ("audio_reference", "/tmp/private.wav"),
        ("audio_reference", "https://example.com/audio"),
        ("audio_reference", "sample.wav"),
        ("audio_reference", ""),
        ("audio_reference", "a" * 129),
        ("audio_reference", 123),
        ("kind", "sms"),
        ("kind", "voice"),
        ("text", "raw transcript"),
        ("transcript", "raw transcript"),
        ("voice_intent_score", 0.99),
        ("subscriber_token", "9876543210"),
        ("timestamp", "invalid"),
    ],
)
def test_invalid_call_input_is_rejected(
    schema_client: TestClient, call_payload: dict[str, object], field: str, value: object
) -> None:
    call_payload[field] = value
    assert schema_client.post("/_test/call", json=call_payload).status_code == 422


@pytest.mark.parametrize("field", ["event_id", "subscriber_token", "timestamp", "source"])
def test_call_required_fields(
    schema_client: TestClient, call_payload: dict[str, object], field: str
) -> None:
    del call_payload[field]
    assert schema_client.post("/_test/call", json=call_payload).status_code == 422


@pytest.mark.parametrize("seconds", [61, -7 * 86400 - 1])
def test_exact_event_time_rejection(sms_payload: dict[str, object], seconds: int) -> None:
    now = datetime(2026, 10, 27, 12, tzinfo=UTC)
    sms_payload["timestamp"] = (now + timedelta(seconds=seconds)).isoformat()
    with pytest.raises(ValidationError):
        SMSEvent.model_validate(sms_payload, context={"now": now})


@pytest.mark.parametrize("seconds", [60, -7 * 86400, 0])
def test_exact_event_time_acceptance(sms_payload: dict[str, object], seconds: int) -> None:
    now = datetime(2026, 10, 27, 12, tzinfo=UTC)
    sms_payload["timestamp"] = (now + timedelta(seconds=seconds)).isoformat()
    event = SMSEvent.model_validate(sms_payload, context={"now": now})
    assert event.timestamp == now + timedelta(seconds=seconds)


def test_timezone_normalization_and_defaults(sms_payload: dict[str, object]) -> None:
    now = datetime(2026, 10, 27, 12, tzinfo=UTC)
    sms_payload["timestamp"] = "2026-10-27T17:30:00+05:30"
    event = SMSEvent.model_validate(sms_payload, context={"now": now})
    assert event.timestamp == now
    assert event.timestamp.tzinfo is UTC
    assert event.kind == "sms"


def test_sensitive_fields_not_in_model_repr(sms_payload: dict[str, object]) -> None:
    event = SMSEvent.model_validate(sms_payload)
    assert sms_payload["text"] not in repr(event)
    assert sms_payload["subscriber_token"] not in repr(event)


def test_default_call_kind(call_payload: dict[str, object]) -> None:
    assert CallEvent.model_validate(call_payload).kind == "call"
