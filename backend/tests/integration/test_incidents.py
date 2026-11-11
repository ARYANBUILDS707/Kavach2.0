"""MVP-B3: incident reads against real PostgreSQL and Redis.

Incidents are created through the real key-authenticated ingestion path with the test-only fake
SMS worker, so stored evidence has exactly the production shape. Each test moves its clock to
its own far-future slot, so incidents written by other tests are expired and invisible.

Covered: session-only access for all three roles; mixed and Bearer credentials; inactive
accounts; filters including `channel`; stable cursor pagination bound to the filters; strict
query validation (`review_status` is 422); the same 404 for missing, malformed and expired IDs;
the detail allowlist (no source, external ID, text, sender, subscriber or digests); uncalibrated
model output and null scores; no-store.
"""

import itertools
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, select

from fakes.support import fake_supervisor, wait_state
from kavach.auth.accounts import AccountService
from kavach.auth.ingest_keys import IngestKeyService
from kavach.db.models import IncidentEvent
from kavach.main import create_app

from .auth_support import Account, FakeClock, add_test_probes, auth_settings, login

pytestmark = pytest.mark.integration

LEGITIMATE = "FICTIONAL DEMO: Running 10 minutes late, start dinner without me."
SENDER = "VM-INCDNT7"
TOKEN = "sub_incident_reader"
# One slot per test, 30 days apart: far beyond the 7-day retention of every other test's rows.
SLOTS = itertools.count()
DETAIL_KEYS = {
    "id",
    "kind",
    "occurred_at",
    "tier",
    "final_score",
    "analysis_status",
    "current_revision",
    "version",
    "latest_review",
    "updated_at",
    "events",
    "assessment",
    "related_incident_ids",
    "reviews",
}
SUMMARY_KEYS = DETAIL_KEYS - {"events", "assessment", "related_incident_ids", "reviews"}
EVENT_KEYS = {
    "id",
    "channel",
    "occurred_at",
    "received_at",
    "analysis_status",
    "processing_ms",
    "sms_score",
    "reason_codes",
    "stages",
    "model_versions",
}


@pytest.fixture
def clock() -> FakeClock:
    clock = FakeClock()
    clock.now = datetime(2031, 1, 1, 12, 0, tzinfo=UTC) + timedelta(days=30 * next(SLOTS))
    return clock


@pytest.fixture
def app(
    migrated_schema: None,
    keys: tuple[str, str],
    clock: FakeClock,
    clean_throttle: None,
    tmp_path: Path,
) -> FastAPI:
    """The conftest configuration plus the fake SMS worker, so evidence is real-shaped."""
    supervisor = fake_supervisor(tmp_path / "sms.lock", inference_timeout_s=0.5)
    return add_test_probes(create_app(auth_settings(*keys), clock=clock, sms_worker=supervisor))


@pytest.fixture
def ready(client: TestClient, app: FastAPI) -> TestClient:
    assert wait_state(app.state.sms_worker, "ready") == "ready"
    return client


@pytest.fixture
def key(app: FastAPI, operator_id: UUID) -> str:
    keys: IngestKeyService = app.state.ingest_keys
    return keys.create(
        actor_id=operator_id, name="incident feed", source="simulator", lifetime=timedelta(days=90)
    ).plaintext


@pytest.fixture
def viewer(make_user: Callable[..., Account]) -> Account:
    return make_user(role="viewer")


def submit(
    client: TestClient, key: str, clock: FakeClock, kind: str = "sms", **override: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "event_id": f"inc-{uuid4().hex[:12]}",
        "subscriber_token": TOKEN,
        "timestamp": clock.now.isoformat(),
        "source": "simulator",
    }
    if kind == "sms":
        body |= {"text": LEGITIMATE, "sender_id": SENDER}
    body |= override
    # The ingestion key goes in a header for this request only; the client keeps no Bearer.
    response = client.post(
        f"/api/v1/events/{kind}", json=body, headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 201, response.status_code
    return response.json()["data"] | {"body": body}


def incident_of(engine: Engine, event_id: str) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                select(IncidentEvent.incident_id).where(IncidentEvent.event_id == UUID(event_id))
            ).scalar_one()
        )


def signed_in(client: TestClient, account: Account) -> TestClient:
    assert login(client, account.username, account.password).status_code == 200
    return client


def get(client: TestClient, path: str, **params: Any) -> Response:
    return client.get(path, params=params)


def error_code(response: Response) -> str:
    return response.json()["error"]["code"]


# --- access ---------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/v1/incidents", f"/api/v1/incidents/{uuid4()}"])
def test_reads_need_a_dashboard_session_and_refuse_keys_and_mixed_credentials(
    ready: TestClient, key: str, viewer: Account, path: str
) -> None:
    anonymous = ready.get(path)
    assert anonymous.status_code == 401 and error_code(anonymous) == "SESSION_EXPIRED"
    bearer = ready.get(path, headers={"Authorization": f"Bearer {key}"})
    assert bearer.status_code == 401 and error_code(bearer) == "SESSION_EXPIRED"
    signed_in(ready, viewer)
    mixed = ready.get(path, headers={"Authorization": f"Bearer {key}"})
    assert mixed.status_code == 401 and error_code(mixed) == "MIXED_CREDENTIALS"


@pytest.mark.parametrize("role", ["viewer", "analyst", "admin"])
def test_every_dashboard_role_can_list_and_read(
    ready: TestClient, key: str, clock: FakeClock, make_user, migration_engine: Engine, role: str
) -> None:
    receipt = submit(ready, key, clock)
    incident_id = incident_of(migration_engine, receipt["event_id"])
    signed_in(ready, make_user(role=role))
    listed = get(ready, "/api/v1/incidents")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [incident_id]
    assert ready.get(f"/api/v1/incidents/{incident_id}").status_code == 200


def test_an_inactive_account_loses_access_on_its_next_read(
    ready: TestClient,
    viewer: Account,
    accounts: AccountService,
    operator_id: UUID,
) -> None:
    signed_in(ready, viewer)
    assert get(ready, "/api/v1/incidents").status_code == 200
    accounts.deactivate_user(actor_id=operator_id, username=viewer.username)
    after = get(ready, "/api/v1/incidents")
    assert after.status_code == 401 and error_code(after) == "SESSION_EXPIRED"


def test_responses_are_not_cacheable_and_carry_a_request_id(
    ready: TestClient, viewer: Account
) -> None:
    signed_in(ready, viewer)
    for response in (
        get(ready, "/api/v1/incidents"),
        ready.get(f"/api/v1/incidents/{uuid4()}"),
        get(ready, "/api/v1/incidents", review_status="unreviewed"),
    ):
        assert response.headers["Cache-Control"] == "no-store"
        assert UUID(response.headers["X-Request-ID"])


# --- list -----------------------------------------------------------------------------------


def test_the_list_is_newest_first_and_the_channel_filter_selects_sms(
    ready: TestClient, key: str, clock: FakeClock, viewer: Account, migration_engine: Engine
) -> None:
    created = []
    for kind in ["sms", "call", "sms"]:
        receipt = submit(ready, key, clock, kind=kind)
        clock.now += timedelta(minutes=1)
        created.append((kind, incident_of(migration_engine, receipt["event_id"])))
    signed_in(ready, viewer)
    everything = get(ready, "/api/v1/incidents").json()
    assert [item["id"] for item in everything["data"]] == [i for _, i in reversed(created)]
    assert set(everything["data"][0]) == SUMMARY_KEYS
    assert everything["page"] == {"next_cursor": None, "has_more": False}
    sms = get(ready, "/api/v1/incidents", channel="sms").json()["data"]
    assert [item["id"] for item in sms] == [i for k, i in reversed(created) if k == "sms"]
    calls = get(ready, "/api/v1/incidents", channel="call").json()["data"]
    assert [item["id"] for item in calls] == [created[1][1]]
    for item in sms:
        assert item["tier"] == "unknown" and item["final_score"] is None
        assert item["latest_review"] is None and item["kind"] == "standalone"


def test_tier_kind_and_time_filters(
    ready: TestClient, key: str, clock: FakeClock, viewer: Account, migration_engine: Engine
) -> None:
    start = clock.now
    ids = []
    for _ in range(3):
        ids.append(incident_of(migration_engine, submit(ready, key, clock)["event_id"]))
        clock.now += timedelta(minutes=1)
    signed_in(ready, viewer)

    def listed(**params: Any) -> list[str]:
        response = get(ready, "/api/v1/incidents", **params)
        assert response.status_code == 200
        return [item["id"] for item in response.json()["data"]]

    assert listed(tier="unknown", kind="standalone") == list(reversed(ids))
    assert listed(tier="high") == [] and listed(kind="pair") == []
    second = (start + timedelta(minutes=1)).isoformat()
    third = (start + timedelta(minutes=2)).isoformat()
    assert listed(**{"from": second}) == [ids[2], ids[1]]  # inclusive
    assert listed(to=third) == [ids[1], ids[0]]  # exclusive
    assert listed(**{"from": second, "to": third}) == [ids[1]]


def test_cursor_pages_cover_every_incident_once_and_are_bound_to_the_filters(
    ready: TestClient, key: str, clock: FakeClock, viewer: Account, migration_engine: Engine
) -> None:
    ids = set()
    # Two incidents share an occurred_at, so the id tiebreak is exercised.
    for step in [0, 1, 0, 1, 1]:
        clock.now += timedelta(seconds=step)
        ids.add(incident_of(migration_engine, submit(ready, key, clock)["event_id"]))
    signed_in(ready, viewer)
    seen: list[str] = []
    cursors: list[str] = []
    params: dict[str, Any] = {"limit": 2, "channel": "sms"}
    while True:
        body = get(ready, "/api/v1/incidents", **params).json()
        seen += [item["id"] for item in body["data"]]
        assert body["page"]["has_more"] is (body["page"]["next_cursor"] is not None)
        if body["page"]["next_cursor"] is None:
            break
        cursors.append(body["page"]["next_cursor"])
        params["cursor"] = cursors[-1]
    assert len(cursors) == 2 and len(seen) == len(set(seen)) == 5 and set(seen) == ids
    first_cursor = cursors[0]
    # A cursor replayed under different filters, or altered, is 400 INVALID_CURSOR.
    for params in (
        {"cursor": first_cursor, "channel": "call"},
        {"cursor": first_cursor},
        {"cursor": first_cursor[:-2] + "!!", "channel": "sms"},
        {"cursor": "not-a-cursor", "channel": "sms"},
    ):
        rejected = get(ready, "/api/v1/incidents", **params)
        assert rejected.status_code == 400 and error_code(rejected) == "INVALID_CURSOR"
    # A different page size is allowed with the same filters.
    assert get(ready, "/api/v1/incidents", cursor=first_cursor, channel="sms", limit=3).is_success


@pytest.mark.parametrize(
    "params",
    [
        {"review_status": "unreviewed"},
        {"unknown": "1"},
        {"limit": "0"},
        {"limit": "101"},
        {"limit": "ten"},
        {"tier": "severe"},
        {"kind": "triple"},
        {"channel": "email"},
        {"from": "2031-01-01T00:00:00"},
        {"to": "2031-01-01"},
        {"from": "2031-01-02T00:00:00Z", "to": "2031-01-01T00:00:00Z"},
        {"from": "2031-01-01T00:00:00Z", "to": "2031-01-01T00:00:00Z"},
        {"occurred_from": "2031-01-01T00:00:00Z"},
        {"cursor": ""},
    ],
)
def test_invalid_queries_are_422_without_echoing_values(
    ready: TestClient, viewer: Account, params: dict[str, str]
) -> None:
    signed_in(ready, viewer)
    response = get(ready, "/api/v1/incidents", **params)
    assert response.status_code == 422 and error_code(response) == "VALIDATION_ERROR"
    assert set(response.json()["error"]) == {"code", "message"}
    for value in params.values():
        if len(value) > 3:
            assert value not in response.text


def test_a_repeated_parameter_is_422(ready: TestClient, viewer: Account) -> None:
    signed_in(ready, viewer)
    response = ready.get("/api/v1/incidents?limit=5&limit=6")
    assert response.status_code == 422 and error_code(response) == "VALIDATION_ERROR"


# --- detail ---------------------------------------------------------------------------------


def test_detail_shows_uncalibrated_model_output_and_nothing_sensitive(
    ready: TestClient, key: str, clock: FakeClock, viewer: Account, migration_engine: Engine
) -> None:
    receipt = submit(ready, key, clock)
    incident_id = incident_of(migration_engine, receipt["event_id"])
    signed_in(ready, viewer)
    response = ready.get(f"/api/v1/incidents/{incident_id}")
    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == DETAIL_KEYS
    assert data["tier"] == "unknown" and data["final_score"] is None
    assert data["related_incident_ids"] == []
    assert data["reviews"] == {"items": [], "page": {"next_cursor": None, "has_more": False}}
    [event] = data["events"]
    assert set(event) == EVENT_KEYS
    assert event["id"] == receipt["event_id"] and event["channel"] == "sms"
    assert event["analysis_status"] == "complete" and event["sms_score"] is None
    assert event["reason_codes"] == ["sms_model_uncalibrated"]
    stage = event["stages"]["sms_classifier"]
    assert stage["status"] == "complete" and stage["reason"] is None
    output = stage["model_output"]
    assert set(output) == {"labels", "top_label", "score_semantics", "truncated"}
    assert set(output["labels"]) == {"legitimate", "spam", "fraud"}
    assert output["score_semantics"] == "uncalibrated_softmax"
    assert event["model_versions"]["sms_classifier"].startswith("horizon-phishing-scam-base@")
    assessment = data["assessment"]
    assert assessment["tier"] == "unknown" and assessment["revision"] == 1
    assert assessment["base_score"] is None and assessment["fusion_score"] is None
    assert assessment["final_score"] is None and assessment["analysis_status"] == "partial"
    assert assessment["policy_version"] == "kavach-m4-uncalibrated-sms-evidence"
    # No source, external ID, message text, sender, subscriber token, digest or evidence body.
    raw = response.text
    for forbidden in (
        LEGITIMATE,
        SENDER,
        TOKEN,
        receipt["body"]["event_id"],
        "simulator",
        "external_event_id",
        '"source"',
        "digest",
        "subscriber",
        '"evidence"',
        "key_version",
    ):
        assert forbidden not in raw, forbidden


def test_detail_of_a_failed_inference_and_of_a_call_shows_unavailable_stages(
    ready: TestClient, key: str, clock: FakeClock, viewer: Account, migration_engine: Engine
) -> None:
    failed = incident_of(migration_engine, submit(ready, key, clock, text="fake:nan")["event_id"])
    call = incident_of(migration_engine, submit(ready, key, clock, kind="call")["event_id"])
    signed_in(ready, viewer)
    sms_event = ready.get(f"/api/v1/incidents/{failed}").json()["data"]["events"][0]
    assert sms_event["analysis_status"] == "unavailable"
    assert sms_event["stages"] == {
        "sms_classifier": {
            "status": "unavailable",
            "reason": "invalid_model_output",
            "duration_ms": sms_event["stages"]["sms_classifier"]["duration_ms"],
            "model_output": None,
        }
    }
    assert sms_event["model_versions"] == {}
    call_event = ready.get(f"/api/v1/incidents/{call}").json()["data"]["events"][0]
    assert call_event["channel"] == "call" and call_event["sms_score"] is None
    assert set(call_event["stages"]) == {"transcription", "voice_intent", "synthesis"}
    for stage in call_event["stages"].values():
        assert stage["status"] == "unavailable" and stage["model_output"] is None
        assert stage["reason"] == "audio_not_provided"


def test_missing_malformed_and_expired_incidents_are_the_same_404(
    ready: TestClient, key: str, clock: FakeClock, viewer: Account, migration_engine: Engine
) -> None:
    incident_id = incident_of(migration_engine, submit(ready, key, clock)["event_id"])
    signed_in(ready, viewer)
    assert ready.get(f"/api/v1/incidents/{incident_id}").status_code == 200
    clock.now += timedelta(days=7, seconds=1)
    # Sign in again: the earlier session is past its absolute lifetime at the new time.
    signed_in(ready, viewer)
    bodies = []
    for path in (incident_id, str(uuid4()), "not-a-uuid", "1;DROP TABLE incidents"):
        response = ready.get(f"/api/v1/incidents/{path}")
        assert response.status_code == 404
        bodies.append({k: v for k, v in response.json().items() if k != "request_id"})
    assert all(body == bodies[0] for body in bodies)
    assert bodies[0] == {"error": {"code": "NOT_FOUND", "message": "Request could not be served"}}
    assert get(ready, "/api/v1/incidents").json()["data"] == []


def test_reads_never_write_to_the_database(
    ready: TestClient, key: str, clock: FakeClock, viewer: Account, migration_engine: Engine
) -> None:
    incident_id = incident_of(migration_engine, submit(ready, key, clock)["event_id"])
    signed_in(ready, viewer)

    def snapshot() -> str:
        with migration_engine.connect() as connection:
            rows = connection.exec_driver_sql(
                "SELECT (SELECT count(*) FROM audit_records), (SELECT count(*) FROM reviews),"
                " (SELECT version FROM incidents WHERE id = %(id)s)",
                {"id": incident_id},
            ).one()
        return json.dumps(list(rows))

    before = snapshot()
    for _ in range(3):
        get(ready, "/api/v1/incidents")
        ready.get(f"/api/v1/incidents/{incident_id}")
    assert snapshot() == before
