"""M3.4 acceptance regressions against real PostgreSQL and Redis: late replays and the
candidate horizon, ambiguous commits, forwarded-header spoofing against the invalid-key
throttle, payload and subscriber key rotation, and pathological JSON."""

import http.client
import json
import logging
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from redis import Redis
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from kavach.auth.ingest_keys import IngestKeyService
from kavach.auth.throttle import BLOCKED_IP_LOOKUPS
from kavach.db.models import Event
from kavach.main import create_app

from .auth_support import ORIGIN, TEST_PAYLOAD_KEYS, TEST_SUBSCRIBER_KEYS, FakeClock, auth_settings

pytestmark = pytest.mark.integration

TOKEN = "sub_acceptance_a"


@pytest.fixture(autouse=True)
def clean_candidates(redis_client: Redis) -> Iterator[None]:
    def clear() -> None:
        for key in redis_client.scan_iter("kavach:test:candidate:*"):
            redis_client.delete(key)

    clear()
    yield
    clear()


@pytest.fixture
def key(app: FastAPI, operator_id: UUID) -> str:
    keys: IngestKeyService = app.state.ingest_keys
    return keys.create(actor_id=operator_id, name="acceptance", source="simulator").plaintext


def sms(clock: FakeClock, **override: Any) -> dict[str, Any]:
    return {
        "event_id": f"acc-{uuid4().hex[:12]}",
        "subscriber_token": TOKEN,
        "timestamp": clock.now.isoformat(),
        "source": "simulator",
        "text": "Synthetic acceptance message",
    } | override


def post(client: TestClient, key: str, body: Any, **headers: str) -> Response:
    return client.post(
        "/api/v1/events/sms", json=body, headers={"Authorization": f"Bearer {key}"} | headers
    )


def stored(engine: Engine, external_event_id: str) -> int:
    with engine.connect() as db:
        return db.execute(
            select(func.count()).select_from(Event).where(
                Event.external_event_id == external_event_id
            )
        ).scalar_one()  # fmt: skip


def candidate_members(app: FastAPI, redis: Redis, token: str = TOKEN, version: str = "v1") -> set:
    service = app.state.ingestion
    digest = service.subscriber_digests.digest(token.encode(), version)
    return {m.decode() for m in redis.zrange(service.candidates.key(version, digest), 0, -1)}


# --- candidate horizon on replay -----------------------------------------------------------


def test_a_late_identical_replay_does_not_resurrect_an_expired_candidate(
    client: TestClient, app: FastAPI, key: str, clock: FakeClock, redis_client: Redis
) -> None:
    body = sms(clock)
    receipt = post(client, key, body).json()["data"]
    member = f"sms:{receipt['event_id']}"
    assert candidate_members(app, redis_client) == {member}
    redis_client.flushdb()  # the index expired (or Redis restarted) since then
    clock.advance(minutes=45)
    replay = post(client, key, body)
    assert (replay.status_code, replay.json()["data"]["replayed"]) == (200, True)
    # 45 minutes later the event can never match anything new, so it must stay out.
    assert candidate_members(app, redis_client) == set()


def test_a_prompt_identical_replay_still_repairs_a_missing_candidate(
    client: TestClient, app: FastAPI, key: str, clock: FakeClock, redis_client: Redis
) -> None:
    body = sms(clock)
    receipt = post(client, key, body).json()["data"]
    redis_client.flushdb()
    clock.advance(minutes=5)
    assert post(client, key, body).status_code == 200
    assert candidate_members(app, redis_client) == {f"sms:{receipt['event_id']}"}


# --- ambiguous commit -----------------------------------------------------------------------


class LostCommitAcknowledgement:
    """Test-only wrapper: the write transaction commits, then the connection 'drops'."""

    def __init__(self, sessions: Any) -> None:
        self.sessions = sessions
        self.calls = 0

    @contextmanager
    def begin(self) -> Iterator[Session]:
        self.calls += 1
        with self.sessions.begin() as db:
            yield db
        if self.calls == 2:  # the second transaction of `ingest` is the write
            raise OperationalError("COMMIT", {}, ConnectionError("connection lost"))


def test_an_ambiguous_commit_is_resolved_by_retrying_the_same_event_id(
    client: TestClient, app: FastAPI, key: str, clock: FakeClock, runtime_engine: Engine
) -> None:
    service = app.state.ingestion
    real = service.sessions
    service.sessions = LostCommitAcknowledgement(real)
    body = sms(clock)
    try:
        lost = post(client, key, body)
    finally:
        service.sessions = real
    # The client cannot know the outcome; the event was in fact committed.
    assert (lost.status_code, lost.json()["error"]["code"]) == (503, "DEPENDENCY_UNAVAILABLE")
    assert stored(runtime_engine, body["event_id"]) == 1
    retry = post(client, key, body)
    assert (retry.status_code, retry.json()["data"]["replayed"]) == (200, True)
    assert stored(runtime_engine, body["event_id"]) == 1


# --- invalid-key throttle against spoofed forwarding headers ---------------------------------


def test_forwarded_headers_cannot_evade_the_invalid_key_throttle(
    client: TestClient, key: str
) -> None:
    bad = {"Authorization": "Bearer kvk_" + "X" * 43}
    statuses = [
        client.post(
            "/api/v1/events/sms",
            json={},
            headers=bad | {"X-Forwarded-For": f"198.51.100.{n}", "X-Real-IP": f"203.0.113.{n}"},
        ).status_code
        for n in range(30 + BLOCKED_IP_LOOKUPS)
    ]
    # 30 rejections fill the one per-peer bucket; then only the small lookup budget remains.
    assert statuses == [401] * (30 + BLOCKED_IP_LOOKUPS)
    spoofed = client.post(
        "/api/v1/events/sms", json={}, headers=bad | {"X-Forwarded-For": "192.0.2.77"}
    )
    assert spoofed.status_code == 429


# --- key rotation ---------------------------------------------------------------------------


def app_with_keys(keys: tuple[str, str], clock: FakeClock, **override: str) -> FastAPI:
    return create_app(auth_settings(*keys, **override), clock=clock)


def test_payload_key_rotation_keeps_replays_and_conflicts_correct(
    keys: tuple[str, str], key: str, clock: FakeClock, runtime_engine: Engine
) -> None:
    body = sms(clock)
    with TestClient(app_with_keys(keys, clock), base_url=ORIGIN) as client:
        assert post(client, key, body).status_code == 201
    v1 = json.loads(TEST_PAYLOAD_KEYS)["v1"]
    rotated = json.dumps({"v1": v1, "v2": "test-only-payload-key-v2-0000000000000000"})
    with TestClient(
        app_with_keys(keys, clock, payload_hmac_keys=rotated, payload_hmac_active_version="v2"),
        base_url=ORIGIN,
    ) as client:
        assert post(client, key, body).status_code == 200
        assert post(client, key, body | {"text": "Changed"}).status_code == 409
        new = sms(clock)
        assert post(client, key, new).status_code == 201
    with runtime_engine.connect() as db:
        versions = dict(
            db.execute(
                select(Event.external_event_id, Event.payload_key_version).where(
                    Event.external_event_id.in_([body["event_id"], new["event_id"]])
                )
            ).all()
        )
    assert versions == {body["event_id"]: "v1", new["event_id"]: "v2"}


def test_a_retired_payload_key_that_is_removed_fails_safely_and_is_reported(
    keys: tuple[str, str],
    key: str,
    clock: FakeClock,
    runtime_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = sms(clock)
    with TestClient(app_with_keys(keys, clock), base_url=ORIGIN) as client:
        assert post(client, key, body).status_code == 201
    only_v2 = json.dumps({"v2": "test-only-payload-key-v2-0000000000000000"})
    caplog.set_level(logging.WARNING, logger="kavach.operations")
    with TestClient(
        app_with_keys(keys, clock, payload_hmac_keys=only_v2, payload_hmac_active_version="v2"),
        base_url=ORIGIN,
        raise_server_exceptions=False,
    ) as client:
        response = post(client, key, body)
    # Neither a replay nor a conflict can be decided without the stored key version.
    assert (response.status_code, response.json()["error"]["code"]) == (500, "INTERNAL_ERROR")
    assert stored(runtime_engine, body["event_id"]) == 1
    assert "event=ingest.payload_key_missing" in caplog.text


def test_subscriber_key_rotation_starts_a_separate_candidate_set(
    keys: tuple[str, str], key: str, clock: FakeClock, redis_client: Redis
) -> None:
    """Documents a limitation for M6: pseudonyms differ per key version, so candidates
    indexed before a subscriber-key rotation are not found under the new version."""
    v1 = json.loads(TEST_SUBSCRIBER_KEYS)["v1"]
    rotated = json.dumps({"v1": v1, "v2": "test-only-subscriber-key-v2-00000000000000"})
    before = app_with_keys(keys, clock)
    after = app_with_keys(
        keys, clock, subscriber_hmac_keys=rotated, subscriber_hmac_active_version="v2"
    )
    with TestClient(before, base_url=ORIGIN) as client:
        first = post(client, key, sms(clock)).json()["data"]["event_id"]
    with TestClient(after, base_url=ORIGIN) as client:
        second = post(client, key, sms(clock)).json()["data"]["event_id"]
    assert candidate_members(after, redis_client, version="v1") == {f"sms:{first}"}
    assert candidate_members(after, redis_client, version="v2") == {f"sms:{second}"}


# --- pathological JSON ----------------------------------------------------------------------


@pytest.mark.parametrize("body", ["[" * 16000 + "]" * 16000, "[" * 30000])
def test_deeply_nested_json_is_a_validation_error_not_a_crash(
    client: TestClient, key: str, body: str
) -> None:
    response = client.post(
        "/api/v1/events/sms",
        content=body.encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    assert (response.status_code, response.json()["error"]["code"]) == (422, "VALIDATION_ERROR")


# --- the real server's proxy-header handling ------------------------------------------------


@contextmanager
def real_server(app: FastAPI, **config: Any) -> Iterator[int]:
    """`app` served by Uvicorn on an ephemeral loopback port with the given settings."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", **config))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    try:
        yield sock.getsockname()[1]
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()


def spoofed_invalid_attempts(port: int, attempts: int) -> list[int]:
    statuses = []
    for n in range(attempts):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request(
            "GET",
            f"/api/v1/events/{uuid4()}",
            headers={"Authorization": "Bearer kvk_" + "W" * 43, "X-Forwarded-For": f"192.0.2.{n}"},
        )
        statuses.append(connection.getresponse().status)
        connection.close()
    return statuses


def test_the_documented_launch_ignores_forwarded_headers(app: FastAPI) -> None:
    """README launches Uvicorn with --no-proxy-headers: the peer address is the throttle key."""
    with real_server(app, proxy_headers=False) as port:
        attempts = 30 + BLOCKED_IP_LOOKUPS
        assert spoofed_invalid_attempts(port, attempts + 1) == [401] * attempts + [429]


def test_uvicorns_default_trusts_loopback_forwarded_headers(app: FastAPI) -> None:
    """Why the flag is required: by default Uvicorn trusts X-Forwarded-For from 127.0.0.1/::1,
    so any local process could rotate its apparent IP past the per-IP ceilings."""
    with real_server(app) as port:
        attempts = 30 + BLOCKED_IP_LOOKUPS + 1
        assert spoofed_invalid_attempts(port, attempts) == [401] * attempts
