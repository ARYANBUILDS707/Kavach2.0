"""MVP-B5: the D08 read limit against real Redis and PostgreSQL.

120 session-authenticated GETs per minute per user, one budget across `/auth/session`,
`/system/models`, `/simulator/scenarios` and the incident reads, shared by every process. Redis
unavailable means 503, never an in-process fallback.
"""

import multiprocessing
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis import Redis

from kavach.auth import throttle
from kavach.auth.ingest_keys import IngestKeyService
from kavach.main import create_app

from .auth_support import ORIGIN, Account, FakeClock, auth_settings, login, reads_in_process

pytestmark = pytest.mark.integration

LIMIT = throttle.READS_PER_USER
READ_PATHS = [
    "/api/v1/auth/session",
    "/api/v1/system/models",
    "/api/v1/incidents",
    f"/api/v1/incidents/{uuid4()}",  # a 404 is still a read
]


def signed_in(client: TestClient, account: Account) -> TestClient:
    assert login(client, account.username, account.password).status_code == 200
    return client


def session_cookie(client: TestClient) -> tuple[str, str]:
    [(name, value)] = client.cookies.items()
    return name, value


def test_one_budget_is_shared_by_every_read_route_then_429_with_retry_after(
    client: TestClient, make_user: Callable[..., Account]
) -> None:
    signed_in(client, make_user(role="admin"))
    paths = READ_PATHS + ["/api/v1/simulator/scenarios"]
    statuses = [client.get(paths[i % len(paths)]).status_code for i in range(LIMIT)]
    assert statuses.count(429) == 0 and set(statuses) <= {200, 404}
    for path in paths:
        blocked = client.get(path)
        assert blocked.status_code == 429, path
        assert blocked.json()["error"]["code"] == "RATE_LIMITED"
        assert 1 <= int(blocked.headers["Retry-After"]) <= throttle.READ_WINDOW_SECONDS
        assert blocked.headers["Cache-Control"] == "no-store"


def test_the_budget_is_per_user(
    app: FastAPI, client: TestClient, make_user: Callable[..., Account]
) -> None:
    signed_in(client, make_user(role="viewer"))
    assert [client.get("/api/v1/incidents").status_code for _ in range(LIMIT)] == [200] * LIMIT
    assert client.get("/api/v1/incidents").status_code == 429
    with TestClient(app, base_url=ORIGIN) as other:
        signed_in(other, make_user(role="viewer"))
        assert other.get("/api/v1/incidents").status_code == 200


def test_unauthenticated_forbidden_login_logout_and_key_reads_are_not_counted(
    app: FastAPI, client: TestClient, make_user: Callable[..., Account], operator_id: UUID
) -> None:
    viewer = make_user(role="viewer")
    for _ in range(LIMIT + 5):
        assert client.get("/api/v1/incidents").status_code == 401
    signed_in(client, viewer)
    for _ in range(10):
        assert client.get("/api/v1/simulator/scenarios").status_code == 403  # role first
    keys: IngestKeyService = app.state.ingest_keys
    key = keys.create(
        actor_id=operator_id, name="reads", source="simulator", lifetime=timedelta(days=1)
    ).plaintext
    with TestClient(app, base_url=ORIGIN) as machine:
        for _ in range(5):
            receipt = machine.get(
                f"/api/v1/events/{uuid4()}", headers={"Authorization": f"Bearer {key}"}
            )
            assert receipt.status_code == 404
    signed_in(client, viewer)  # a second login is not a read
    statuses = [client.get("/api/v1/system/models").status_code for _ in range(LIMIT)]
    assert statuses == [200] * LIMIT
    assert client.get("/api/v1/system/models").status_code == 429


def test_the_limit_recovers_when_the_window_slides(
    client: TestClient, make_user: Callable[..., Account], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(throttle, "READS_PER_USER", 3)
    monkeypatch.setattr(throttle, "READ_WINDOW_SECONDS", 1)
    signed_in(client, make_user(role="analyst"))
    assert [client.get("/api/v1/auth/session").status_code for _ in range(3)] == [200] * 3
    assert client.get("/api/v1/auth/session").status_code == 429
    time.sleep(1.1)
    assert client.get("/api/v1/auth/session").status_code == 200


def test_two_processes_cannot_exceed_the_shared_budget(
    client: TestClient, make_user: Callable[..., Account], keys: tuple[str, str], clock: FakeClock
) -> None:
    signed_in(client, make_user(role="viewer"))
    cookie = session_cookie(client)
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(2, mp_context=context) as pool:
        runs = [pool.submit(reads_in_process, cookie, clock.now, 80, *keys) for _ in range(2)]
        statuses = [status for run in runs for status in run.result(timeout=120)]
    assert statuses.count(200) == LIMIT
    assert statuses.count(429) == 160 - LIMIT


def test_redis_unavailable_fails_every_read_closed_with_503(
    client: TestClient, make_user: Callable[..., Account], keys: tuple[str, str], clock: FakeClock
) -> None:
    # A healthy app issues the session; a second app shares PostgreSQL but cannot reach Redis.
    signed_in(client, make_user(role="admin"))
    cookie = session_cookie(client)
    broken = create_app(
        auth_settings(*keys, redis_url="redis://:unused@127.0.0.1:1/15"), clock=clock
    )
    with TestClient(broken, base_url=ORIGIN) as reader:
        reader.cookies.set(*cookie)
        for path in READ_PATHS + ["/api/v1/simulator/scenarios"]:
            response = reader.get(path)
            assert response.status_code == 503, path
            assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
        # The session itself is still valid: the healthy app keeps serving it.
    assert client.get("/api/v1/auth/session").status_code == 200


def test_redis_keys_hold_no_user_id_or_session_material(
    client: TestClient, make_user: Callable[..., Account], redis_client: Redis
) -> None:
    viewer = make_user(role="viewer")
    signed_in(client, viewer)
    client.get("/api/v1/incidents")
    names = [key.decode() for key in redis_client.scan_iter("kavach:test:ratelimit:read:*")]
    assert len(names) == 1
    _, cookie_value = session_cookie(client)
    assert str(viewer.id) not in names[0] and viewer.username not in names[0]
    assert cookie_value not in names[0]
    members = [m.decode() for m in redis_client.zrange(names[0], 0, -1)]
    assert all(str(viewer.id) not in m and cookie_value not in m for m in members)
