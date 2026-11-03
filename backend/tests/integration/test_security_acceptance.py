"""M2.5 security acceptance against real PostgreSQL: findings fixed in this milestone and
scenarios not covered earlier (revocation finality, retention procedure limits, concurrent
bootstrap and provisioning, write-ahead retention audit)."""

import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.exc import IntegrityError, ProgrammingError

import kavach.db.retention as retention
from kavach.auth.accounts import AccountError, AccountService
from kavach.db.models import AuditRecord, IngestKey, User, UserSession
from kavach.db.retention import RetentionRefused, run_audited_retention, run_retention

from . import schema_rows as rows
from .auth_support import OPERATOR_PASSWORD, OPERATOR_USERNAME, Account

pytestmark = pytest.mark.integration

PAST = datetime(2001, 1, 1, tzinfo=UTC)


# --- revocation is final ------------------------------------------------------------------


@pytest.fixture
def revoked(migration_engine: Engine, make_user: Callable[..., Account]) -> dict[str, UUID]:
    account = make_user()
    now = datetime.now(UTC)
    with migration_engine.begin() as connection:
        session_id = rows.add(
            connection, UserSession, rows.user_session(account.id, revoked_at=now)
        )
        key_id = rows.add(connection, IngestKey, rows.ingest_key(account.id, revoked_at=now))
    return {"session": session_id, "key": key_id}


@pytest.mark.parametrize("engine_name", ["runtime_engine", "migration_engine"])
@pytest.mark.parametrize("value", [None, datetime(2030, 1, 1, tzinfo=UTC)])
def test_revoked_sessions_and_keys_cannot_be_reinstated(
    revoked: dict[str, UUID], request: pytest.FixtureRequest, engine_name: str, value: Any
) -> None:
    engine: Engine = request.getfixturevalue(engine_name)
    for model, key in ((UserSession, "session"), (IngestKey, "key")):
        with pytest.raises(IntegrityError) as error, engine.begin() as connection:
            connection.execute(
                update(model).where(model.id == revoked[key]).values(revoked_at=value)
            )
        assert rows.violated_constraint(error) == "revocation_is_final"


# --- the retention procedure --------------------------------------------------------------


def purge(engine: Engine, target: str, cutoff: datetime, batch: int = 100) -> int:
    with engine.begin() as connection:
        return connection.execute(
            text("SELECT kavach_retention_purge(:t, :c, :b)"),
            {"t": target, "c": cutoff, "b": batch},
        ).scalar_one()


@pytest.mark.parametrize(
    ("target", "cutoff", "batch"),
    [
        ("audit_records", datetime.now(UTC) + timedelta(days=1), 100),
        ("users", PAST, 100),
        ("ingest_keys", PAST, 100),
        ("audit_records; DROP TABLE users", PAST, 100),
        ("audit_records", PAST, 0),
        ("audit_records", PAST, 10_001),
    ],
)
def test_purge_refuses_future_cutoffs_unknown_targets_and_bad_batches(
    retention_engine: Engine, target: str, cutoff: datetime, batch: int
) -> None:
    with pytest.raises(Exception) as error:
        purge(retention_engine, target, cutoff, batch)
    assert getattr(getattr(error.value, "orig", None), "sqlstate", None) == "22023"


def test_retention_role_cannot_delete_unexpired_audit_records(
    retention_engine: Engine, migration_engine: Engine
) -> None:
    with migration_engine.begin() as connection:
        live = rows.add(
            connection, AuditRecord, rows.audit(expires_at=datetime.now(UTC) + timedelta(days=30))
        )
    with pytest.raises(ProgrammingError, match="permission denied"):
        with retention_engine.begin() as connection:
            connection.execute(text("DELETE FROM audit_records WHERE id = :id"), {"id": live})
    purge(retention_engine, "audit_records", datetime.now(UTC) - timedelta(seconds=1))
    with migration_engine.connect() as connection:
        assert (
            connection.execute(
                select(func.count()).select_from(AuditRecord).where(AuditRecord.id == live)
            ).scalar_one()
            == 1
        )


def test_a_future_cutoff_is_refused_before_anything_runs(retention_engine: Engine) -> None:
    with pytest.raises(RetentionRefused, match="database's current time"):
        run_retention(
            retention_engine,
            confirm_database="kavach_test",
            as_of=datetime.now(UTC) + timedelta(days=3650),
            dry_run=False,
        )


def test_the_default_cutoff_is_the_database_clock(retention_engine: Engine) -> None:
    report = run_retention(retention_engine, confirm_database="kavach_test", dry_run=True)
    assert abs(report.as_of - datetime.now(UTC)) < timedelta(minutes=1)


# --- write-ahead retention audit ----------------------------------------------------------


@pytest.fixture
def expired_audit_row(migration_engine: Engine) -> Iterator[UUID]:
    with migration_engine.begin() as connection:
        row = rows.add(connection, AuditRecord, rows.audit(expires_at=PAST))
    yield row
    with migration_engine.begin() as connection:
        connection.execute(text("DELETE FROM audit_records WHERE id = :id"), {"id": row})


def audit_exists(engine: Engine, row: UUID) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                select(func.count()).select_from(AuditRecord).where(AuditRecord.id == row)
            ).scalar_one()
        )


def test_retention_records_its_start_before_deleting(
    retention_engine: Engine, migration_engine: Engine, expired_audit_row: UUID
) -> None:
    seen: list[tuple[str, UUID, bool]] = []

    def record(action: str, run_id: UUID) -> None:
        seen.append((action, run_id, audit_exists(migration_engine, expired_audit_row)))

    report = run_audited_retention(
        retention_engine, record=record, confirm_database="kavach_test", as_of=PAST, dry_run=False
    )
    assert seen == [
        ("retention.start", report.run_id, True),  # nothing deleted yet
        ("retention.complete", report.run_id, False),
    ]


def test_a_failed_start_record_prevents_any_deletion(
    retention_engine: Engine, migration_engine: Engine, expired_audit_row: UUID
) -> None:
    def record(action: str, run_id: UUID) -> None:
        raise RuntimeError("audit store unavailable")

    with pytest.raises(RuntimeError):
        run_audited_retention(
            retention_engine,
            record=record,
            confirm_database="kavach_test",
            as_of=PAST,
            dry_run=False,
        )
    assert audit_exists(migration_engine, expired_audit_row)


def test_an_interrupted_run_leaves_a_start_without_a_completion(
    retention_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def crash(*args: Any) -> None:
        raise ConnectionError("lost the database mid-run")

    monkeypatch.setattr(retention, "execute", crash)
    with pytest.raises(ConnectionError):
        run_audited_retention(
            retention_engine,
            record=lambda action, run_id: seen.append(action),
            confirm_database="kavach_test",
            as_of=PAST,
            dry_run=False,
        )
    assert seen == ["retention.start"]


def test_dry_runs_write_no_audit_records(retention_engine: Engine) -> None:
    seen: list[str] = []
    run_audited_retention(
        retention_engine,
        record=lambda action, run_id: seen.append(action),
        confirm_database="kavach_test",
        as_of=PAST,
        dry_run=True,
    )
    assert seen == []


# --- bootstrap and provisioning under concurrency -----------------------------------------


@pytest.fixture
def no_active_admin(migration_engine: Engine) -> Iterator[None]:
    """Every admin inactive (only reachable outside the CLI); restored afterwards."""
    with migration_engine.begin() as connection:
        admins = list(
            connection.execute(
                update(User)
                .where(User.role == "admin", User.is_active)
                .values(is_active=False)
                .returning(User.id)
            ).scalars()
        )
    yield
    with migration_engine.begin() as connection:
        connection.execute(
            update(User)
            .where(User.role == "admin", User.username.like("boot.%"))
            .values(is_active=False)
        )
        if admins:
            connection.execute(update(User).where(User.id.in_(admins)).values(is_active=True))


def concurrently(count: int, action: Callable[[int], str]) -> list[str]:
    results: list[str] = []
    barrier = threading.Barrier(count)

    def run(index: int) -> None:
        barrier.wait()
        results.append(action(index))

    threads = [threading.Thread(target=run, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_concurrent_bootstrap_creates_exactly_one_admin(
    accounts: AccountService, no_active_admin: None
) -> None:
    run = uuid4().hex[:6]

    def bootstrap(index: int) -> str:
        try:
            accounts.bootstrap_admin(
                username=f"boot.{run}.{index}",
                display_name="Bootstrap",
                password="bootstrap passphrase",
            )
            return "created"
        except AccountError:
            return "refused"

    assert sorted(concurrently(8, bootstrap)) == ["created"] + ["refused"] * 7


def test_bootstrap_is_the_documented_recovery_when_no_admin_is_active(
    accounts: AccountService, no_active_admin: None
) -> None:
    user_id = accounts.bootstrap_admin(
        username=f"boot.recovery.{uuid4().hex[:6]}",
        display_name="Recovery",
        password="recovery passphrase",
    )
    assert user_id
    with pytest.raises(AccountError, match="active admin exists"):
        accounts.bootstrap_admin(
            username=f"boot.second.{uuid4().hex[:6]}",
            display_name="Second",
            password="recovery passphrase",
        )


def test_concurrent_provisioning_of_one_username_is_refused_cleanly(
    accounts: AccountService, operator_id: UUID
) -> None:
    username = f"race.{uuid4().hex[:8]}"

    def provision(index: int) -> str:
        try:
            accounts.provision_user(
                actor_id=operator_id,
                username=username,
                display_name="Race",
                role="viewer",
                password="race test passphrase",
            )
            return "created"
        except AccountError as error:
            return str(error)

    assert sorted(concurrently(6, provision)) == ["That username is already provisioned"] * 5 + [
        "created"
    ]


def test_cli_reports_a_rejected_change_as_a_refusal(
    run_cli: Callable[..., Any], operator_id: UUID
) -> None:
    username = f"cli.dup.{uuid4().hex[:6]}"
    argv = [
        "user",
        "create",
        "--username",
        username,
        "--display-name",
        "Dup",
        "--role",
        "viewer",
        "--actor",
        OPERATOR_USERNAME,
    ]
    assert run_cli(argv, OPERATOR_PASSWORD, "duplicate passphrase")[0] == 0
    code, _, err = run_cli(argv, OPERATOR_PASSWORD, "duplicate passphrase")
    assert (code, err.strip()) == (1, "Refused: That username is already provisioned")
