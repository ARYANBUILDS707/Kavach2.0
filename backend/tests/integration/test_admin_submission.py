"""MVP-B4: admin browser SMS submission against real PostgreSQL and Redis.

Order under test (owner requirement): Origin, session, active account, admin role, CSRF,
per-admin limit, body read, validation, `source=simulator` and the `ui-` identifiers, then the
unchanged ingestion service. FastAPI 0.162 reads a *declared* body before any dependency runs;
the SMS route declares none and reads the body itself after authorization. The ASGI tests at
the end prove that a rejected browser request never pulls the body from the server.
"""

import json
import threading
import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from redis import Redis
from sqlalchemy import Engine, func, select

from fakes.support import fake_supervisor, wait_state
from kavach.auth import throttle
from kavach.auth.accounts import AccountService
from kavach.auth.ingest_keys import IngestKeyService
from kavach.db.models import AuditRecord, Event, IncidentEvent
from kavach.main import create_app
from kavach.models.sms_worker import SmsWorkerSupervisor

from .auth_support import ORIGIN, Account, FakeClock, auth_settings, login

pytestmark = pytest.mark.integration

# ASGI spec versions: uvicorn 0.54 reports 2.3; Starlette changes disconnect handling at 2.4.
SPECS = ["2.3", "2.4"]
TEXT = "FICTIONAL UI CANARY 5521: your parcel is held, pay the fee at the link"
SENDER = "VM-UICANA"
RECEIPT_KEYS = {
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


# --- helpers --------------------------------------------------------------------------------------


def browser_body(clock: FakeClock, **override: Any) -> dict[str, Any]:
    return {
        "event_id": f"ui-{uuid.uuid4()}",
        "subscriber_token": f"ui-sub-{uuid.uuid4()}",
        "timestamp": clock.now.isoformat(),
        "source": "simulator",
        "text": TEXT,
        "sender_id": SENDER,
    } | override


def sign_in(client: TestClient, account: Account) -> str:
    """Signs in and returns the CSRF token (held in memory, as the browser will)."""
    response = login(client, account.username, account.password)
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


def post_browser(
    client: TestClient,
    body: Any,
    csrf: str | None,
    *,
    origin: str | None = ORIGIN,
    headers: dict[str, str] | None = None,
) -> Response:
    sent = dict(headers or {})
    if origin is not None:
        sent["Origin"] = origin
    if csrf is not None:
        sent["X-CSRF-Token"] = csrf
    return client.post("/api/v1/events/sms", json=body, headers=sent)


def stored_events(engine: Engine, external_id: str) -> int:
    with engine.connect() as connection:
        return connection.execute(
            select(func.count()).select_from(Event).where(Event.external_event_id == external_id)
        ).scalar_one()


def code(response: Response) -> str:
    return response.json()["error"]["code"]


@pytest.fixture
def admin(make_user: Callable[..., Account]) -> Account:
    return make_user(role="admin")


@pytest.fixture
def csrf(client: TestClient, admin: Account) -> str:
    return sign_in(client, admin)


@pytest.fixture
def key(app: FastAPI, operator_id: UUID) -> str:
    keys: IngestKeyService = app.state.ingest_keys
    return keys.create(
        actor_id=operator_id, name="ui tests", source="simulator", lifetime=timedelta(days=1)
    ).plaintext


# --- success, idempotency and audit ---------------------------------------------------------------


def test_an_admin_submission_is_stored_with_its_incident_and_a_user_audit_actor(
    client: TestClient, csrf: str, admin: Account, clock: FakeClock, migration_engine: Engine
) -> None:
    body = browser_body(clock)
    response = post_browser(client, body, csrf)
    assert response.status_code == 201
    data = response.json()["data"]
    assert set(data) == RECEIPT_KEYS | {"incident_ids"}
    assert data["external_event_id"] == body["event_id"] and data["source"] == "simulator"
    # Receipt reads are key-only, so a browser receipt carries no Location; it uses incidents.
    assert "Location" not in response.headers
    # The worker is disabled (the MVP default until the M4-Q decision).
    assert data["analysis_status"] == "unavailable"
    assert data["warnings"] == ["SMS_CLASSIFIER_UNAVAILABLE"]
    with migration_engine.connect() as connection:
        linked = connection.execute(
            select(IncidentEvent.incident_id).where(
                IncidentEvent.event_id == UUID(data["event_id"])
            )
        ).scalars()
        assert data["incident_ids"] == [str(i) for i in linked]
        [audit] = connection.execute(
            select(
                AuditRecord.action,
                AuditRecord.actor_kind,
                AuditRecord.actor_user_id,
                AuditRecord.actor_ingest_key_id,
            ).where(AuditRecord.resource_id == UUID(data["event_id"]))
        ).all()
    assert audit == ("event.ingest", "user", admin.id, None)
    assert TEXT not in response.text and SENDER not in response.text
    assert body["subscriber_token"] not in response.text
    detail = client.get(f"/api/v1/incidents/{data['incident_ids'][0]}").json()["data"]
    stage = detail["events"][0]["stages"]["sms_classifier"]
    assert stage == {
        "status": "unavailable",
        "reason": "model_not_deployed",
        "duration_ms": 0,
        "model_output": None,
    }


def test_replay_returns_the_same_incident_and_a_changed_payload_conflicts(
    client: TestClient, csrf: str, clock: FakeClock, migration_engine: Engine
) -> None:
    body = browser_body(clock)
    first = post_browser(client, body, csrf).json()["data"]
    replay = post_browser(client, body, csrf)
    assert replay.status_code == 200
    assert "Location" not in replay.headers
    assert replay.json()["data"]["replayed"] is True
    assert replay.json()["data"]["incident_ids"] == first["incident_ids"]
    conflict = post_browser(client, body | {"text": TEXT + " changed"}, csrf)
    assert conflict.status_code == 409 and code(conflict) == "EVENT_ID_CONFLICT"
    assert stored_events(migration_engine, body["event_id"]) == 1
    with migration_engine.connect() as connection:
        audits = connection.execute(
            select(func.count())
            .select_from(AuditRecord)
            .where(AuditRecord.resource_id == UUID(first["event_id"]))
        ).scalar_one()
    assert audits == 1


def test_concurrent_identical_submissions_store_one_event(
    client: TestClient, csrf: str, clock: FakeClock, migration_engine: Engine
) -> None:
    body = browser_body(clock)
    statuses: list[int] = []
    barrier = threading.Barrier(2)

    def send() -> None:
        barrier.wait()
        statuses.append(post_browser(client, body, csrf).status_code)

    threads = [threading.Thread(target=send) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(statuses) == [200, 201]
    assert stored_events(migration_engine, body["event_id"]) == 1


def test_key_receipts_are_unchanged_and_never_carry_incident_ids(
    client: TestClient, key: str, clock: FakeClock
) -> None:
    response = client.post(
        "/api/v1/events/sms",
        json=browser_body(clock, event_id="key-path-1"),
        headers={"Authorization": f"Bearer {key}"},
    )
    assert response.status_code == 201
    assert set(response.json()["data"]) == RECEIPT_KEYS
    event_id = response.json()["data"]["event_id"]
    assert response.headers["Location"] == f"/api/v1/events/{event_id}"
    replay = client.post(
        "/api/v1/events/sms",
        json=json.loads(response.request.content),
        headers={"Authorization": f"Bearer {key}"},
    )
    assert replay.status_code == 200 and "Location" not in replay.headers


# --- authentication, authorization, CSRF and Origin -----------------------------------------------


@pytest.mark.parametrize("role", ["viewer", "analyst"])
def test_non_admin_roles_are_forbidden_before_the_quota_and_store_nothing(
    client: TestClient,
    make_user: Callable[..., Account],
    clock: FakeClock,
    migration_engine: Engine,
    redis_client: Redis,
    role: str,
) -> None:
    token = sign_in(client, make_user(role=role))
    body = browser_body(clock)
    for _ in range(3):
        response = post_browser(client, body, token)
        assert response.status_code == 403 and code(response) == "FORBIDDEN"
    assert stored_events(migration_engine, body["event_id"]) == 0
    assert list(redis_client.scan_iter("kavach:test:ratelimit:ingest:user:*")) == []


@pytest.mark.parametrize(
    "headers",
    [
        {},  # no X-CSRF-Token
        {"X-CSRF-Token": "not-the-token"},
        {"X-CSRF-Token": ""},
    ],
)
def test_a_missing_or_wrong_csrf_token_is_rejected(
    client: TestClient,
    csrf: str,
    clock: FakeClock,
    migration_engine: Engine,
    headers: dict[str, str],
) -> None:
    body = browser_body(clock)
    response = post_browser(client, body, None, headers=headers)
    assert response.status_code == 403 and code(response) == "CSRF_REJECTED"
    assert stored_events(migration_engine, body["event_id"]) == 0


def test_another_sessions_csrf_token_is_rejected(
    app: FastAPI, client: TestClient, csrf: str, admin: Account, clock: FakeClock
) -> None:
    with TestClient(app, base_url=ORIGIN) as other:
        foreign = sign_in(other, admin)
    assert foreign != csrf
    response = post_browser(client, browser_body(clock), foreign)
    assert response.status_code == 403 and code(response) == "CSRF_REJECTED"


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "null",
        ORIGIN + "/",
        "http://kavach.test",
        "https://kavach.test:8443",
        "https://evil.test",
        "https://kavach.test.evil.test",
    ],
)
def test_any_origin_but_the_exact_one_is_rejected(
    client: TestClient, csrf: str, clock: FakeClock, migration_engine: Engine, origin: str | None
) -> None:
    body = browser_body(clock)
    response = post_browser(client, body, csrf, origin=origin)
    assert response.status_code == 403 and code(response) == "CSRF_REJECTED"
    assert stored_events(migration_engine, body["event_id"]) == 0


def test_credentials_must_be_exactly_one(
    app: FastAPI, client: TestClient, csrf: str, key: str, clock: FakeClock
) -> None:
    mixed = post_browser(
        client, browser_body(clock), csrf, headers={"Authorization": f"Bearer {key}"}
    )
    assert mixed.status_code == 401 and code(mixed) == "MIXED_CREDENTIALS"
    with TestClient(app, base_url=ORIGIN) as anonymous:
        none = post_browser(anonymous, browser_body(clock), None)
    assert none.status_code == 401 and code(none) == "INVALID_CREDENTIALS"
    assert none.headers["WWW-Authenticate"] == "Bearer"


def test_expired_revoked_deactivated_and_demoted_admins_are_refused(
    app: FastAPI,
    make_user: Callable[..., Account],
    accounts: AccountService,
    operator_id: UUID,
    clock: FakeClock,
) -> None:
    def fresh() -> tuple[TestClient, Account, str]:
        client = TestClient(app, base_url=ORIGIN)
        client.__enter__()
        account = make_user(role="admin")
        return client, account, sign_in(client, account)

    client, _, token = fresh()
    clock.advance(hours=9)  # past the 8-hour absolute lifetime
    expired = post_browser(client, browser_body(clock), token)
    assert expired.status_code == 401 and code(expired) == "SESSION_EXPIRED"
    client.__exit__(None, None, None)

    client, _, token = fresh()
    cookie = dict(client.cookies)
    assert (
        client.post(
            "/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": token}
        ).status_code
        == 204
    )
    client.cookies.update(cookie)  # replay the revoked cookie
    revoked = post_browser(client, browser_body(clock), token)
    assert revoked.status_code == 401 and code(revoked) == "SESSION_EXPIRED"
    client.__exit__(None, None, None)

    client, account, token = fresh()
    accounts.deactivate_user(actor_id=operator_id, username=account.username)
    inactive = post_browser(client, browser_body(clock), token)
    assert inactive.status_code == 401 and code(inactive) == "SESSION_EXPIRED"
    client.__exit__(None, None, None)

    client, account, token = fresh()
    accounts.change_role(actor_id=operator_id, username=account.username, role="analyst")
    demoted = post_browser(client, browser_body(clock), token)
    assert demoted.status_code == 403 and code(demoted) == "FORBIDDEN"
    client.__exit__(None, None, None)


# --- scope, identifiers and body handling ---------------------------------------------------------


def test_a_non_simulator_source_is_forbidden(
    client: TestClient, csrf: str, clock: FakeClock, migration_engine: Engine
) -> None:
    body = browser_body(clock, source="partner-feed")
    response = post_browser(client, body, csrf)
    assert response.status_code == 403 and code(response) == "FORBIDDEN"
    assert stored_events(migration_engine, body["event_id"]) == 0


@pytest.mark.parametrize(
    "override",
    [
        {"event_id": "sim-run-1-S01-1"},
        {"event_id": "ui-not-a-uuid"},
        {"event_id": f"ui-{str(uuid.uuid4()).upper()}"},
        {"event_id": f"ui-{uuid.uuid1()}"},
        {"event_id": f"x-ui-{uuid.uuid4()}"},
        {"subscriber_token": "sub_demo_user_a"},
        {"subscriber_token": f"ui-{uuid.uuid4()}"},
        {"subscriber_token": f"ui-sub-{uuid.uuid4()}-x"},
    ],
)
def test_browser_identifiers_must_be_the_synthetic_ui_namespaces(
    client: TestClient,
    csrf: str,
    clock: FakeClock,
    migration_engine: Engine,
    override: dict[str, str],
) -> None:
    body = browser_body(clock, **override)
    response = post_browser(client, body, csrf)
    assert response.status_code == 422 and code(response) == "VALIDATION_ERROR"
    assert stored_events(migration_engine, body["event_id"]) == 0
    for value in override.values():
        assert value not in response.text


@pytest.mark.parametrize(
    ("content", "status"),
    [
        (b"{not json", 422),
        (b"[" * 5000 + b"]" * 5000, 422),
        (json.dumps({"event_id": "x"}).encode(), 422),
        (b"x" * (33 * 1024), 413),
    ],
)
def test_malformed_deep_invalid_and_oversized_bodies(
    client: TestClient, csrf: str, content: bytes, status: int
) -> None:
    response = client.post(
        "/api/v1/events/sms",
        content=content,
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert response.status_code == status
    assert set(response.json()["error"]) == {"code", "message"}


@pytest.mark.parametrize(
    "override",
    [
        {"unexpected": "field"},
        {"text": ""},
        {"timestamp": "2026-01-01T00:00:00"},
        {"subscriber_token": "9876543210"},
    ],
)
def test_validation_failures_echo_nothing(
    client: TestClient, csrf: str, clock: FakeClock, override: dict[str, str]
) -> None:
    body = browser_body(clock) | override
    response = post_browser(client, body, csrf)
    assert response.status_code == 422 and code(response) == "VALIDATION_ERROR"
    assert TEXT not in response.text and body["event_id"] not in response.text


# --- limits ---------------------------------------------------------------------------------------


def test_thirty_per_minute_per_admin_counted_before_the_body_then_429(
    app: FastAPI,
    client: TestClient,
    csrf: str,
    make_user: Callable[..., Account],
    key: str,
    clock: FakeClock,
    redis_client: Redis,
) -> None:
    statuses = [post_browser(client, browser_body(clock), csrf).status_code for _ in range(29)]
    statuses.append(post_browser(client, {"invalid": True}, csrf).status_code)  # counts
    assert statuses == [201] * 29 + [422]
    blocked = post_browser(client, browser_body(clock), csrf)
    assert blocked.status_code == 429 and code(blocked) == "RATE_LIMITED"
    assert 1 <= int(blocked.headers["Retry-After"]) <= throttle.SUBMISSION_WINDOW_SECONDS
    # Reads are a separate budget: the submissions spent none of it.
    assert list(redis_client.scan_iter("kavach:test:ratelimit:read:*")) == []
    assert client.get("/api/v1/system/models").status_code == 200
    # Another admin and an ingestion key each have their own budget.
    with TestClient(app, base_url=ORIGIN) as other:
        assert post_browser(other, browser_body(clock), sign_in(other, make_user(role="admin")))
    with TestClient(app, base_url=ORIGIN) as machine:
        keyed = machine.post(
            "/api/v1/events/sms",
            json=browser_body(clock, event_id="key-budget-1"),
            headers={"Authorization": f"Bearer {key}"},
        )
    assert keyed.status_code == 201
    names = [k.decode() for k in redis_client.scan_iter("kavach:test:ratelimit:ingest:user:*")]
    assert len(names) == 2


def test_redis_unavailable_fails_closed_and_stores_nothing(
    client: TestClient,
    csrf: str,
    keys: tuple[str, str],
    clock: FakeClock,
    migration_engine: Engine,
) -> None:
    broken = create_app(
        auth_settings(*keys, redis_url="redis://:unused@127.0.0.1:1/15"), clock=clock
    )
    body = browser_body(clock)
    with TestClient(broken, base_url=ORIGIN) as other:
        other.cookies.update(dict(client.cookies))
        response = post_browser(other, body, csrf)
    assert response.status_code == 503 and code(response) == "DEPENDENCY_UNAVAILABLE"
    assert stored_events(migration_engine, body["event_id"]) == 0


# --- model paths with the test-only fake worker ---------------------------------------------------


@pytest.fixture
def model_client(
    migrated_schema: None, keys: tuple[str, str], clock: FakeClock, tmp_path: Path
) -> TestClient:
    supervisor = fake_supervisor(tmp_path / "sms.lock", inference_timeout_s=0.5)
    app = create_app(auth_settings(*keys), clock=clock, sms_worker=supervisor)
    client = TestClient(app, base_url=ORIGIN)
    client.__enter__()
    assert wait_state(supervisor, "ready") == "ready"
    yield client
    client.__exit__(None, None, None)


def user_ingest_audits(engine: Engine) -> int:
    with engine.connect() as connection:
        return connection.execute(
            select(func.count())
            .select_from(AuditRecord)
            .where(AuditRecord.actor_kind == "user", AuditRecord.action == "event.ingest")
        ).scalar_one()


def assert_nothing_sensitive(response: Response, body: dict[str, Any]) -> None:
    for value in (body["text"], body["sender_id"], body["subscriber_token"]):
        assert value not in response.text
    assert set(response.json()["error"]) == {"code", "message"}


def test_a_saturated_worker_is_429_for_a_browser_session_and_stores_nothing(
    model_client: TestClient,
    make_user: Callable[..., Account],
    clock: FakeClock,
    migration_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    token = sign_in(model_client, make_user(role="admin"))
    payloads = [
        browser_body(clock, text="fake:sleep:0.4 slow"),
        browser_body(clock, text="fake:sleep:0.1 waits"),
        browser_body(clock),
    ]
    responses: list[Response | None] = [None] * 3
    barrier = threading.Barrier(3)

    def send(index: int) -> None:
        barrier.wait()
        time.sleep(0.05 * index)
        responses[index] = post_browser(model_client, payloads[index], token)

    threads = [threading.Thread(target=send, args=(i,)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    assert [r.status_code for r in responses if r is not None] == [201, 201, 429]
    rejected = responses[2]
    assert rejected is not None and rejected.json()["error"]["code"] == "CAPACITY_EXCEEDED"
    assert rejected.headers["Retry-After"] == "1" and "Location" not in rejected.headers
    assert_nothing_sensitive(rejected, payloads[2])
    assert stored_events(migration_engine, payloads[2]["event_id"]) == 0
    # Nothing was stored, so the same ID is analysed afresh on retry.
    retry = post_browser(model_client, payloads[2], token)
    assert retry.status_code == 201 and retry.json()["data"]["analysis_status"] == "complete"
    assert stored_events(migration_engine, payloads[2]["event_id"]) == 1
    for record in caplog.records:
        assert TEXT not in record.getMessage() and SENDER not in record.getMessage()


def test_a_starting_worker_is_503_for_a_browser_session_and_stores_nothing(
    migrated_schema: None,
    keys: tuple[str, str],
    clock: FakeClock,
    tmp_path: Path,
    make_user: Callable[..., Account],
    migration_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    supervisor = fake_supervisor(tmp_path / "hang.lock", mode="hang", start_timeout_s=30)
    app = create_app(auth_settings(*keys), clock=clock, sms_worker=supervisor)
    with TestClient(app, base_url=ORIGIN) as client:
        token = sign_in(client, make_user(role="admin"))
        body = browser_body(clock)
        audits_before = user_ingest_audits(migration_engine)
        response = post_browser(client, body, token)
        # The audit trail gains nothing for a rejected submission.
        assert user_ingest_audits(migration_engine) == audits_before
        assert (response.status_code, response.json()["error"]["code"]) == (
            503,
            "DEPENDENCY_UNAVAILABLE",
        )
        assert response.headers["Retry-After"] == "10" and "Location" not in response.headers
        assert_nothing_sensitive(response, body)
        assert stored_events(migration_engine, body["event_id"]) == 0
    for record in caplog.records:
        assert TEXT not in record.getMessage() and SENDER not in record.getMessage()


def test_an_unusable_worker_stores_the_browser_submission_as_unavailable(
    migrated_schema: None,
    keys: tuple[str, str],
    clock: FakeClock,
    make_user: Callable[..., Account],
    migration_engine: Engine,
) -> None:
    """A worker that cannot run at all (refused at startup) is not a 503: the event is stored
    with the stage unavailable and a reason, as for ingestion keys (M4-I.2)."""
    supervisor = SmsWorkerSupervisor.refused("manifest_invalid")
    app = create_app(auth_settings(*keys), clock=clock, sms_worker=supervisor)
    with TestClient(app, base_url=ORIGIN) as client:
        token = sign_in(client, make_user(role="admin"))
        body = browser_body(clock)
        response = post_browser(client, body, token)
        assert response.status_code == 201 and "Location" not in response.headers
        data = response.json()["data"]
        assert data["analysis_status"] == "unavailable"
        assert data["warnings"] == ["SMS_CLASSIFIER_UNAVAILABLE"]
        for value in (body["text"], body["sender_id"], body["subscriber_token"]):
            assert value not in response.text
        stage = client.get(f"/api/v1/incidents/{data['incident_ids'][0]}").json()["data"]
        reason = stage["events"][0]["stages"]["sms_classifier"]["reason"]
        assert reason == "model_unverified"
    assert stored_events(migration_engine, body["event_id"]) == 1


def test_completed_inference_is_uncalibrated_and_the_receipt_has_no_scores(
    model_client: TestClient, make_user: Callable[..., Account], clock: FakeClock
) -> None:
    token = sign_in(model_client, make_user(role="admin"))
    done = post_browser(model_client, browser_body(clock), token)
    assert done.status_code == 201
    data = done.json()["data"]
    assert data["analysis_status"] == "complete"
    assert data["warnings"] == ["SMS_SCORE_UNCALIBRATED"]
    for absent in ("labels", "fraud", "spam", "legitimate", "score"):
        assert absent not in done.text
    failed = post_browser(model_client, browser_body(clock, text="fake:nan"), token)
    assert failed.status_code == 201
    assert failed.json()["data"]["analysis_status"] == "unavailable"


# --- privacy --------------------------------------------------------------------------------------


def test_no_text_sender_or_subscriber_reaches_logs_or_redis(
    client: TestClient,
    csrf: str,
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
    redis_client: Redis,
) -> None:
    caplog.set_level("DEBUG")
    body = browser_body(clock)
    post_browser(client, body, csrf)
    post_browser(client, body | {"source": "other"}, csrf)
    post_browser(client, body | {"text": ""}, csrf)
    secrets = (TEXT, SENDER, body["subscriber_token"])
    for record in caplog.records:
        assert not any(value in record.getMessage() for value in secrets)
    for name in redis_client.scan_iter("kavach:test:*"):
        assert not any(value.encode() in name for value in secrets)
        if redis_client.type(name) == b"zset":
            for member in redis_client.zrange(name, 0, -1):
                assert not any(value.encode() in member for value in secrets)


# --- ASGI level: the body is never pulled before authorization ------------------------------------


def asgi_post(
    app: FastAPI, headers: dict[str, str], body: bytes, spec: str = "2.3"
) -> tuple[int, list[str]]:
    """Calls the ASGI app directly and records, in order, every `receive()` the app makes and
    the start of the response. Returns the status and that timeline."""
    timeline: list[str] = []
    status: list[int] = []
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        timeline.append("receive")
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        await anyio.sleep(3600)  # a well-behaved client waits; never reached in these tests
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            timeline.append("response.start")
            status.append(message["status"])

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/v1/events/sms",
        "raw_path": b"/api/v1/events/sms",
        "root_path": "",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]
        + [(b"host", b"kavach.test"), (b"content-length", str(len(body)).encode())],
        "client": ("127.0.0.1", 50000),
        "server": ("kavach.test", 443),
        "state": {},
    }

    async def run() -> None:
        with anyio.fail_after(30):
            await app(scope, receive, send)

    anyio.run(run)
    return status[0], timeline


def body_pulled_before_response(timeline: list[str]) -> bool:
    return "receive" in timeline[: timeline.index("response.start")]


@pytest.mark.parametrize("spec", SPECS)
def test_rejected_browser_requests_never_pull_the_body(
    spec: str,
    app: FastAPI,
    client: TestClient,
    csrf: str,
    make_user: Callable[..., Account],
    key: str,
    clock: FakeClock,
) -> None:
    cookie = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
    viewer_client = TestClient(app, base_url=ORIGIN)
    viewer_client.__enter__()
    viewer_csrf = sign_in(viewer_client, make_user(role="viewer"))
    viewer_cookie = "; ".join(f"{n}={v}" for n, v in viewer_client.cookies.items())
    viewer_client.__exit__(None, None, None)
    body = json.dumps(browser_body(clock)).encode()
    json_type = {"Content-Type": "application/json"}
    rejected = {
        "no credentials": ({"Origin": ORIGIN} | json_type, 401),
        "mixed": (
            {"Cookie": cookie, "Authorization": f"Bearer {key}", "Origin": ORIGIN} | json_type,
            401,
        ),
        "wrong origin": ({"Cookie": cookie, "Origin": "https://evil.test"} | json_type, 403),
        "missing origin": ({"Cookie": cookie, "X-CSRF-Token": csrf} | json_type, 403),
        "expired cookie": (
            {"Cookie": "__Host-kavach_session=forged", "Origin": ORIGIN, "X-CSRF-Token": csrf}
            | json_type,
            401,
        ),
        "viewer": (
            {"Cookie": viewer_cookie, "Origin": ORIGIN, "X-CSRF-Token": viewer_csrf} | json_type,
            403,
        ),
        "missing csrf": ({"Cookie": cookie, "Origin": ORIGIN} | json_type, 403),
        "wrong csrf": ({"Cookie": cookie, "Origin": ORIGIN, "X-CSRF-Token": "x"} | json_type, 403),
    }
    for name, (headers, expected) in rejected.items():
        status, timeline = asgi_post(app, headers, body, spec)
        assert status == expected, name
        assert not body_pulled_before_response(timeline), name
    # Over the per-admin limit: also rejected before the body.
    valid = {"Cookie": cookie, "Origin": ORIGIN, "X-CSRF-Token": csrf} | json_type
    for _ in range(throttle.SUBMISSIONS_PER_KEY):
        asgi_post(app, valid, json.dumps(browser_body(clock)).encode(), spec)
    status, timeline = asgi_post(app, valid, json.dumps(browser_body(clock)).encode(), spec)
    assert status == 429 and not body_pulled_before_response(timeline)


@pytest.mark.parametrize("spec", SPECS)
def test_authorized_browser_requests_read_the_body_after_the_checks(
    spec: str, app: FastAPI, client: TestClient, csrf: str, clock: FakeClock
) -> None:
    cookie = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
    headers = {
        "Cookie": cookie,
        "Origin": ORIGIN,
        "X-CSRF-Token": csrf,
        "Content-Type": "application/json",
    }
    for payload, expected in (
        (json.dumps(browser_body(clock)).encode(), 201),
        (b"{not json", 422),
        (json.dumps(browser_body(clock, source="other")).encode(), 403),
        (json.dumps(browser_body(clock, text="")).encode(), 422),
    ):
        status, timeline = asgi_post(app, headers, payload, spec)
        assert status == expected
        assert body_pulled_before_response(timeline), expected
