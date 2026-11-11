"""M3.3 against real PostgreSQL and Redis: the whole catalog through the real endpoints, then
the stored receipts, incidents and Redis candidate state checked against the catalog's
expectations; determinism, key scope, revoked keys, rate limits, outages, loopback HTTP,
privacy, and the admin-only catalog endpoint."""

import io
import json
import logging
import socket
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

import kavach.auth.throttle as throttle
from kavach.api.schemas.events import SMSEvent
from kavach.auth.ingest_keys import IngestKeyService
from kavach.correlation.candidates import CandidateIndex
from kavach.db.models import Assessment, AuditRecord, Event, Incident, IncidentEvent
from kavach.main import create_app
from kavach.services.ingestion import canonical_payload
from kavach.simulator import cli
from kavach.simulator.catalog import load_catalog
from kavach.simulator.runner import (
    HttpResult,
    Pacer,
    PlannedStep,
    Runner,
    RunReport,
    plan_scenario,
)

from .auth_support import ORIGIN, Account, FakeClock, auth_settings, login

pytestmark = pytest.mark.integration

ALL = [scenario.id for scenario in load_catalog().scenarios]


@pytest.fixture(autouse=True)
def clean_candidates(redis_client: Redis) -> Iterator[None]:
    def clear() -> None:
        for key in redis_client.scan_iter("kavach:test:candidate:*"):
            redis_client.delete(key)

    clear()
    yield
    clear()


@pytest.fixture
def make_key(app: FastAPI, operator_id: UUID) -> Callable[..., Any]:
    keys: IngestKeyService = app.state.ingest_keys

    def make(source: str = "simulator") -> Any:
        return keys.create(actor_id=operator_id, name=f"simulator {source}", source=source)

    return make


@pytest.fixture
def key(make_key: Callable[..., Any]) -> str:
    return make_key().plaintext


class InProcessTransport:
    """Test-only adapter: the runner's HTTP requests served in-process by the real app."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.submissions = 0

    def request(
        self, method: str, path: str, headers: Mapping[str, str], body: bytes | None
    ) -> HttpResult:
        if method == "POST":
            self.submissions += 1
        response = self.client.request(method, path, headers=dict(headers), content=body)
        headers_out = {name.lower(): value for name, value in response.headers.items()}
        return HttpResult(response.status_code, headers_out, response.content)


def no_wait_pacer() -> Pacer:
    return Pacer(30, sleep=lambda seconds: None)


def run(
    client: TestClient,
    key: str,
    clock: FakeClock,
    scenario_ids: list[str],
    *,
    run_id: str,
    seed: int = 0,
    pacer: Pacer | None = None,
) -> RunReport:
    runner = Runner(
        load_catalog(), InProcessTransport(client), key, clock=clock,
        pacer=pacer or no_wait_pacer(), seed=seed, run_id=run_id,
    )  # fmt: skip
    return runner.run(scenario_ids)


def plans(clock: FakeClock, run_id: str, seed: int = 0) -> dict[str, list[PlannedStep]]:
    catalog = load_catalog()
    return {
        s.id: plan_scenario(s, catalog.source, seed=seed, run_id=run_id, anchor=clock.now)
        for s in catalog.scenarios
    }


def rows_for(engine: Engine, run_id: str) -> list[Any]:
    with engine.connect() as db:
        return list(
            db.execute(
                select(Event.source, Event.external_event_id, Event.id, Event.analysis_status)
                .where(Event.external_event_id.like(f"sim-{run_id}-%"))
            )
        )  # fmt: skip


# --- the whole catalog against real services --------------------------------------------------


def test_every_scenario_meets_its_catalog_expectations(
    client: TestClient,
    app: FastAPI,
    key: str,
    clock: FakeClock,
    runtime_engine: Engine,
    redis_client: Redis,
) -> None:
    report = run(client, key, clock, ALL, run_id="full1")
    assert report.passed, "\n".join(map(str, report.scenarios))
    assert report.submissions == 20

    catalog = load_catalog()
    planned = plans(clock, "full1")
    receipts = {
        (s.scenario_id, step.step): step.receipt_id for s in report.scenarios for step in s.steps
    }
    ingestion = app.state.ingestion
    index: CandidateIndex = ingestion.candidates
    stored_ids: set[UUID] = set()

    with Session(runtime_engine) as db:
        for scenario in catalog.scenarios:
            steps = {p.step: p for p in planned[scenario.id]}
            for step in scenario.stored_steps():
                plan = steps[step.step]
                event = db.execute(
                    select(Event).where(
                        Event.source == "simulator",
                        Event.external_event_id == plan.external_event_id,
                    )
                ).scalar_one()
                assert str(event.id) == receipts[(scenario.id, step.step)]
                stored_ids.add(event.id)
                # No model ran: every stage unavailable, every score null, tier unknown.
                assert event.analysis_status == "unavailable"
                assert {s["status"] for s in event.signals["stages"].values()} == {"unavailable"}
                assert (event.sms_score, event.voice_intent_score, event.synthesis_score) == (
                    None, None, None,
                )  # fmt: skip
                incident = db.execute(
                    select(Incident)
                    .join(IncidentEvent, IncidentEvent.incident_id == Incident.id)
                    .where(IncidentEvent.event_id == event.id)
                ).scalar_one()
                assert incident.kind == "standalone"
                assessment = db.execute(
                    select(Assessment).where(Assessment.incident_id == incident.id)
                ).scalar_one()
                assert assessment.tier == "unknown"
                assert (assessment.base_score, assessment.fusion_score, assessment.final_score) == (
                    None, None, None,
                )  # fmt: skip
                # Redis candidate expectation (provisional D05).
                digest = ingestion.subscriber_digests.digest(
                    plan.payload["subscriber_token"].encode()
                )
                member = f"{plan.kind}:{event.id}"
                in_index = redis_client.zscore(index.key("v1", digest), member) is not None
                assert in_index is step.expect.indexed, (scenario.id, step.step)
            for pair in scenario.candidate_pairs:
                first, second = (steps[s] for s in pair.between)
                digest = ingestion.subscriber_digests.digest(
                    first.payload["subscriber_token"].encode()
                )
                near = index.near("v1", digest, clock.now + timedelta(seconds=first.offset_seconds))
                linked = str(receipts[(scenario.id, second.step)]) in {
                    str(c.event_id) for c in near
                }
                assert linked is pair.linked, (scenario.id, pair.between)

        # Forged source and unapproved audio stored nothing; the conflicting reuse changed
        # nothing; candidate proximity created no pair incident.
        assert {row.external_event_id for row in rows_for(runtime_engine, "full1")} == {
            p.external_event_id
            for scenario in catalog.scenarios
            for p in planned[scenario.id]
            if p.expect.status == 201
        }
        assert all(row.source == "simulator" for row in rows_for(runtime_engine, "full1"))
        pair_incidents = db.execute(
            select(Incident.id)
            .join(IncidentEvent, IncidentEvent.incident_id == Incident.id)
            .where(IncidentEvent.event_id.in_(stored_ids), Incident.kind == "pair")
        ).all()
        assert pair_incidents == []
        original = planned["S09"][0]
        digest, version = db.execute(
            select(Event.payload_digest, Event.payload_key_version).where(
                Event.external_event_id == original.external_event_id
            )
        ).one()
        event = SMSEvent.model_validate(original.payload, context={"now": clock.now})
        assert ingestion.payload_digests.matches(canonical_payload(event), digest, version)
        audits = db.execute(
            select(AuditRecord.action).where(AuditRecord.resource_id.in_(stored_ids))
        ).scalars()
        assert sorted(audits) == ["event.ingest"] * len(stored_ids)


def test_nothing_sensitive_is_stored_logged_or_printed(
    client: TestClient,
    key: str,
    clock: FakeClock,
    runtime_engine: Engine,
    redis_client: Redis,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        ["run", "--all", "--run-id", "priv1"],
        out=out,
        err=err,
        environ={cli.KEY_VARIABLE: key},
        clock=clock,
        transport=InProcessTransport(client),
        pacer=no_wait_pacer(),
    )
    assert code == 0, out.getvalue()
    secrets = {key}
    for steps in plans(clock, "priv1").values():
        for step in steps:
            secrets.add(step.payload["subscriber_token"])
            for field in ("text", "sender_id"):
                if step.payload.get(field):
                    secrets.add(step.payload[field])
            if step.truth:
                secrets.add(step.truth)
    redis_dump = []
    for redis_key in redis_client.scan_iter("kavach:test:*"):
        redis_dump.append(redis_key.decode())
        if redis_client.type(redis_key) == b"zset":
            redis_dump.extend(m.decode() for m in redis_client.zrange(redis_key, 0, -1))
    with runtime_engine.connect() as db:
        stored = [
            json.dumps(row, default=str)
            for row in db.execute(
                select(Event.external_event_id, Event.signals, Event.model_versions)
            ).all()
        ]
        stored += [
            json.dumps(e, default=str) for e in db.execute(select(Assessment.evidence)).scalars()
        ]
    haystacks = {
        "runner output": out.getvalue() + err.getvalue(),
        "logs": "\n".join(record.getMessage() for record in caplog.records),
        "redis": "\n".join(redis_dump),
        "database": "\n".join(stored),
    }
    for where, haystack in haystacks.items():
        for secret in secrets:
            assert secret not in haystack, where


# --- determinism, scope and credentials ---------------------------------------------------------


def test_the_same_seed_and_run_id_replays_identically(
    client: TestClient, key: str, clock: FakeClock
) -> None:
    first = run(client, key, clock, ["S05", "S07"], run_id="det1", seed=11)
    again = run(client, key, clock, ["S05", "S07"], run_id="det1", seed=11)
    assert first.passed and not again.passed  # a repeat is a replay, not new evidence
    for before, after in zip(first.scenarios, again.scenarios, strict=True):
        for a, b in zip(before.steps, after.steps, strict=True):
            assert (b.status, b.replayed, b.receipt_id) == (200, True, a.receipt_id)
    fresh = run(client, key, clock, ["S05"], run_id="det2", seed=11)
    assert fresh.passed
    assert {s.receipt_id for s in fresh.scenarios[0].steps}.isdisjoint(
        {s.receipt_id for s in first.scenarios[0].steps}
    )


def test_a_key_for_another_source_stops_the_run_and_stores_nothing(
    client: TestClient, make_key: Callable[..., Any], clock: FakeClock, runtime_engine: Engine
) -> None:
    other = make_key("partner-feed").plaintext
    report = run(client, other, clock, ALL, run_id="scope1")
    assert report.aborted == "the API key is not scoped to the catalog source"
    assert report.submissions == 1
    assert report.scenarios[0].steps[0].status == 403
    assert rows_for(runtime_engine, "scope1") == []


def test_a_revoked_key_is_rejected_once_and_the_run_stops(
    app: FastAPI,
    client: TestClient,
    make_key: Callable[..., Any],
    operator_id: UUID,
    clock: FakeClock,
    runtime_engine: Engine,
    redis_client: Redis,
) -> None:
    issued = make_key()
    app.state.ingest_keys.revoke(actor_id=operator_id, key_id=issued.key_id)
    report = run(client, issued.plaintext, clock, ALL, run_id="revoked1")
    assert report.aborted == "the API key was rejected (expired, revoked or unknown)"
    assert report.submissions == 1 and rows_for(runtime_engine, "revoked1") == []
    # Exactly one rejected attempt was counted against the invalid-key throttle.
    (bearer_key,) = list(redis_client.scan_iter("kavach:test:ratelimit:bearer:*"))
    assert int(redis_client.get(bearer_key) or 0) == 1


def test_the_runner_honors_the_servers_rate_limit(
    client: TestClient, key: str, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A tiny server-side window so the real 429 path is exercised in seconds.
    monkeypatch.setattr(throttle, "SUBMISSIONS_PER_KEY", 3)
    monkeypatch.setattr(throttle, "SUBMISSION_WINDOW_SECONDS", 2)
    report = run(client, key, clock, ["S10", "S05"], run_id="rate1", pacer=Pacer(30))
    assert report.passed, report
    retries = sum(step.rate_limit_retries for s in report.scenarios for step in s.steps)
    assert retries >= 1
    assert report.submissions == 6 + retries


# --- outages -------------------------------------------------------------------------------


def test_postgresql_outage_stops_the_run_with_nothing_stored(
    keys: tuple[str, str], clock: FakeClock, key: str, runtime_engine: Engine, clean_throttle: None
) -> None:
    dead_db = "postgresql+psycopg://kavach_app:unused@127.0.0.1:1/kavach_test"
    app = create_app(auth_settings(*keys, database_url=dead_db), clock=clock)
    with TestClient(app, base_url=ORIGIN) as client:
        report = run(client, key, clock, ALL, run_id="pgdown1")
    assert report.aborted == "server returned 503" and report.submissions == 1
    assert report.scenarios[0].steps[0].code == "DEPENDENCY_UNAVAILABLE"
    assert rows_for(runtime_engine, "pgdown1") == []


def test_redis_outage_stops_the_run_with_nothing_stored(
    keys: tuple[str, str], clock: FakeClock, key: str, runtime_engine: Engine
) -> None:
    app = create_app(auth_settings(*keys, redis_url="redis://:unused@127.0.0.1:1/15"), clock=clock)
    with TestClient(app, base_url=ORIGIN) as client:
        report = run(client, key, clock, ALL, run_id="rdown1")
    assert report.aborted == "server returned 503" and report.submissions == 1
    assert rows_for(runtime_engine, "rdown1") == []


# --- real loopback HTTP ------------------------------------------------------------------------


@pytest.fixture
def served(app: FastAPI) -> Iterator[str]:
    """The same app served by Uvicorn on an ephemeral loopback port."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    server.should_exit = True
    thread.join(10)
    sock.close()


def test_the_cli_runs_over_real_loopback_http(served: str, key: str, clock: FakeClock) -> None:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        ["run", "--scenario", "S05", "--scenario", "S08", "--scenario", "S09",
         "--run-id", "http1", "--base-url", served, "--key-stdin"],
        stdin=io.StringIO(key + "\n"),
        out=out,
        err=err,
        clock=clock,
    )  # fmt: skip
    assert code == 0, out.getvalue() + err.getvalue()
    assert "Summary: 3/3 scenarios passed, 6 submissions" in out.getvalue()
    assert key not in out.getvalue() + err.getvalue()


# --- admin catalog endpoint ----------------------------------------------------------------------


def test_admins_read_the_catalog(client: TestClient, make_user: Callable[..., Account]) -> None:
    admin = make_user("admin")
    assert login(client, admin.username, admin.password).status_code == 200
    response = client.get("/api/v1/simulator/scenarios")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()["data"]
    assert data["samples"] == [] and data["synthetic"] is True
    expected = load_catalog().model_dump(mode="json")
    assert {k: v for k, v in data.items() if k != "samples"} == expected


@pytest.mark.parametrize("role", ["viewer", "analyst"])
def test_other_roles_cannot_read_the_catalog(
    client: TestClient, make_user: Callable[..., Account], role: str
) -> None:
    user = make_user(role)
    login(client, user.username, user.password)
    response = client.get("/api/v1/simulator/scenarios")
    assert (response.status_code, response.json()["error"]["code"]) == (403, "FORBIDDEN")


def test_machine_keys_and_anonymous_callers_cannot_read_the_catalog(
    client: TestClient, key: str, make_user: Callable[..., Account]
) -> None:
    bearer = {"Authorization": f"Bearer {key}"}
    for headers in ({}, bearer):
        response = client.get("/api/v1/simulator/scenarios", headers=headers)
        assert response.status_code == 401
    admin = make_user("admin")
    login(client, admin.username, admin.password)
    mixed = client.get("/api/v1/simulator/scenarios", headers=bearer)
    assert (mixed.status_code, mixed.json()["error"]["code"]) == (401, "MIXED_CREDENTIALS")


def test_a_deactivated_admin_loses_catalog_access(
    client: TestClient, make_user: Callable[..., Account], accounts: Any, operator_id: UUID
) -> None:
    admin = make_user("admin")
    login(client, admin.username, admin.password)
    assert client.get("/api/v1/simulator/scenarios").status_code == 200
    accounts.deactivate_user(actor_id=operator_id, username=admin.username)
    assert client.get("/api/v1/simulator/scenarios").status_code == 401
