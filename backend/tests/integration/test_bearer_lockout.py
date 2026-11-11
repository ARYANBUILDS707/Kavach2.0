"""TD-19 (M3.4) against real PostgreSQL and Redis: other clients' invalid Bearer attempts must
not lock out a valid key on the same IP, while lookups from a blocked IP stay bounded, scope
and submission limits still apply, Redis failures fail closed, and separate processes share
the same state."""

import logging
import multiprocessing
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from redis import Redis, RedisError

from kavach.auth.ingest_keys import IngestKeyService
from kavach.auth.throttle import (
    BEARER_FAILURE_LIMIT,
    BLOCKED_IP_LOOKUP_WINDOW_SECONDS,
    BLOCKED_IP_LOOKUPS,
)
from kavach.main import create_app

from .auth_support import ORIGIN, FakeClock, auth_settings, submissions_in_process

pytestmark = pytest.mark.integration


@pytest.fixture
def make_key(app: FastAPI, operator_id: UUID) -> Callable[..., Any]:
    keys: IngestKeyService = app.state.ingest_keys

    def make(source: str = "simulator") -> Any:
        return keys.create(actor_id=operator_id, name=f"lockout {source}", source=source)

    return make


def invalid_key() -> str:
    return "kvk_" + uuid4().hex + uuid4().hex[:11]


def sms(clock: FakeClock, source: str = "simulator") -> dict[str, Any]:
    return {
        "event_id": f"lock-{uuid4().hex[:12]}",
        "subscriber_token": "sub_lockout_a",
        "timestamp": clock.now.isoformat(),
        "source": source,
        "text": "Synthetic lockout probe",
    }


def submit(client: TestClient, key: str, body: Any) -> Response:
    return client.post("/api/v1/events/sms", json=body, headers={"Authorization": f"Bearer {key}"})


def receipt(client: TestClient, key: str) -> Response:
    return client.get(f"/api/v1/events/{uuid4()}", headers={"Authorization": f"Bearer {key}"})


def block_ip(client: TestClient) -> None:
    """Exhaust the rejected-credential ceiling for the test client's address."""
    statuses = [receipt(client, invalid_key()).status_code for _ in range(BEARER_FAILURE_LIMIT)]
    assert statuses == [401] * BEARER_FAILURE_LIMIT


def spend_lookup_budget(client: TestClient) -> None:
    """An attacker uses up whatever is left of the blocked IP's lookup budget."""
    for _ in range(BLOCKED_IP_LOOKUPS + 1):
        if receipt(client, invalid_key()).status_code == 429:
            return
    pytest.fail("the lookup budget never ran out")


def lookups(caplog: pytest.LogCaptureFixture) -> int:
    """Rejections after a database lookup (`reason=unknown`); throttled ones never look up."""
    return sum("reason=unknown" in r.getMessage() for r in caplog.records)


@pytest.fixture(autouse=True)
def security_log(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    caplog.set_level(logging.WARNING, logger="kavach.security")
    yield


# --- a valid key keeps working --------------------------------------------------------------


def test_a_valid_key_is_not_locked_out_by_other_clients_on_its_ip(
    client: TestClient, make_key: Callable[..., Any], clock: FakeClock
) -> None:
    block_ip(client)
    assert receipt(client, invalid_key()).status_code == 401  # still within the lookup budget
    first_use = make_key().plaintext  # never used before: admitted by the lookup budget
    assert submit(client, first_use, sms(clock)).status_code == 201
    spend_lookup_budget(client)
    # Budget spent by an attacker: the recently valid key is still checked and accepted.
    assert submit(client, first_use, sms(clock)).status_code == 201
    assert receipt(client, first_use).status_code == 404  # authenticated, unknown event
    # Residual risk: a key never seen valid waits until the lookup window passes.
    cold = submit(client, make_key().plaintext, sms(clock))
    assert cold.status_code == 429
    assert 1 <= int(cold.headers["Retry-After"]) <= BLOCKED_IP_LOOKUP_WINDOW_SECONDS


def test_a_valid_key_used_before_the_attack_never_needs_the_budget(
    client: TestClient, make_key: Callable[..., Any], clock: FakeClock
) -> None:
    key = make_key().plaintext
    assert submit(client, key, sms(clock)).status_code == 201
    block_ip(client)
    spend_lookup_budget(client)
    assert [submit(client, key, sms(clock)).status_code for _ in range(5)] == [201] * 5


# --- the blocked IP stays bounded -----------------------------------------------------------


def test_lookups_from_a_blocked_ip_are_bounded(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    block_ip(client)
    before = lookups(caplog)
    statuses = [receipt(client, invalid_key()).status_code for _ in range(50)]
    assert statuses == [401] * BLOCKED_IP_LOOKUPS + [429] * (50 - BLOCKED_IP_LOOKUPS)
    assert lookups(caplog) - before == BLOCKED_IP_LOOKUPS
    # Malformed credentials from a blocked IP are refused without a lookup or budget.
    malformed = client.get(
        f"/api/v1/events/{uuid4()}", headers={"Authorization": "Bearer not-a-kavach-key"}
    )
    assert malformed.status_code == 429
    assert lookups(caplog) - before == BLOCKED_IP_LOOKUPS


def test_a_revoked_key_loses_its_blocked_ip_access(
    app: FastAPI,
    client: TestClient,
    make_key: Callable[..., Any],
    operator_id: UUID,
    clock: FakeClock,
) -> None:
    issued = make_key()
    assert submit(client, issued.plaintext, sms(clock)).status_code == 201
    block_ip(client)
    spend_lookup_budget(client)
    app.state.ingest_keys.revoke(actor_id=operator_id, key_id=issued.key_id)
    # The marker only allows one more database check, which sees the revocation.
    first = submit(client, issued.plaintext, sms(clock))
    assert (first.status_code, first.json()["error"]["code"]) == (401, "INVALID_CREDENTIALS")
    assert submit(client, issued.plaintext, sms(clock)).status_code == 429


def test_an_expired_key_is_rejected_from_a_blocked_ip(
    client: TestClient, make_key: Callable[..., Any], clock: FakeClock
) -> None:
    key = make_key().plaintext
    assert submit(client, key, sms(clock)).status_code == 201
    block_ip(client)
    clock.advance(days=91)  # past the default 90-day lifetime
    assert submit(client, key, sms(clock)).status_code == 401


# --- scope and submission limits still apply ------------------------------------------------


def test_a_valid_key_on_a_blocked_ip_keeps_its_scope_and_submission_limit(
    client: TestClient, make_key: Callable[..., Any], clock: FakeClock
) -> None:
    key = make_key().plaintext
    assert submit(client, key, sms(clock)).status_code == 201
    block_ip(client)
    forbidden = submit(client, key, sms(clock, source="partner-feed"))
    assert (forbidden.status_code, forbidden.json()["error"]["code"]) == (403, "FORBIDDEN")
    statuses = [submit(client, key, sms(clock)).status_code for _ in range(29)]
    assert statuses == [201] * 28 + [429]  # 30 per minute per key, all attempts counted


# --- Redis failures fail closed ---------------------------------------------------------------


def test_blocked_ip_admission_fails_closed_when_redis_fails(
    app: FastAPI,
    client: TestClient,
    make_key: Callable[..., Any],
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    key = make_key().plaintext
    assert submit(client, key, sms(clock)).status_code == 201
    block_ip(client)

    def broken(**kwargs: Any) -> Any:
        raise RedisError("unavailable")

    monkeypatch.setattr(app.state.bearer_throttle, "_admit", broken)
    before = lookups(caplog)
    for presented in (key, invalid_key()):
        response = submit(client, presented, sms(clock))
        body = response.json()
        assert (response.status_code, body["error"]["code"]) == (503, "DEPENDENCY_UNAVAILABLE")
        assert presented not in response.text
    assert lookups(caplog) == before


def test_a_valid_key_fails_closed_without_redis(
    keys: tuple[str, str], make_key: Callable[..., Any], clock: FakeClock
) -> None:
    key = make_key().plaintext
    settings = auth_settings(*keys, redis_url="redis://:unused@127.0.0.1:1/15")
    with TestClient(create_app(settings, clock=clock), base_url=ORIGIN) as client:
        response = submit(client, key, sms(clock))
    assert (response.status_code, response.json()["error"]["code"]) == (
        503,
        "DEPENDENCY_UNAVAILABLE",
    )


# --- separate processes share the state -----------------------------------------------------------


def test_separate_processes_share_the_block_and_the_lookup_budget(
    client: TestClient,
    make_key: Callable[..., Any],
    clock: FakeClock,
    keys: tuple[str, str],
) -> None:
    valid = make_key().plaintext
    attacker = [[{} for _ in range(20)], [{} for _ in range(20)]]
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(2, mp_context=context) as pool:
        runs = [
            pool.submit(submissions_in_process, invalid_key(), batch, *keys) for batch in attacker
        ]
        statuses = [s for run in runs for s in run.result(timeout=120)]
    # 30 rejections fill the shared bucket, 10 lookups use the shared budget, nothing more.
    assert statuses.count(401) == BEARER_FAILURE_LIMIT + BLOCKED_IP_LOOKUPS
    assert statuses.count(429) == 40 - BEARER_FAILURE_LIMIT - BLOCKED_IP_LOOKUPS
    # This process never used the valid key, and the budget is gone: it waits (residual risk)...
    assert submit(client, valid, sms(clock)).status_code == 429


def test_a_key_used_in_one_process_is_admitted_in_another(
    client: TestClient,
    make_key: Callable[..., Any],
    clock: FakeClock,
    keys: tuple[str, str],
) -> None:
    valid = make_key().plaintext
    body = sms(clock)
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(1, mp_context=context) as pool:
        # Another backend process accepts the key once (its event time comes from the real
        # clock there, so use a receipt-free submission that fails validation but authenticates).
        assert pool.submit(submissions_in_process, valid, [{}], *keys).result(120) == [422]
    block_ip(client)
    spend_lookup_budget(client)
    assert submit(client, valid, body).status_code == 201


# --- privacy -------------------------------------------------------------------------------


def test_lockout_state_in_redis_reveals_no_keys_or_addresses(
    client: TestClient, make_key: Callable[..., Any], clock: FakeClock, redis_client: Redis
) -> None:
    key = make_key().plaintext
    assert submit(client, key, sms(clock)).status_code == 201
    block_ip(client)
    spend_lookup_budget(client)
    names = [k.decode() for k in redis_client.scan_iter("kavach:test:ratelimit:bearer:*")]
    kinds = sorted({name.split(":")[4] for name in names})
    assert kinds == ["ip", "lookup", "valid"]
    values = b" ".join(redis_client.get(name) or b"" for name in names)
    for secret in (key, key[4:], "testclient", "127.0.0.1"):
        assert secret not in " ".join(names) and secret.encode() not in values
