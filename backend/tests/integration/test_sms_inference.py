"""M4-I.2: the SMS worker connected to ingestion, against real PostgreSQL and Redis.

The worker is the test-only fake (`tests/fakes/fake_sms_worker.py`): a real child process
speaking the real protocol with scripted faults. Every message is fictional.

Covered:
- authentication, scope and limits still run first;
- idempotency never re-runs inference;
- the failure matrix of design §6.4;
- outages;
- the cross-process model-copy lock;
- readiness;
- privacy.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from redis import Redis
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import OperationalError

import kavach.db.event_repository as repo
from fakes.support import fake_supervisor, fake_worker_config, wait_state, worker_pid
from kavach.auth.ingest_keys import IngestKeyService
from kavach.correlation.candidates import CandidateIndex
from kavach.db.models import Assessment, AuditRecord, Event, IncidentEvent
from kavach.main import create_app
from kavach.models.sms_worker import SmsWorkerSupervisor

from .auth_support import ORIGIN, FakeClock, add_test_probes, auth_settings, login

pytestmark = pytest.mark.integration

LEGITIMATE = "FICTIONAL DEMO: Running 10 minutes late, start dinner without me."
PRIVATE = "FICTIONAL PRIVATE 7731-INGEST-CANARY body text"
SENDER = "VM-CANARY7"
TOKEN = "sub_model_demo"


# --- fixtures ----------------------------------------------------------------------------------


@pytest.fixture
def lock_path(tmp_path: Path) -> Path:
    return tmp_path / "sms.lock"


@pytest.fixture
def report(tmp_path: Path) -> Path:
    return tmp_path / "worker.json"


@pytest.fixture
def app(
    migrated_schema: None,
    keys: tuple[str, str],
    clock: FakeClock,
    clean_throttle: None,
    lock_path: Path,
    report: Path,
) -> FastAPI:
    """Overrides the conftest app: the same configuration plus the fake SMS worker."""
    supervisor = fake_supervisor(lock_path, report=report, inference_timeout_s=0.5)
    return add_test_probes(create_app(auth_settings(*keys), clock=clock, sms_worker=supervisor))


@pytest.fixture
def ready_client(client: TestClient, app: FastAPI) -> TestClient:
    assert wait_state(app.state.sms_worker, "ready") == "ready"
    return client


@pytest.fixture
def key(app: FastAPI, operator_id: UUID) -> str:
    keys: IngestKeyService = app.state.ingest_keys
    from datetime import timedelta

    return keys.create(
        actor_id=operator_id,
        name="sms model feed",
        source="simulator",
        lifetime=timedelta(days=90),
    ).plaintext


@pytest.fixture
def calls(app: FastAPI) -> list[str]:
    """Counts every classify call the ingestion service makes (texts are not kept)."""
    return count_calls(app.state.sms_worker)


@pytest.fixture
def make_client(
    migrated_schema: None, keys: tuple[str, str], clock: FakeClock, tmp_path: Path
) -> Iterator[Callable[..., tuple[FastAPI, TestClient]]]:
    opened: list[TestClient] = []

    def make(supervisor: SmsWorkerSupervisor | None = None, **settings: Any):
        app = create_app(auth_settings(*keys, **settings), clock=clock, sms_worker=supervisor)
        client = TestClient(app, base_url=ORIGIN)
        client.__enter__()
        opened.append(client)
        return app, client

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def count_calls(supervisor: SmsWorkerSupervisor) -> list[str]:
    """Record every classify call (no text is kept) and still forward it."""
    seen: list[str] = []
    original = supervisor.classify

    def counting(text: str, deadline: float):  # type: ignore[no-untyped-def]
        seen.append("call")
        return original(text, deadline)

    supervisor.classify = counting  # type: ignore[method-assign]
    return seen


def body(clock: FakeClock, text_value: str = LEGITIMATE, **override: Any) -> dict[str, Any]:
    return {
        "event_id": f"sms-{uuid4().hex[:12]}",
        "subscriber_token": TOKEN,
        "timestamp": clock.now.isoformat(),
        "source": "simulator",
        "text": text_value,
    } | override


def post(client: TestClient, key: str | None, payload: Any) -> Response:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return client.post("/api/v1/events/sms", json=payload, headers=headers)


def stored(engine: Engine, external_id: str) -> dict[str, Any] | None:
    with engine.connect() as connection:
        row = (
            connection.execute(select(Event).where(Event.external_event_id == external_id))
            .mappings()
            .first()
        )
        return dict(row) if row else None


def assessment_of(engine: Engine, event_id: UUID) -> dict[str, Any]:
    with engine.connect() as connection:
        link = (
            connection.execute(select(IncidentEvent).where(IncidentEvent.event_id == event_id))
            .mappings()
            .one()
        )
        return dict(
            connection.execute(
                select(Assessment).where(Assessment.incident_id == link["incident_id"])
            )
            .mappings()
            .one()
        )


def events_with(engine: Engine, external_id: str) -> int:
    with engine.connect() as connection:
        return connection.execute(
            select(func.count()).select_from(Event).where(Event.external_event_id == external_id)
        ).scalar_one()


def stage(row: dict[str, Any]) -> dict[str, Any]:
    return row["signals"]["stages"]["sms_classifier"]


# --- successful inference and stored contract ----------------------------------------------------


def test_sms_is_classified_and_only_uncalibrated_evidence_is_stored(
    ready_client: TestClient, key: str, clock: FakeClock, migration_engine: Engine
) -> None:
    payload = body(clock, sender_id=SENDER)
    response = post(ready_client, key, payload)
    assert response.status_code == 201, response.text
    receipt = response.json()["data"]
    assert receipt["analysis_status"] == "complete"
    assert receipt["warnings"] == ["SMS_SCORE_UNCALIBRATED"]
    assert "sms_score" not in receipt and "labels" not in json.dumps(receipt)

    row = stored(migration_engine, payload["event_id"])
    assert row is not None
    assert row["sms_score"] is None, "uncalibrated evidence never becomes sms_score"
    assert row["analysis_status"] == "complete"
    assert row["signals"] == {
        "schema_version": 2,
        "stages": {
            "sms_classifier": {
                "status": "complete",
                "reason": None,
                "duration_ms": 3,
                "model_output": {
                    "labels": {"legitimate": 0.1, "spam": 0.2, "fraud": 0.7},
                    "top_label": "fraud",
                    "score_semantics": "uncalibrated_softmax",
                    "truncated": False,
                },
            }
        },
        "reason_codes": ["sms_model_uncalibrated"],
    }
    version = row["model_versions"]["sms_classifier"]
    assert version.startswith("horizon-phishing-scam-base@fa686fc0d6a3+m1:")

    assessment = assessment_of(migration_engine, row["id"])
    assert (assessment["tier"], assessment["final_score"], assessment["base_score"]) == (
        "unknown",
        None,
        None,
    )
    assert assessment["analysis_status"] == "partial"
    assert assessment["policy_version"] == "kavach-m4-uncalibrated-sms-evidence"
    assert assessment["model_versions"] == {"sms_classifier": version}
    assert assessment["evidence"]["reasons"] == [
        "sms_model_uncalibrated",
        "no_calibrated_base_signal",
    ]
    assert assessment["evidence"]["sms_model_evidence"]["score_semantics"] == "uncalibrated_softmax"

    lookup = ready_client.get(
        f"/api/v1/events/{receipt['event_id']}", headers={"Authorization": f"Bearer {key}"}
    )
    assert lookup.status_code == 200
    assert {k: lookup.json()["data"][k] for k in ("analysis_status", "warnings")} == {
        "analysis_status": "complete",
        "warnings": ["SMS_SCORE_UNCALIBRATED"],
    }


def test_calls_keep_the_no_model_behaviour(
    ready_client: TestClient, key: str, clock: FakeClock, calls: list[str]
) -> None:
    payload = {
        "event_id": f"call-{uuid4().hex[:8]}",
        "subscriber_token": TOKEN,
        "timestamp": clock.now.isoformat(),
        "source": "simulator",
    }
    response = ready_client.post(
        "/api/v1/events/call", json=payload, headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 201
    assert response.json()["data"]["analysis_status"] == "unavailable"
    assert calls == []


# --- idempotency -------------------------------------------------------------------------------


def test_replay_returns_the_stored_result_and_never_reruns_inference(
    ready_client: TestClient,
    key: str,
    clock: FakeClock,
    calls: list[str],
    migration_engine: Engine,
) -> None:
    payload = body(clock)
    first = post(ready_client, key, payload)
    assert first.status_code == 201 and calls == ["call"]
    replay = post(ready_client, key, payload)
    assert replay.status_code == 200 and replay.json()["data"]["replayed"] is True
    assert replay.json()["data"]["warnings"] == first.json()["data"]["warnings"]
    conflict = post(ready_client, key, payload | {"text": LEGITIMATE + " changed"})
    assert (conflict.status_code, conflict.json()["error"]["code"]) == (409, "EVENT_ID_CONFLICT")
    assert calls == ["call"], "replays and conflicts never reach the worker"
    assert events_with(migration_engine, payload["event_id"]) == 1


def test_concurrent_first_submissions_store_exactly_one_event(
    ready_client: TestClient, key: str, clock: FakeClock, migration_engine: Engine
) -> None:
    payload = body(clock, text_value="fake:sleep:0.2 " + LEGITIMATE)
    results: list[int] = []
    barrier = threading.Barrier(2)

    def submit() -> None:
        barrier.wait()
        results.append(post(ready_client, key, payload).status_code)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    assert sorted(results) == [200, 201]
    assert events_with(migration_engine, payload["event_id"]) == 1


# --- rejection before storage ------------------------------------------------------------------


def test_saturation_is_429_with_nothing_stored_and_a_retry_succeeds(
    ready_client: TestClient, key: str, clock: FakeClock, migration_engine: Engine
) -> None:
    payloads = [
        body(clock, text_value="fake:sleep:0.4 slow"),
        body(clock, text_value="fake:sleep:0.1 waits"),
        body(clock),
    ]
    responses: list[Response | None] = [None] * 3
    barrier = threading.Barrier(3)

    def submit(index: int) -> None:
        barrier.wait()
        time.sleep(0.05 * index)
        responses[index] = post(ready_client, key, payloads[index])

    threads = [threading.Thread(target=submit, args=(i,)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    statuses = [r.status_code for r in responses if r is not None]
    assert statuses == [201, 201, 429]
    rejected = responses[2]
    assert rejected is not None and rejected.json()["error"]["code"] == "CAPACITY_EXCEEDED"
    assert rejected.headers["Retry-After"] == "1"
    assert events_with(migration_engine, payloads[2]["event_id"]) == 0
    retry = post(ready_client, key, payloads[2])
    assert retry.status_code == 201 and retry.json()["data"]["analysis_status"] == "complete"


def test_a_starting_worker_is_503_with_nothing_stored(
    make_client, key: str, clock: FakeClock, migration_engine: Engine, tmp_path: Path
) -> None:
    supervisor = fake_supervisor(tmp_path / "hang.lock", mode="hang", start_timeout_s=30)
    _, client = make_client(supervisor)
    payload = body(clock)
    response = post(client, key, payload)
    assert (response.status_code, response.json()["error"]["code"]) == (
        503,
        "DEPENDENCY_UNAVAILABLE",
    )
    assert response.headers["Retry-After"] == "10"
    assert events_with(migration_engine, payload["event_id"]) == 0


def test_authentication_scope_validation_and_rate_limits_run_before_inference(
    ready_client: TestClient, key: str, clock: FakeClock, calls: list[str], make_key_other
) -> None:
    assert post(ready_client, None, body(clock)).status_code == 401
    assert post(ready_client, "kvk_" + "x" * 40, body(clock)).status_code == 401
    assert post(ready_client, key, body(clock, source="partner-z")).status_code == 403
    assert post(ready_client, key, {"event_id": "only"}).status_code == 422
    assert post(ready_client, key, body(clock, text_value="x" * 4097)).status_code == 422
    assert calls == []
    statuses = [post(ready_client, make_key_other, body(clock)).status_code for _ in range(31)]
    assert statuses[:30] == [201] * 30 and statuses[30] == 429
    assert len(calls) == 30, "the 31st submission was refused before reaching the worker"


@pytest.fixture
def make_key_other(app: FastAPI, operator_id: UUID) -> str:
    from datetime import timedelta

    return app.state.ingest_keys.create(
        actor_id=operator_id,
        name="second feed",
        source="simulator",
        lifetime=timedelta(days=90),
    ).plaintext


# --- attempted inference that fails: stored unavailable, never legitimate ----------------------


@pytest.mark.parametrize(
    ("directive", "reason"),
    [
        ("fake:sleep:5", "inference_timeout"),
        ("fake:crash", "worker_crashed"),
        ("fake:garbage", "invalid_model_output"),
        ("fake:nan", "invalid_model_output"),
        ("fake:wrong_id", "invalid_model_output"),
    ],
)
def test_failed_inference_is_stored_unavailable_and_replay_never_reruns(
    ready_client: TestClient,
    app: FastAPI,
    key: str,
    clock: FakeClock,
    calls: list[str],
    migration_engine: Engine,
    report: Path,
    directive: str,
    reason: str,
) -> None:
    first_pid = worker_pid(report)
    payload = body(clock, text_value=f"{directive} {LEGITIMATE}")
    response = post(ready_client, key, payload)
    assert response.status_code == 201
    receipt = response.json()["data"]
    assert receipt["analysis_status"] == "unavailable"
    assert receipt["warnings"] == ["SMS_CLASSIFIER_UNAVAILABLE"]
    row = stored(migration_engine, payload["event_id"])
    assert stage(row) == {"status": "unavailable", "reason": reason, "duration_ms": 0}
    assert row["sms_score"] is None and row["model_versions"] == {}
    assert "legitimate" not in json.dumps(row["signals"])
    assessment = assessment_of(migration_engine, row["id"])
    assert (assessment["tier"], assessment["analysis_status"]) == ("unknown", "unavailable")
    # The worker was replaced; a replay still returns the stored failure without re-running.
    assert wait_state(app.state.sms_worker, "ready") == "ready"
    assert worker_pid(report) != first_pid
    replay = post(ready_client, key, payload)
    assert replay.status_code == 200 and replay.json()["data"]["analysis_status"] == "unavailable"
    assert calls == ["call"]
    assert post(ready_client, key, body(clock)).json()["data"]["analysis_status"] == "complete"


@pytest.mark.parametrize(
    ("mode", "state", "reason"),
    [("crash", "circuit_open", "worker_unavailable"), ("fatal", "unverified", "model_unverified")],
)
def test_open_circuit_and_unverified_artifacts_store_unavailable(
    make_client,
    key: str,
    clock: FakeClock,
    migration_engine: Engine,
    tmp_path: Path,
    mode: str,
    state: str,
    reason: str,
) -> None:
    supervisor = fake_supervisor(tmp_path / f"{mode}.lock", mode=mode)
    _, client = make_client(supervisor)
    assert wait_state(supervisor, state) == state
    payload = body(clock)
    response = post(client, key, payload)
    assert response.status_code == 201
    assert response.json()["data"]["analysis_status"] == "unavailable"
    assert stage(stored(migration_engine, payload["event_id"]))["reason"] == reason


def test_missing_artifacts_configuration_is_unverified_not_a_crash(
    make_client, key: str, clock: FakeClock, migration_engine: Engine, tmp_path: Path
) -> None:
    app, client = make_client(
        sms_worker_enabled=True,
        sms_worker_python=Path(sys.executable),
        model_dir=tmp_path / "no-such-models",
        model_manifest_path=Path(__file__).resolve().parents[3]
        / "deployment"
        / "models"
        / "sms_classifier.horizon.v1.json",
    )
    assert app.state.sms_worker.status()["fatal_code"] == "model_dir_missing"
    payload = body(clock)
    assert post(client, key, payload).json()["data"]["analysis_status"] == "unavailable"
    assert stage(stored(migration_engine, payload["event_id"]))["reason"] == "model_unverified"


# --- dependency outages ------------------------------------------------------------------------


def test_database_failure_after_inference_stores_nothing_and_a_retry_reanalyzes(
    ready_client: TestClient,
    key: str,
    clock: FakeClock,
    calls: list[str],
    migration_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = body(clock)

    def down(*_args: Any, **_kwargs: Any) -> None:
        raise OperationalError("INSERT", {}, Exception("connection lost"))

    monkeypatch.setattr(repo, "insert_event_if_absent", down)
    response = post(ready_client, key, payload)
    assert (response.status_code, response.json()["error"]["code"]) == (
        503,
        "DEPENDENCY_UNAVAILABLE",
    )
    assert events_with(migration_engine, payload["event_id"]) == 0
    monkeypatch.undo()
    assert post(ready_client, key, payload).status_code == 201
    assert calls == ["call", "call"], "nothing was stored, so the retry is analyzed afresh"


def test_unreachable_database_or_redis_fail_closed_before_inference(
    make_client, key: str, clock: FakeClock, tmp_path: Path
) -> None:
    for name, override in [
        ("db", {"database_url": "postgresql+psycopg://kavach_app:unused@127.0.0.1:1/kavach_test"}),
        ("redis", {"redis_url": "redis://:unused@127.0.0.1:1/15"}),
    ]:
        supervisor = fake_supervisor(tmp_path / f"{name}.lock")
        _, client = make_client(supervisor, **override)
        assert wait_state(supervisor, "ready") == "ready"
        seen = count_calls(supervisor)
        response = post(client, key, body(clock))
        assert (response.status_code, response.json()["error"]["code"]) == (
            503,
            "DEPENDENCY_UNAVAILABLE",
        )
        assert seen == [], f"{name} outage must refuse before any inference"


def test_redis_index_failure_after_commit_keeps_the_committed_evidence(
    ready_client: TestClient, app: FastAPI, key: str, clock: FakeClock, migration_engine: Engine
) -> None:
    app.state.ingestion.candidates = CandidateIndex(
        Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.5), "test"
    )
    payload = body(clock)
    response = post(ready_client, key, payload)
    assert response.status_code == 201 and response.json()["data"]["analysis_status"] == "complete"
    assert stage(stored(migration_engine, payload["event_id"]))["status"] == "complete"


# --- one model copy across API processes ---------------------------------------------------------

SECOND_PROCESS = """
import sys, time
sys.path.insert(0, {tests!r})
from fakes.support import fake_supervisor
supervisor = fake_supervisor(__import__("pathlib").Path({lock!r}))
supervisor.start()
time.sleep(0.5)
print(supervisor.state, supervisor.classify("FICTIONAL DEMO: hi", time.monotonic() + 10).reason)
supervisor.close()
"""


def test_a_second_api_process_cannot_load_a_second_model_copy(
    ready_client: TestClient, app: FastAPI, lock_path: Path
) -> None:
    tests_dir = str(Path(__file__).resolve().parents[1])
    code = SECOND_PROCESS.format(tests=tests_dir, lock=str(lock_path))
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=True
    )
    assert done.stdout.split() == ["lock_held", "worker_unavailable"]
    assert app.state.sms_worker.state == "ready", "the first process keeps its worker"


# --- readiness -------------------------------------------------------------------------------


def test_model_readiness_requires_a_dashboard_session_and_never_claims_accuracy(
    ready_client: TestClient, key: str, make_user, make_client, tmp_path: Path
) -> None:
    assert ready_client.get("/api/v1/system/models").status_code == 401
    bearer = ready_client.get("/api/v1/system/models", headers={"Authorization": f"Bearer {key}"})
    assert bearer.status_code == 401
    viewer = make_user(role="viewer")
    assert login(ready_client, viewer.username, viewer.password).status_code == 200
    data = ready_client.get("/api/v1/system/models").json()["data"]["sms_classifier"]
    assert data["state"] == "ready" and data["detail"] == "ready"
    assert data["model_version"].startswith("horizon-phishing-scam-base@")
    assert data["score_semantics"] == "uncalibrated_softmax"
    assert data["validated_on_kavach_data"] is False
    assert set(data) == {
        "state",
        "detail",
        "reason",
        "model_version",
        "score_semantics",
        "validated_on_kavach_data",
    }

    states = []
    for supervisor in (
        None,
        fake_supervisor(tmp_path / "s.lock", mode="hang"),
        fake_supervisor(tmp_path / "f.lock", mode="fatal"),
    ):
        _, client = make_client(supervisor)
        if supervisor is not None and "fatal" in supervisor.config.command:
            wait_state(supervisor, "unverified")
        login(client, viewer.username, viewer.password)
        states.append(client.get("/api/v1/system/models").json()["data"]["sms_classifier"]["state"])
    assert states == ["disabled", "starting", "unavailable"]


# --- privacy -----------------------------------------------------------------------------------


def all_database_text(engine: Engine) -> str:
    with engine.connect() as connection:
        tables = (
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )
            )
            .scalars()
            .all()
        )
        return "\n".join(
            row
            for table in tables
            for row in connection.execute(
                text(f'SELECT row_to_json(t)::text FROM "{table}" t')  # names from the catalog
            ).scalars()
        )


def all_redis_text(client: Redis) -> str:
    parts = []
    for name in client.scan_iter("*"):
        parts.append(str(name))
        kind = client.type(name)
        kind = kind.decode() if isinstance(kind, bytes) else kind
        if kind == "string":
            parts.append(str(client.get(name)))
        elif kind == "zset":
            parts.append(str(client.zrange(name, 0, -1, withscores=True)))
        elif kind == "hash":
            parts.append(str(client.hgetall(name)))
        elif kind == "set":
            parts.append(str(client.smembers(name)))
        elif kind == "list":
            parts.append(str(client.lrange(name, 0, -1)))
    return "\n".join(parts)


def test_no_text_or_sender_reaches_postgres_redis_logs_audit_or_the_worker_environment(
    ready_client: TestClient,
    key: str,
    clock: FakeClock,
    migration_engine: Engine,
    redis_client: Redis,
    caplog: pytest.LogCaptureFixture,
    report: Path,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.DEBUG)
    texts = [
        PRIVATE,
        f"fake:stderr {PRIVATE}",
        f"fake:stdout {PRIVATE}",
        f"fake:crash {PRIVATE}",
        f"fake:sleep:5 {PRIVATE}",
        f"fake:garbage {PRIVATE}",
    ]
    for value in texts:
        wait_state(app.state.sms_worker, "ready")
        payload = body(clock, text_value=value, sender_id=SENDER)
        assert post(ready_client, key, payload).status_code == 201
        assert post(ready_client, key, payload).status_code == 200
    haystacks = {
        "postgres": all_database_text(migration_engine),
        "redis": all_redis_text(redis_client),
        "logs": caplog.text,
    }
    for where, haystack in haystacks.items():
        assert "INGEST-CANARY" not in haystack, f"text reached {where}"
        assert SENDER not in haystack, f"sender ID reached {where}"
    with migration_engine.connect() as connection:
        audits = connection.execute(select(AuditRecord)).mappings().all()
    assert all("INGEST-CANARY" not in json.dumps(dict(a), default=str) for a in audits)
    env = json.loads(report.read_text())["env"]
    for secret in (
        "DATABASE_URL",
        "REDIS_URL",
        "PAYLOAD_HMAC_KEYS",
        "SUBSCRIBER_HMAC_KEYS",
        "AUDIT_HMAC_KEYS",
        "RATE_LIMIT_HMAC_KEY",
        "TEST_DATABASE_URL",
    ):
        assert secret not in env
    assert all(
        os.environ.get(name, "\0") not in json.dumps(env)
        for name in ("TEST_DATABASE_URL", "TEST_REDIS_URL")
    )
    assert "INGEST-CANARY" not in " ".join(json.loads(report.read_text())["argv"])


# --- shutdown ----------------------------------------------------------------------------------


def test_shutdown_stops_the_worker_and_releases_the_model_copy_lock(
    migrated_schema: None, keys: tuple[str, str], clock: FakeClock, tmp_path: Path
) -> None:
    lock, report_path = tmp_path / "shutdown.lock", tmp_path / "shutdown.json"
    supervisor = SmsWorkerSupervisor(fake_worker_config(lock, report=report_path))
    app = create_app(auth_settings(*keys), clock=clock, sms_worker=supervisor)
    with TestClient(app, base_url=ORIGIN):
        assert wait_state(supervisor, "ready") == "ready"
        pid = worker_pid(report_path)
    assert supervisor.state == "closed"
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        pytest.fail("the worker outlived the API shutdown")
    again = SmsWorkerSupervisor(fake_worker_config(lock))
    again.start()
    assert again.state != "lock_held"
    again.close()
