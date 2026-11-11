"""M3.2 against real PostgreSQL and Redis: candidate index (D05 window, lateness, order,
duplicates, processes), shared ingestion limits (D08), invalid-Bearer throttling, deadline,
Redis failure after commit, recovery, and privacy of everything written to Redis."""

import logging
import multiprocessing
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from redis import Redis
from sqlalchemy import Engine, func, select, text

import kavach.auth.throttle as throttle
import kavach.correlation.candidates as candidates_module
from kavach.auth.ingest_keys import IngestKeyService
from kavach.correlation.candidates import CandidateIndex
from kavach.db.models import Event, Incident
from kavach.main import create_app

from .auth_support import (
    OPERATOR_PASSWORD,
    OPERATOR_USERNAME,
    ORIGIN,
    FakeClock,
    auth_settings,
    submissions_in_process,
)

pytestmark = pytest.mark.integration

TOKEN = "sub_resilience_a"
TEXT = "Synthetic: verify your wallet now at the link"


@pytest.fixture(autouse=True)
def clean_candidates(redis_client: Redis) -> Iterator[None]:
    def clear() -> None:
        for key in redis_client.scan_iter("kavach:test:candidate:*"):
            redis_client.delete(key)

    clear()
    yield
    clear()


@pytest.fixture
def make_key(app: FastAPI, operator_id: UUID) -> Callable[..., str]:
    keys: IngestKeyService = app.state.ingest_keys

    def make(source: str = "simulator") -> str:
        return keys.create(actor_id=operator_id, name=f"feed {source}", source=source).plaintext

    return make


@pytest.fixture
def key(make_key: Callable[..., str]) -> str:
    return make_key()


def body(when: datetime, token: str = TOKEN, **override: Any) -> dict[str, Any]:
    return {
        "event_id": f"evt-{uuid4().hex[:12]}",
        "subscriber_token": token,
        "timestamp": when.isoformat(),
        "source": "simulator",
        "text": TEXT,
    } | override


def post(client: TestClient, key: str, payload: Any, kind: str = "sms") -> Response:
    return client.post(
        f"/api/v1/events/{kind}", json=payload, headers={"Authorization": f"Bearer {key}"}
    )


def candidate_key(app: FastAPI, token: str = TOKEN) -> str:
    digest = app.state.ingestion.subscriber_digests.digest(token.encode())
    return app.state.ingestion.candidates.key("v1", digest)


def members(redis: Redis, key: str) -> dict[str, float]:
    return {m.decode(): s for m, s in redis.zrange(key, 0, -1, withscores=True)}


def ms(moment: datetime) -> float:
    return float(int(moment.timestamp() * 1000))


# --- candidate index ----------------------------------------------------------------------


def test_new_events_are_indexed_once_with_event_time_scores_and_a_40_minute_ttl(
    client: TestClient, app: FastAPI, key: str, clock: FakeClock, redis_client: Redis
) -> None:
    payload = body(clock.now)
    receipt = post(client, key, payload).json()["data"]
    redis_key = candidate_key(app)
    assert members(redis_client, redis_key) == {f"sms:{receipt['event_id']}": ms(clock.now)}
    assert 2390 < redis_client.ttl(redis_key) <= 2400
    assert post(client, key, payload).status_code == 200  # replay
    assert redis_client.zcard(redis_key) == 1


def test_out_of_order_arrivals_are_found_by_event_time(
    client: TestClient, app: FastAPI, key: str, clock: FakeClock
) -> None:
    # The call happened later but arrives first; the SMS arrives 5 minutes after it.
    call = post(
        client, key, {k: v for k, v in body(clock.now).items() if k != "text"}, "call"
    ).json()["data"]
    clock.advance(minutes=5)
    sms = post(client, key, body(clock.now - timedelta(minutes=12))).json()["data"]
    index: CandidateIndex = app.state.ingestion.candidates
    digest = app.state.ingestion.subscriber_digests.digest(TOKEN.encode())
    near = index.near("v1", digest, clock.now - timedelta(minutes=12))
    assert {(c.kind, str(c.event_id)) for c in near} == {
        ("call", call["event_id"]),
        ("sms", sms["event_id"]),
    }


def test_window_boundaries_are_inclusive_at_30_minutes(redis_client: Redis) -> None:
    index = CandidateIndex(redis_client, "test")
    digest = bytes(range(32))
    base = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    ids = {offset: uuid4() for offset in (-31, -30, 0, 30, 31)}
    for offset, event_id in ids.items():
        index.add(
            identity_key_version="v1",
            subscriber_digest=digest,
            event_id=event_id,
            kind="sms",
            event_time=base + timedelta(minutes=offset),
            received_at=base,
        )
    found = {c.event_id for c in index.near("v1", digest, base)}
    assert found == {ids[-30], ids[0], ids[30]}


def test_candidates_older_than_the_horizon_are_skipped_and_pruned(redis_client: Redis) -> None:
    index = CandidateIndex(redis_client, "test")
    digest = bytes(range(1, 33))
    arrival = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    oldest_kept, too_old = uuid4(), uuid4()
    for event_id, age in ((oldest_kept, timedelta(minutes=40)), (too_old, timedelta(minutes=41))):
        index.add(
            identity_key_version="v1",
            subscriber_digest=digest,
            event_id=event_id,
            kind="call",
            event_time=arrival - age,
            received_at=arrival,
        )
    redis_key = index.key("v1", digest)
    assert set(members(redis_client, redis_key)) == {f"call:{oldest_kept}"}
    # A later write prunes everything that has fallen behind its own horizon.
    later = arrival + timedelta(minutes=5)
    index.add(
        identity_key_version="v1",
        subscriber_digest=digest,
        event_id=uuid4(),
        kind="sms",
        event_time=later,
        received_at=later,
    )
    assert f"call:{oldest_kept}" not in members(redis_client, redis_key)


def test_the_per_subscriber_cap_evicts_the_oldest(
    redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(candidates_module, "MAX_CANDIDATES_PER_SUBSCRIBER", 3)
    index = CandidateIndex(redis_client, "test")
    digest = bytes(range(2, 34))
    base = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    evicted = [
        index.add(
            identity_key_version="v1",
            subscriber_digest=digest,
            event_id=uuid4(),
            kind="sms",
            event_time=base + timedelta(minutes=i),
            received_at=base + timedelta(minutes=5),
        )
        for i in range(5)
    ]
    assert evicted == [0, 0, 0, 1, 1]
    scores = sorted(members(redis_client, index.key("v1", digest)).values())
    assert scores == [ms(base + timedelta(minutes=i)) for i in (2, 3, 4)]


def test_candidate_proximity_creates_no_pair_or_conclusion(
    client: TestClient, key: str, clock: FakeClock, migration_engine: Engine
) -> None:
    before = select(func.count()).select_from(Incident).where(Incident.kind == "pair")
    with migration_engine.connect() as connection:
        pairs_before = connection.execute(before).scalar_one()
    post(client, key, body(clock.now))
    post(client, key, {k: v for k, v in body(clock.now).items() if k != "text"}, "call")
    with migration_engine.connect() as connection:
        assert connection.execute(before).scalar_one() == pairs_before


def test_separate_processes_share_one_candidate_index(
    app: FastAPI, key: str, keys: tuple[str, str], redis_client: Redis
) -> None:
    now = datetime.now(UTC)
    shared = [body(now - timedelta(seconds=i)) for i in range(4)]
    own = [[body(now - timedelta(seconds=10 + 4 * p + i)) for i in range(4)] for p in range(2)]
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(2, mp_context=context) as pool:
        runs = [pool.submit(submissions_in_process, key, shared + own[p], *keys) for p in range(2)]
        statuses = sorted(s for run in runs for s in run.result(timeout=120))
    assert statuses == [200] * 4 + [201] * 12  # shared events: one 201 and one 200 each
    assert redis_client.zcard(candidate_key(app)) == 12


# --- shared submission limits -------------------------------------------------------------


def test_thirty_submissions_per_minute_then_429_with_retry_after(
    client: TestClient, key: str, clock: FakeClock
) -> None:
    first = body(clock.now)
    statuses = [post(client, key, first).status_code]
    statuses += [post(client, key, first).status_code for _ in range(9)]  # replays count
    statuses += [post(client, key, body(clock.now)).status_code for _ in range(20)]
    assert statuses == [201] + [200] * 9 + [201] * 20
    blocked = post(client, key, body(clock.now))
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert 1 <= int(blocked.headers["Retry-After"]) <= 60
    # Invalid bodies count too: the limit is checked before the body is read.
    other = post(client, key, {"not": "valid"})
    assert other.status_code == 429


def test_limits_are_per_key_and_receipt_reads_are_not_counted(
    client: TestClient, make_key: Callable[..., str], clock: FakeClock
) -> None:
    first, second = make_key(), make_key()
    created = [post(client, first, body(clock.now)).json()["data"] for _ in range(30)]
    assert post(client, first, body(clock.now)).status_code == 429
    assert post(client, second, body(clock.now)).status_code == 201
    receipt = client.get(
        f"/api/v1/events/{created[0]['event_id']}", headers={"Authorization": f"Bearer {first}"}
    )
    assert receipt.status_code == 200


def test_the_limit_recovers_when_the_window_slides(
    client: TestClient, key: str, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(throttle, "SUBMISSIONS_PER_KEY", 3)
    monkeypatch.setattr(throttle, "SUBMISSION_WINDOW_SECONDS", 1)
    assert [post(client, key, body(clock.now)).status_code for _ in range(3)] == [201] * 3
    assert post(client, key, body(clock.now)).status_code == 429
    time.sleep(1.1)
    assert post(client, key, body(clock.now)).status_code == 201


def test_two_processes_cannot_exceed_the_shared_limit(
    key: str, keys: tuple[str, str], migrated_schema: None
) -> None:
    now = datetime.now(UTC)
    batches = [[body(now - timedelta(seconds=p * 20 + i)) for i in range(20)] for p in range(2)]
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(2, mp_context=context) as pool:
        runs = [pool.submit(submissions_in_process, key, batch, *keys) for batch in batches]
        statuses = [s for run in runs for s in run.result(timeout=120)]
    assert statuses.count(201) == 30
    assert statuses.count(429) == 10


# --- invalid Bearer throttling ------------------------------------------------------------


def test_repeated_invalid_keys_are_throttled_and_valid_keys_do_not_count(
    client: TestClient, key: str, clock: FakeClock, redis_client: Redis
) -> None:
    for _ in range(40):  # valid attempts refund their reservation
        client.get(f"/api/v1/events/{uuid4()}", headers={"Authorization": f"Bearer {key}"})
    bad = {"Authorization": "Bearer kvk_" + "Z" * 43}
    statuses = [
        client.post("/api/v1/events/sms", json={}, headers=bad).status_code for _ in range(30)
    ]
    assert statuses == [401] * 30
    # Over the ceiling only a small per-IP lookup budget remains (TD-19, M3.4).
    budget = [
        client.post("/api/v1/events/sms", json={}, headers=bad).status_code
        for _ in range(throttle.BLOCKED_IP_LOOKUPS)
    ]
    assert budget == [401] * throttle.BLOCKED_IP_LOOKUPS
    blocked = client.post("/api/v1/events/sms", json={}, headers=bad)
    assert (blocked.status_code, blocked.json()["error"]["code"]) == (429, "RATE_LIMITED")
    assert 1 <= int(blocked.headers["Retry-After"]) <= 900
    # TD-19 (M3.4): other clients' failures do not lock out a valid key on the same IP.
    assert post(client, key, body(clock.now)).status_code == 201
    (counter,) = list(redis_client.scan_iter("kavach:test:ratelimit:bearer:ip:*"))
    assert int(redis_client.get(counter) or 0) == 30
    assert b"testclient" not in counter and b"kvk_" not in counter


# --- deadline and failures ----------------------------------------------------------------


def test_the_deadline_aborts_before_commit_and_a_retry_succeeds(
    migrated_schema: None,
    keys: tuple[str, str],
    key: str,
    clock: FakeClock,
    migration_engine: Engine,
) -> None:
    app = create_app(auth_settings(*keys, inference_timeout_seconds=1.0), clock=clock)
    digest = app.state.ingestion.subscriber_digests.digest(TOKEN.encode())
    lock = int.from_bytes(digest[:8], "big", signed=True)
    payload = body(clock.now)
    with migration_engine.connect() as holder, TestClient(app, base_url=ORIGIN) as client:
        holder.execute(text("SELECT pg_advisory_lock(:k)"), {"k": lock})
        started = time.monotonic()
        response = post(client, key, payload)
        elapsed = time.monotonic() - started
        holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock})
        holder.commit()
        assert (response.status_code, response.json()["error"]["code"]) == (
            503,
            "PROCESSING_TIMEOUT",
        )
        assert elapsed < 2.0
        with migration_engine.connect() as connection:
            stored = connection.execute(
                select(func.count())
                .select_from(Event)
                .where(Event.external_event_id == payload["event_id"])
            ).scalar_one()
        assert stored == 0
        assert post(client, key, payload).status_code == 201


def test_redis_outage_refuses_submissions_before_storing_anything(
    migrated_schema: None,
    keys: tuple[str, str],
    key: str,
    clock: FakeClock,
    migration_engine: Engine,
) -> None:
    app = create_app(auth_settings(*keys, redis_url="redis://:unused@127.0.0.1:1/15"), clock=clock)
    before = select(func.count()).select_from(Event)
    with migration_engine.connect() as connection:
        count_before = connection.execute(before).scalar_one()
    with TestClient(app, base_url=ORIGIN) as client:
        response = post(client, key, body(clock.now))
    assert (response.status_code, response.json()["error"]["code"]) == (
        503,
        "DEPENDENCY_UNAVAILABLE",
    )
    with migration_engine.connect() as connection:
        assert connection.execute(before).scalar_one() == count_before


def test_redis_failure_after_commit_still_reports_success_and_is_recoverable(
    client: TestClient,
    app: FastAPI,
    key: str,
    clock: FakeClock,
    redis_client: Redis,
    caplog: pytest.LogCaptureFixture,
) -> None:
    working = app.state.ingestion.candidates
    app.state.ingestion.candidates = CandidateIndex(
        Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.5), "test"
    )
    payload = body(clock.now)
    with caplog.at_level(logging.WARNING, logger="kavach.operations"):
        created = post(client, key, payload)
    member = f"sms:{created.json()['data']['event_id']}"
    assert created.status_code == 201  # the commit is authoritative
    assert any("candidate.index_deferred" in r.getMessage() for r in caplog.records)
    redis_key = candidate_key(app)
    assert redis_client.zscore(redis_key, member) is None
    app.state.ingestion.candidates = working
    # Recovery path 1: an identical retry re-indexes idempotently.
    assert post(client, key, payload).status_code == 200
    assert redis_client.zscore(redis_key, member) is not None
    # Recovery path 2: rebuilding from PostgreSQL restores a wiped index.
    redis_client.delete(redis_key)
    assert app.state.ingestion.rebuild_candidates() >= 1
    assert redis_client.zscore(redis_key, member) is not None


def test_cli_rebuilds_the_candidate_index(
    run_cli: Callable[..., Any],
    client: TestClient,
    app: FastAPI,
    key: str,
    clock: FakeClock,
    operator_id: UUID,
    redis_client: Redis,
) -> None:
    post(client, key, body(clock.now))
    redis_key = candidate_key(app)
    redis_client.delete(redis_key)
    code, out, err = run_cli(
        ["candidates", "rebuild", "--actor", OPERATOR_USERNAME], OPERATOR_PASSWORD
    )
    assert code == 0, err
    assert "Re-indexed" in out
    assert redis_client.zcard(redis_key) >= 1


# --- privacy ------------------------------------------------------------------------------


def test_nothing_sensitive_reaches_redis(
    client: TestClient, key: str, clock: FakeClock, redis_client: Redis
) -> None:
    payload = body(clock.now, sender_id="VM-WALLET")
    post(client, key, payload)
    post(client, "kvk_" + "Q" * 43, payload)
    dump = []
    for redis_key in redis_client.scan_iter("kavach:test:*"):
        dump.append(redis_key)
        kind = redis_client.type(redis_key)
        if kind == b"zset":
            dump.extend(m for m, _ in redis_client.zrange(redis_key, 0, -1, withscores=True))
        elif kind == b"string":
            dump.append(redis_client.get(redis_key) or b"")
    blob = b" ".join(dump)
    for secret in (TEXT, TOKEN, "VM-WALLET", key, "kvk_" + "Q" * 43, "testclient"):
        assert secret.encode() not in blob
