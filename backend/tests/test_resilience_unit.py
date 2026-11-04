"""Service-free M3.2 checks: D05 timing rules, Redis key privacy, and fail-closed behavior when
Redis refuses connections or never answers."""

import json
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from redis import Redis

from kavach.auth.throttle import BearerAttemptThrottle, SubmissionQuota, blocked_for
from kavach.cli import build_parser
from kavach.core.config import Settings
from kavach.correlation.candidates import (
    ALLOWED_LATENESS,
    CANDIDATE_HORIZON,
    CORRELATION_WINDOW,
    MAX_CANDIDATES_PER_SUBSCRIBER,
    CandidateIndex,
    is_indexable,
    is_late,
)
from kavach.main import create_app

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
ORIGIN = "https://kavach.test"


def test_d05_constants() -> None:
    assert CORRELATION_WINDOW == timedelta(minutes=30)
    assert ALLOWED_LATENESS == timedelta(minutes=10)
    assert CANDIDATE_HORIZON == timedelta(minutes=40)
    assert MAX_CANDIDATES_PER_SUBSCRIBER == 30 * 40


def test_lateness_boundary() -> None:
    assert not is_late(NOW - timedelta(minutes=10), NOW)
    assert is_late(NOW - timedelta(minutes=10, microseconds=1), NOW)
    assert not is_late(NOW + timedelta(seconds=60), NOW)


def test_indexing_horizon_boundary() -> None:
    assert is_indexable(NOW - timedelta(minutes=40), NOW)
    assert not is_indexable(NOW - timedelta(minutes=40, microseconds=1), NOW)


def test_redis_keys_reveal_no_identifiers() -> None:
    redis = Redis(host="127.0.0.1", port=1)
    bearer = BearerAttemptThrottle(redis, b"k" * 32, "test")._redis_key("203.0.113.9")
    quota = SubmissionQuota(redis, b"k" * 32, "test")._redis_key("6f1c0d4e-key-id")
    candidate = CandidateIndex(redis, "test").key("v1", b"\x01" * 32)
    assert bearer.startswith("kavach:test:ratelimit:bearer:ip:") and "203.0.113" not in bearer
    assert quota.startswith("kavach:test:ratelimit:ingest:key:") and "6f1c0d4e" not in quota
    assert candidate == "kavach:test:candidate:v1:" + "01" * 32
    other = SubmissionQuota(redis, b"j" * 32, "test")._redis_key("6f1c0d4e-key-id")
    assert other != quota


def test_retry_after_is_whole_seconds_and_at_least_one() -> None:
    assert blocked_for(1).retry_after_seconds == 1
    assert blocked_for(1500).retry_after_seconds == 2
    assert blocked_for(60_000).retry_after_seconds == 60


def test_candidate_rebuild_is_an_operator_command() -> None:
    args = build_parser().parse_args(["candidates", "rebuild", "--actor", "root"])
    assert (args.group, args.action, args.actor) == ("candidates", "rebuild", "root")


def configured(redis_url: str, **override: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "database_url": "postgresql+psycopg://kavach_app:unused@127.0.0.1:1/kavach_test",
        "redis_url": redis_url,
        "app_origin": ORIGIN,
        "rate_limit_hmac_key": "r" * 32,
        "audit_hmac_keys": json.dumps({"v1": "a" * 32}),
        "audit_hmac_active_version": "v1",
        "subscriber_hmac_keys": json.dumps({"v1": "s" * 32}),
        "subscriber_hmac_active_version": "v1",
        "payload_hmac_keys": json.dumps({"v1": "p" * 32}),
        "payload_hmac_active_version": "v1",
    }
    return Settings(**(values | override))


@pytest.fixture
def black_hole() -> Iterator[int]:
    """A TCP listener that accepts connections and never replies (a hung Redis)."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        server.settimeout(0.1)
        while not stop.is_set():
            try:
                held.append(server.accept()[0])
            except TimeoutError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield server.getsockname()[1]
    stop.set()
    thread.join()
    for connection in held:
        connection.close()
    server.close()


@pytest.mark.parametrize("hung", [False, True])
def test_presented_keys_fail_closed_when_redis_is_down_or_hung(hung: bool, black_hole: int) -> None:
    port = black_hole if hung else 1
    app = create_app(configured(f"redis://:unused@127.0.0.1:{port}/15"))
    headers = {"Authorization": "Bearer kvk_" + "A" * 43}
    with TestClient(app, base_url=ORIGIN) as client:
        started = time.monotonic()
        submit = client.post("/api/v1/events/sms", json={}, headers=headers)
        receipt = client.get("/api/v1/events/00000000-0000-0000-0000-000000000000", headers=headers)
        elapsed = time.monotonic() - started
    for response in (submit, receipt):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
        assert "kvk_" not in response.text
    # Two requests, each bounded by one 0.5 s Redis timeout and no retries.
    assert elapsed < 2.5


def test_requests_without_a_credential_are_rejected_without_touching_redis() -> None:
    app = create_app(configured("redis://:unused@127.0.0.1:1/15"))
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post("/api/v1/events/sms", json={})
    assert (response.status_code, response.json()["error"]["code"]) == (401, "INVALID_CREDENTIALS")


def test_the_deadline_setting_is_bounded() -> None:
    assert configured("redis://:x@127.0.0.1:1/15").inference_timeout_seconds == 30.0
    with pytest.raises(ValueError):
        configured("redis://:x@127.0.0.1:1/15", inference_timeout_seconds=0)
