"""M3.1 event ingestion against real PostgreSQL: authentication and source scope, idempotency
(including concurrency), validation, missing-model behavior, receipts, rollback and privacy."""

import hashlib
import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, func, select, text

from kavach.auth.ingest_keys import IngestKeyService
from kavach.db.models import Assessment, AuditRecord, Event, Incident, IncidentEvent
from kavach.main import create_app
from kavach.privacy.audit import AuditWriter

from .auth_support import ORIGIN, FakeClock, auth_settings

pytestmark = pytest.mark.integration

SMS_TEXT = "Synthetic: your KYC lapses today, update at the link to avoid account freeze"
TOKEN = "sub_demo_user_a"


@pytest.fixture
def make_key(ingest_keys: IngestKeyService, operator_id: UUID) -> Callable[..., str]:
    def make(source: str = "simulator", days: int = 90) -> str:
        return ingest_keys.create(
            actor_id=operator_id,
            name=f"feed {source}",
            source=source,
            lifetime=timedelta(days=days),
        ).plaintext

    return make


@pytest.fixture
def ingest_keys(app: FastAPI) -> IngestKeyService:
    return app.state.ingest_keys


@pytest.fixture
def key(make_key: Callable[..., str]) -> str:
    return make_key()


def sms_body(clock: FakeClock, **override: Any) -> dict[str, Any]:
    return {
        "event_id": f"sms-{uuid4().hex[:12]}",
        "subscriber_token": TOKEN,
        "timestamp": clock.now.isoformat(),
        "source": "simulator",
        "text": SMS_TEXT,
        "sender_id": "VM-KYCUPD",
    } | override


def call_body(clock: FakeClock, **override: Any) -> dict[str, Any]:
    return {
        "event_id": f"call-{uuid4().hex[:12]}",
        "subscriber_token": TOKEN,
        "timestamp": clock.now.isoformat(),
        "source": "simulator",
    } | override


def post(client: TestClient, kind: str, key: str | None, body: Any) -> Response:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return client.post(f"/api/v1/events/{kind}", json=body, headers=headers)


def count(engine: Engine, model: Any, *where: Any) -> int:
    with engine.connect() as connection:
        return connection.execute(
            select(func.count()).select_from(model).where(*where)
        ).scalar_one()


# --- creation, replay and conflict --------------------------------------------------------


def test_first_submission_creates_a_receipt_event_incident_and_audit(
    client: TestClient, key: str, clock: FakeClock, migration_engine: Engine, app: FastAPI
) -> None:
    body = sms_body(clock)
    response = post(client, "sms", key, body)
    assert response.status_code == 201, response.text
    receipt = response.json()["data"]
    assert set(receipt) == {
        "event_id",
        "external_event_id",
        "source",
        "kind",
        "analysis_status",
        "received_at",
        "processing_ms",
        "replayed",
        "warnings",
    }
    assert receipt["external_event_id"] == body["event_id"]
    assert (receipt["source"], receipt["kind"], receipt["analysis_status"]) == (
        "simulator",
        "sms",
        "unavailable",
    )
    assert receipt["replayed"] is False and receipt["warnings"] == ["SMS_CLASSIFIER_UNAVAILABLE"]
    assert response.headers["Location"] == f"/api/v1/events/{receipt['event_id']}"
    event_id = UUID(receipt["event_id"])

    with migration_engine.connect() as connection:
        event = connection.execute(select(Event).where(Event.id == event_id)).mappings().one()
        link = (
            connection.execute(select(IncidentEvent).where(IncidentEvent.event_id == event_id))
            .mappings()
            .one()
        )
        assessment = (
            connection.execute(
                select(Assessment).where(Assessment.incident_id == link["incident_id"])
            )
            .mappings()
            .one()
        )
        incident = (
            connection.execute(select(Incident).where(Incident.id == link["incident_id"]))
            .mappings()
            .one()
        )
        audit = (
            connection.execute(select(AuditRecord).where(AuditRecord.resource_id == event_id))
            .mappings()
            .one()
        )
    assert (event["sms_score"], event["voice_intent_score"], event["synthesis_score"]) == (
        None,
        None,
        None,
    )
    assert event["analysis_status"] == "unavailable" and event["model_versions"] == {}
    assert event["signals"]["stages"]["sms_classifier"]["reason"] == "model_not_deployed"
    assert event["event_time"] == clock.now and event["received_at"] == clock.now
    assert event["expires_at"] == clock.now + timedelta(days=7)
    assert (incident["kind"], incident["incident_key"]) == ("standalone", f"standalone:{event_id}")
    assert (assessment["tier"], assessment["final_score"], assessment["base_score"]) == (
        "unknown",
        None,
        None,
    )
    assert assessment["analysis_status"] == "unavailable"
    assert (audit["action"], audit["actor_kind"]) == ("event.ingest", "ingestor")
    assert audit["actor_ingest_key_id"] is not None
    assert app.state.auth.audit.verify(audit)


def test_identical_replays_return_the_original_receipt(
    client: TestClient, key: str, clock: FakeClock, migration_engine: Engine
) -> None:
    body = sms_body(clock)
    first = post(client, "sms", key, body).json()["data"]
    audits = count(migration_engine, AuditRecord, AuditRecord.action == "event.ingest")
    clock.advance(seconds=30)
    # The same instant written in another timezone is the same canonical payload.
    ist = timezone(timedelta(hours=5, minutes=30))
    equivalent = body | {
        "timestamp": datetime.fromisoformat(body["timestamp"]).astimezone(ist).isoformat()
    }
    for replay_body in (body, equivalent):
        replay = post(client, "sms", key, replay_body)
        assert replay.status_code == 200
        data = replay.json()["data"]
        assert data | {"replayed": False} == first and data["replayed"] is True
        assert "Location" not in replay.headers
    assert count(migration_engine, Event, Event.external_event_id == body["event_id"]) == 1
    assert count(migration_engine, AuditRecord, AuditRecord.action == "event.ingest") == audits


@pytest.mark.parametrize(
    "change",
    [
        {"text": SMS_TEXT + "!"},
        {"sender_id": None},
        {"subscriber_token": "sub_demo_user_b"},
        {"timestamp": "shift"},
    ],
)
def test_a_changed_payload_with_the_same_event_id_conflicts(
    client: TestClient, key: str, clock: FakeClock, migration_engine: Engine, change: dict
) -> None:
    body = sms_body(clock)
    assert post(client, "sms", key, body).status_code == 201
    changed = body | change
    if change.get("timestamp") == "shift":
        changed["timestamp"] = (clock.now - timedelta(seconds=1)).isoformat()
    response = post(client, "sms", key, changed)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EVENT_ID_CONFLICT"
    assert count(migration_engine, Event, Event.external_event_id == body["event_id"]) == 1


def test_event_ids_are_scoped_per_source(
    client: TestClient, key: str, make_key: Callable[..., str], clock: FakeClock
) -> None:
    body = sms_body(clock)
    partner = make_key("partner-a")
    first = post(client, "sms", key, body).json()["data"]
    other = post(client, "sms", partner, body | {"source": "partner-a"})
    assert other.status_code == 201
    assert other.json()["data"]["event_id"] != first["event_id"]


def concurrently(count_: int, action: Callable[[int], int]) -> list[int]:
    results: list[int] = []
    barrier = threading.Barrier(count_)

    def run(index: int) -> None:
        barrier.wait()
        results.append(action(index))

    threads = [threading.Thread(target=run, args=(i,)) for i in range(count_)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_concurrent_identical_submissions_store_one_event(
    app: FastAPI, key: str, clock: FakeClock, migration_engine: Engine
) -> None:
    body = sms_body(clock)
    with TestClient(app, base_url=ORIGIN) as client:
        statuses = concurrently(8, lambda _: post(client, "sms", key, body).status_code)
    assert sorted(statuses) == [200] * 7 + [201]
    assert count(migration_engine, Event, Event.external_event_id == body["event_id"]) == 1
    assert (
        count(
            migration_engine,
            Incident,
            Incident.incident_key.like("standalone:%"),
            Incident.id.in_(
                select(IncidentEvent.incident_id)
                .join(Event, Event.id == IncidentEvent.event_id)
                .where(Event.external_event_id == body["event_id"])
            ),
        )
        == 1
    )


def test_concurrent_conflicting_submissions_keep_exactly_one(
    app: FastAPI, key: str, clock: FakeClock, migration_engine: Engine
) -> None:
    body = sms_body(clock)
    with TestClient(app, base_url=ORIGIN) as client:
        statuses = concurrently(
            8, lambda i: post(client, "sms", key, body | {"text": f"{SMS_TEXT} {i}"}).status_code
        )
    assert sorted(statuses) == [201] + [409] * 7
    assert count(migration_engine, Event, Event.external_event_id == body["event_id"]) == 1


# --- authentication and source scope ------------------------------------------------------


def test_keys_may_only_submit_for_their_own_source(
    client: TestClient, make_key: Callable[..., str], clock: FakeClock, caplog: Any
) -> None:
    partner = make_key("partner-a")
    with caplog.at_level(logging.WARNING, logger="kavach.security"):
        response = post(client, "sms", partner, sms_body(clock))  # body says "simulator"
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert any("ingest.source_forbidden" in r.getMessage() for r in caplog.records)


def test_invalid_expired_revoked_and_missing_keys_are_rejected(
    client: TestClient,
    ingest_keys: IngestKeyService,
    operator_id: UUID,
    make_key: Callable[..., str],
    clock: FakeClock,
) -> None:
    short = make_key(days=1)
    revoked = ingest_keys.create(actor_id=operator_id, name="gone", source="simulator")
    ingest_keys.revoke(actor_id=operator_id, key_id=revoked.key_id)
    clock.advance(days=1)
    for credential in (None, "kvk_" + "A" * 43, revoked.plaintext, short):
        response = post(client, "sms", credential, sms_body(clock))
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_session_cookie_with_a_key_is_rejected(
    client: TestClient, key: str, clock: FakeClock
) -> None:
    client.cookies.set("__Host-kavach_session", "anything")
    response = post(client, "sms", key, sms_body(clock))
    assert (response.status_code, response.json()["error"]["code"]) == (401, "MIXED_CREDENTIALS")


# --- validation and bounds ----------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"subscriber_token": "+91 98765 43210"},
        {"subscriber_token": "9876543210"},
        {"timestamp": "future"},
        {"timestamp": "stale"},
        {"timestamp": "2026-10-31T09:00:00"},
        {"text": ""},
        {"text": "x" * 4097},
        {"kind": "call"},
        {"sms_score": 0.97},
        {"event_id": "../../etc/passwd"},
    ],
)
def test_invalid_events_are_rejected_without_echo(
    client: TestClient, key: str, clock: FakeClock, migration_engine: Engine, change: dict
) -> None:
    body = sms_body(clock) | change
    if change.get("timestamp") == "future":
        body["timestamp"] = (clock.now + timedelta(seconds=61)).isoformat()
    if change.get("timestamp") == "stale":
        body["timestamp"] = (clock.now - timedelta(days=7, seconds=1)).isoformat()
    before = count(migration_engine, Event)
    response = post(client, "sms", key, body)
    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "VALIDATION_ERROR",
        "message": "Request validation failed",
    }
    assert SMS_TEXT not in response.text and "98765" not in response.text
    assert count(migration_engine, Event) == before


def test_malformed_and_oversized_bodies(client: TestClient, key: str) -> None:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    for content in (b"{not json", b"\xff\xfe", b"[]", b"null"):
        response = client.post("/api/v1/events/sms", content=content, headers=headers)
        assert response.status_code == 422
    big = client.post("/api/v1/events/sms", content=b" " * (32 * 1024 + 1), headers=headers)
    assert (big.status_code, big.json()["error"]["code"]) == (413, "PAYLOAD_TOO_LARGE")


def test_metadata_only_calls_record_unavailable_voice_analysis(
    client: TestClient, key: str, clock: FakeClock
) -> None:
    response = post(client, "call", key, call_body(clock))
    assert response.status_code == 201
    assert response.json()["data"]["warnings"] == [
        "SYNTHESIS_UNAVAILABLE",
        "TRANSCRIPTION_UNAVAILABLE",
        "VOICE_INTENT_UNAVAILABLE",
    ]


def test_unknown_audio_references_are_rejected(
    client: TestClient, key: str, clock: FakeClock, migration_engine: Engine
) -> None:
    before = count(migration_engine, Event)
    response = post(client, "call", key, call_body(clock, audio_reference="controlled_sample_09"))
    assert (response.status_code, response.json()["error"]["code"]) == (
        422,
        "UNKNOWN_AUDIO_REFERENCE",
    )
    assert count(migration_engine, Event) == before


# --- receipt recovery ---------------------------------------------------------------------


def test_receipts_are_recoverable_by_the_owning_source_only(
    client: TestClient, key: str, make_key: Callable[..., str], clock: FakeClock
) -> None:
    created = post(client, "sms", key, sms_body(clock)).json()["data"]
    own = client.get(
        f"/api/v1/events/{created['event_id']}", headers={"Authorization": f"Bearer {key}"}
    )
    assert own.status_code == 200
    assert own.json()["data"] == created
    partner = make_key("partner-a")
    for event_id, credential in (
        (created["event_id"], partner),
        (str(uuid4()), key),
        ("not-a-uuid", key),
        ("1; DROP TABLE events", key),
    ):
        response = client.get(
            f"/api/v1/events/{event_id}", headers={"Authorization": f"Bearer {credential}"}
        )
        assert response.status_code == 404
        assert response.json()["error"] == {
            "code": "NOT_FOUND",
            "message": "Request could not be served",
        }
    anonymous = client.get(f"/api/v1/events/{created['event_id']}")
    assert anonymous.status_code == 401


# --- transactions, outages and privacy ----------------------------------------------------


def test_a_failed_audit_write_stores_nothing_and_a_retry_succeeds(
    app: FastAPI, key: str, clock: FakeClock, migration_engine: Engine
) -> None:
    body = sms_body(clock)
    service = app.state.ingestion
    good_audit = service.audit
    service.audit = AuditWriter({"v1": b"k" * 32}, "missing-version", timedelta(days=30))
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        failed = post(client, "sms", key, body)
        assert failed.status_code == 500
        assert failed.json()["error"]["code"] == "INTERNAL_ERROR"
        assert count(migration_engine, Event, Event.external_event_id == body["event_id"]) == 0
        service.audit = good_audit
        assert post(client, "sms", key, body).status_code == 201


def test_database_outage_fails_closed(
    migrated_schema: None, keys: tuple[str, str], key: str, clock: FakeClock
) -> None:
    settings = auth_settings(
        *keys, database_url="postgresql+psycopg://kavach_app:unused@127.0.0.1:1/kavach_test"
    )
    with TestClient(create_app(settings, clock=clock), base_url=ORIGIN) as client:
        response = post(client, "sms", key, sms_body(clock))
    assert (response.status_code, response.json()["error"]["code"]) == (
        503,
        "DEPENDENCY_UNAVAILABLE",
    )


def test_raw_content_is_never_stored_or_logged(
    client: TestClient,
    key: str,
    clock: FakeClock,
    migration_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    body = sms_body(clock)
    created = post(client, "sms", key, body)
    conflict = post(client, "sms", key, body | {"text": SMS_TEXT + " (edited)"})
    assert (created.status_code, conflict.status_code) == (201, 409)
    secrets = (SMS_TEXT, TOKEN, body["sender_id"], key)
    logged = "\n".join(record.getMessage() for record in caplog.records)
    for value in secrets:
        assert value not in logged
        assert value not in created.text and value not in conflict.text
    # Search every text-like column of every table for the raw values.
    with migration_engine.connect() as connection:
        dump = connection.execute(
            text(
                "SELECT string_agg(t::text, ' ') FROM ("
                " SELECT row_to_json(e)::text AS t FROM events e"
                " UNION ALL SELECT row_to_json(a)::text FROM assessments a"
                " UNION ALL SELECT row_to_json(i)::text FROM incidents i"
                " UNION ALL SELECT row_to_json(r)::text FROM audit_records r) rows"
            )
        ).scalar_one()
    for value in (SMS_TEXT, TOKEN, body["sender_id"], key):
        assert value not in dump
    digest = hashlib.sha256(TOKEN.encode()).hexdigest()
    assert digest not in dump  # an unkeyed hash of the token is not stored either
