"""Service-free M3.1 checks: canonical payloads, keyed digests, stage reporting, config."""

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kavach.api.schemas.events import CallEvent, SMSEvent
from kavach.core.config import Settings
from kavach.main import create_app
from kavach.privacy.digests import KeyedDigester, UnknownKeyVersion
from kavach.services.ingestion import canonical_payload, unavailable_stages, warnings_from

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
CONTEXT = {"now": NOW}


def sms(**override: Any) -> SMSEvent:
    values: dict[str, Any] = {
        "event_id": "sms-1",
        "subscriber_token": "sub_abc",
        "timestamp": NOW.isoformat(),
        "source": "simulator",
        "text": "Your parcel is held; pay the fee at the link.",
    } | override
    return SMSEvent.model_validate(values, context=CONTEXT)


def test_equivalent_requests_have_identical_canonical_payloads() -> None:
    base = canonical_payload(sms())
    ist = NOW.astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat()
    assert canonical_payload(sms(timestamp=ist)) == base
    assert canonical_payload(sms(timestamp=NOW.isoformat().replace("+00:00", "Z"))) == base
    assert canonical_payload(sms(sender_id=None)) == base
    assert canonical_payload(sms(kind="sms")) == base


@pytest.mark.parametrize(
    "override",
    [
        {"text": "Your parcel is held; pay the fee at the link"},
        {"text": "your parcel is held; pay the fee at the link."},
        {"sender_id": "VM-PARCEL"},
        {"subscriber_token": "sub_abd"},
        {"timestamp": (NOW - timedelta(microseconds=1)).isoformat()},
        {"source": "partner-a"},
    ],
)
def test_any_meaningful_difference_changes_the_canonical_payload(override: dict[str, Any]) -> None:
    assert canonical_payload(sms(**override)) != canonical_payload(sms())


def test_canonical_payload_is_sorted_compact_utf8_json() -> None:
    payload = canonical_payload(sms(text="नमस्ते — your OTP is not to be shared"))
    decoded = json.loads(payload)
    assert list(decoded) == sorted(decoded)
    assert decoded["timestamp"] == "2026-11-04T12:00:00.000000+00:00"
    assert "नमस्ते".encode() in payload and b", " not in payload


def test_keyed_digests_are_versioned_and_rotatable() -> None:
    old = KeyedDigester({"v1": b"a" * 32}, "v1")
    rotated = KeyedDigester({"v1": b"a" * 32, "v2": b"b" * 32}, "v2")
    stored = old.digest(b"payload")
    assert len(stored) == 32
    assert rotated.matches(b"payload", stored, "v1")
    assert rotated.digest(b"payload") != stored
    assert not rotated.matches(b"other", stored, "v1")
    with pytest.raises(UnknownKeyVersion):
        old.digest(b"payload", "v9")
    with pytest.raises(ValueError):
        KeyedDigester({"v1": b"a" * 32}, "v2")


def test_every_model_stage_is_reported_unavailable_with_a_reason() -> None:
    sms_stages = unavailable_stages(sms())
    assert sms_stages == {
        "sms_classifier": {
            "status": "unavailable",
            "reason": "model_not_deployed",
            "duration_ms": 0,
        }
    }
    call = CallEvent.model_validate(
        {
            "event_id": "call-1",
            "subscriber_token": "sub_abc",
            "timestamp": NOW.isoformat(),
            "source": "simulator",
        },
        context=CONTEXT,
    )
    call_stages = unavailable_stages(call)
    assert set(call_stages) == {"transcription", "voice_intent", "synthesis"}
    assert {stage["reason"] for stage in call_stages.values()} == {"audio_not_provided"}
    assert warnings_from({"stages": call_stages}) == [
        "SYNTHESIS_UNAVAILABLE",
        "TRANSCRIPTION_UNAVAILABLE",
        "VOICE_INTENT_UNAVAILABLE",
    ]


@pytest.mark.parametrize(
    "override",
    [
        {"subscriber_token": "+91-98765-43210"},
        {"subscriber_token": "9876543210"},
        {"timestamp": (NOW + timedelta(seconds=61)).isoformat()},
        {"timestamp": (NOW - timedelta(days=7, seconds=1)).isoformat()},
        {"timestamp": "2026-11-04T12:00:00"},
        {"text": "x" * 4097},
        {"text": "   "},
        {"source": "bad source"},
        {"model_score": 0.99},
    ],
)
def test_events_are_validated_against_the_injected_clock(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        sms(**override)


def ingestion_values(**override: Any) -> dict[str, Any]:
    return {
        "app_env": "test",
        "database_url": "postgresql+psycopg://kavach_app:unused@127.0.0.1:1/kavach_test",
        "redis_url": "redis://:unused@127.0.0.1:1/15",
        "app_origin": "https://kavach.test",
        "rate_limit_hmac_key": "r" * 32,
        "audit_hmac_keys": json.dumps({"v1": "a" * 32}),
        "audit_hmac_active_version": "v1",
        "subscriber_hmac_keys": json.dumps({"v1": "s" * 32}),
        "subscriber_hmac_active_version": "v1",
        "payload_hmac_keys": json.dumps({"v1": "p" * 32}),
        "payload_hmac_active_version": "v1",
    } | override


@pytest.mark.parametrize(
    "override",
    [
        {"payload_hmac_keys": None},
        {"subscriber_hmac_active_version": "v2"},
        {"payload_hmac_keys": json.dumps({"v1": "short"})},
        {
            "app_origin": None,
            "rate_limit_hmac_key": None,
            "audit_hmac_keys": None,
            "audit_hmac_active_version": None,
        },
    ],
)
def test_ingestion_configuration_is_all_or_nothing(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(**ingestion_values(**override))
    assert "p" * 32 not in str(error.value) and "s" * 32 not in str(error.value)


def test_ingestion_is_configured_only_with_the_full_group() -> None:
    assert Settings(**ingestion_values()).ingestion_configured
    assert not Settings(app_env="test").ingestion_configured


def test_ingestion_routes_require_an_api_key_before_reading_the_body() -> None:
    app = create_app(Settings(**ingestion_values()))
    with TestClient(app, base_url="https://kavach.test") as client:
        huge = client.post(
            "/api/v1/events/sms",
            content=b"x" * 100_000,
            headers={"Content-Type": "application/json"},
        )
        missing = client.post("/api/v1/events/call", json={})
        receipt = client.get("/api/v1/events/not-a-uuid")
    for response in (huge, missing, receipt):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
