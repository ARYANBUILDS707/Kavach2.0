"""M2.4 against real PostgreSQL and Redis: source-scoped API keys, operator authorization, the
CLI, audit integrity and its limits, and retention."""

import hashlib
import io
import logging
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select, text, update

from kavach.auth.accounts import AccountError, AccountService
from kavach.auth.ingest_keys import IngestKeyService, IssuedKey
from kavach.cli import main as cli
from kavach.db.models import (
    Assessment,
    AuditRecord,
    Event,
    Incident,
    IncidentEvent,
    IngestKey,
    Review,
    User,
    UserSession,
)
from kavach.db.retention import RetentionRefused, run_retention
from kavach.main import create_app
from kavach.privacy.audit import AuditWriter

from . import schema_rows as rows
from .auth_support import (
    OPERATOR_PASSWORD,
    OPERATOR_USERNAME,
    ORIGIN,
    Account,
    FakeClock,
    add_test_probes,
    auth_settings,
    login,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def ingest_keys(app: FastAPI) -> IngestKeyService:
    return app.state.ingest_keys


@pytest.fixture
def issued(ingest_keys: IngestKeyService, operator_id: UUID) -> IssuedKey:
    return ingest_keys.create(actor_id=operator_id, name="simulator feed", source="simulator")


def probe(client: TestClient, source: str, authorization: str | None) -> Any:
    headers = {"Authorization": authorization} if authorization is not None else {}
    return client.get(f"/_test/ingest/{source}", headers=headers)


def scalar(engine: Engine, query: Any) -> Any:
    with engine.connect() as connection:
        return connection.execute(query).scalar()


def audit_actions(engine: Engine, resource_id: UUID) -> list[str]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                select(AuditRecord.action)
                .where(AuditRecord.resource_id == resource_id)
                .order_by(AuditRecord.created_at, AuditRecord.action)
            ).scalars()
        )


# --- API keys -----------------------------------------------------------------------------


def test_a_key_is_shown_once_and_stored_only_as_a_digest(
    issued: IssuedKey, migration_engine: Engine, app: FastAPI
) -> None:
    assert issued.plaintext.startswith("kvk_")
    with migration_engine.connect() as connection:
        row = connection.execute(select(IngestKey).where(IngestKey.id == issued.key_id)).one()
        audit = (
            connection.execute(select(AuditRecord).where(AuditRecord.resource_id == issued.key_id))
            .mappings()
            .one()
        )
    assert row.key_digest == hashlib.sha256(issued.plaintext.encode()).digest()
    assert issued.plaintext.encode() not in row.key_digest
    assert row.source == "simulator"
    assert row.expires_at - row.created_at == timedelta(days=90)
    assert audit["action"] == "key.create" and app.state.auth.audit.verify(audit)


def test_a_valid_key_authenticates_for_its_own_source_only(
    client: TestClient, issued: IssuedKey
) -> None:
    ok = probe(client, "simulator", f"Bearer {issued.plaintext}")
    assert ok.status_code == 200
    assert ok.json() == {"key_id": str(issued.key_id), "source": "simulator"}
    assert probe(client, "simulator", f"bearer {issued.plaintext}").status_code == 200
    other = probe(client, "partner-a", f"Bearer {issued.plaintext}")
    assert other.status_code == 403
    assert other.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Bearer",
        "Bearer ",
        "Basic dXNlcjpwYXNz",
        "Bearer not-a-kavach-key",
        "Bearer kvk_" + "A" * 43,
        "Bearer kvk_" + "A" * 200,
    ],
)
def test_malformed_unknown_and_oversized_keys_are_rejected_uniformly(
    client: TestClient, authorization: str | None
) -> None:
    response = probe(client, "simulator", authorization)
    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "INVALID_CREDENTIALS",
        "message": "Invalid or expired API key",
    }
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_expired_and_revoked_keys_are_rejected(
    client: TestClient,
    ingest_keys: IngestKeyService,
    operator_id: UUID,
    clock: FakeClock,
) -> None:
    short = ingest_keys.create(
        actor_id=operator_id, name="short", source="simulator", lifetime=timedelta(days=1)
    )
    revoked = ingest_keys.create(actor_id=operator_id, name="gone", source="simulator")
    ingest_keys.revoke(actor_id=operator_id, key_id=revoked.key_id)
    assert probe(client, "simulator", f"Bearer {revoked.plaintext}").status_code == 401
    assert probe(client, "simulator", f"Bearer {short.plaintext}").status_code == 200
    clock.advance(days=1)
    expired = probe(client, "simulator", f"Bearer {short.plaintext}")
    assert expired.status_code == 401
    assert expired.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_rotation_replaces_the_key_atomically(
    client: TestClient,
    ingest_keys: IngestKeyService,
    issued: IssuedKey,
    operator_id: UUID,
    migration_engine: Engine,
) -> None:
    replacement = ingest_keys.rotate(actor_id=operator_id, key_id=issued.key_id)
    assert replacement.key_id != issued.key_id and replacement.source == issued.source
    assert probe(client, "simulator", f"Bearer {issued.plaintext}").status_code == 401
    assert probe(client, "simulator", f"Bearer {replacement.plaintext}").status_code == 200
    assert audit_actions(migration_engine, issued.key_id) == ["key.create", "key.revoke"]
    assert audit_actions(migration_engine, replacement.key_id) == ["key.rotate"]
    with pytest.raises(AccountError, match="already revoked"):
        ingest_keys.rotate(actor_id=operator_id, key_id=issued.key_id)
    with pytest.raises(AccountError, match="already revoked"):
        ingest_keys.revoke(actor_id=operator_id, key_id=issued.key_id)


def test_session_cookie_with_api_key_is_rejected(client: TestClient, issued: IssuedKey) -> None:
    client.cookies.set("__Host-kavach_session", "anything")
    response = probe(client, "simulator", f"Bearer {issued.plaintext}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MIXED_CREDENTIALS"


def test_api_keys_cannot_open_browser_sessions(client: TestClient, issued: IssuedKey) -> None:
    response = client.get(
        "/api/v1/auth/session", headers={"Authorization": f"Bearer {issued.plaintext}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"


@pytest.mark.parametrize(
    ("name", "source", "days", "message"),
    [
        ("feed", "bad source", 90, "Sources are"),
        ("feed", "-leading", 90, "Sources are"),
        ("feed", "s" * 65, 90, "Sources are"),
        ("", "simulator", 90, "names must be"),
        ("feed", "simulator", 0, "lifetime"),
        ("feed", "simulator", 366, "lifetime"),
    ],
)
def test_key_requests_are_validated(
    ingest_keys: IngestKeyService,
    operator_id: UUID,
    name: str,
    source: str,
    days: int,
    message: str,
) -> None:
    with pytest.raises(AccountError, match=message):
        ingest_keys.create(
            actor_id=operator_id, name=name, source=source, lifetime=timedelta(days=days)
        )


def test_key_rejections_are_logged_without_the_key(
    client: TestClient, issued: IssuedKey, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    unknown = "kvk_" + "B" * 43
    probe(client, "simulator", f"Bearer {unknown}")
    probe(client, "simulator", f"Bearer {issued.plaintext}")
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=ingest.key_rejected reason=unknown" in logged
    assert unknown not in logged and issued.plaintext not in logged


def test_key_validation_fails_closed_when_the_database_is_down(
    migrated_schema: None, keys: tuple[str, str], issued: IssuedKey
) -> None:
    settings = auth_settings(
        *keys, database_url="postgresql+psycopg://kavach_app:unused@127.0.0.1:1/kavach_test"
    )
    with TestClient(add_test_probes(create_app(settings)), base_url=ORIGIN) as client:
        response = probe(client, "simulator", f"Bearer {issued.plaintext}")
    assert (response.status_code, response.json()["error"]["code"]) == (
        503,
        "DEPENDENCY_UNAVAILABLE",
    )


# --- operator authorization ---------------------------------------------------------------


def test_only_active_admins_may_act(
    accounts: AccountService,
    ingest_keys: IngestKeyService,
    make_user: Callable[..., Account],
    operator_id: UUID,
) -> None:
    analyst, retired_admin = make_user("analyst"), make_user("admin")
    accounts.deactivate_user(actor_id=operator_id, username=retired_admin.username)
    for actor in (analyst.id, retired_admin.id, uuid4()):
        with pytest.raises(AccountError, match="not an active admin"):
            accounts.provision_user(
                actor_id=actor,
                username=f"x.{uuid4().hex[:8]}",
                display_name="X",
                role="viewer",
                password="a long enough passphrase",
            )
        with pytest.raises(AccountError, match="not an active admin"):
            ingest_keys.create(actor_id=actor, name="feed", source="simulator")
        with pytest.raises(AccountError, match="not an active admin"):
            accounts.change_role(actor_id=actor, username=analyst.username, role="admin")


def test_operator_authentication_is_generic(
    accounts: AccountService, make_user: Callable[..., Account], operator_id: UUID
) -> None:
    analyst = make_user("analyst")
    for username, password in (
        (OPERATOR_USERNAME, "wrong passphrase"),
        (analyst.username, analyst.password),
        ("nobody." + uuid4().hex, "whatever passphrase"),
    ):
        with pytest.raises(AccountError, match="^Operator authentication failed$"):
            accounts.authenticate_operator(username, password)
    assert accounts.authenticate_operator(OPERATOR_USERNAME.upper(), OPERATOR_PASSWORD) == (
        operator_id
    )


def test_bootstrap_is_refused_while_an_active_admin_exists(
    accounts: AccountService, operator_id: UUID
) -> None:
    with pytest.raises(AccountError, match="active admin exists"):
        accounts.bootstrap_admin(
            username="second.root", display_name="Second", password="another long passphrase"
        )


def test_role_changes_are_audited_and_apply_to_live_sessions(
    client: TestClient,
    accounts: AccountService,
    make_user: Callable[..., Account],
    operator_id: UUID,
    migration_engine: Engine,
) -> None:
    viewer = make_user("viewer")
    assert login(client, viewer.username, viewer.password).status_code == 200
    assert client.get("/_test/admin-only").status_code == 403
    accounts.change_role(actor_id=operator_id, username=viewer.username, role="admin")
    assert client.get("/_test/admin-only").status_code == 200
    assert audit_actions(migration_engine, viewer.id) == ["user.provision", "user.role_change"]
    with pytest.raises(AccountError, match="already has the admin role"):
        accounts.change_role(actor_id=operator_id, username=viewer.username, role="admin")
    with pytest.raises(AccountError, match="Role must be one of"):
        accounts.change_role(actor_id=operator_id, username=viewer.username, role="root")


def test_operators_cannot_deactivate_themselves(
    accounts: AccountService, operator_id: UUID
) -> None:
    with pytest.raises(AccountError, match="their own account"):
        accounts.deactivate_user(actor_id=operator_id, username=OPERATOR_USERNAME)


@pytest.fixture
def sole_admin(migration_engine: Engine, operator_id: UUID) -> Iterator[None]:
    """Temporarily make the test operator the only active admin."""
    with migration_engine.begin() as connection:
        others = list(
            connection.execute(
                update(User)
                .where(User.role == "admin", User.is_active, User.id != operator_id)
                .values(is_active=False)
                .returning(User.id)
            ).scalars()
        )
    yield
    with migration_engine.begin() as connection:
        if others:
            connection.execute(update(User).where(User.id.in_(others)).values(is_active=True))


def test_the_last_active_admin_cannot_be_demoted(
    accounts: AccountService, operator_id: UUID, sole_admin: None
) -> None:
    with pytest.raises(AccountError, match="last active admin"):
        accounts.change_role(actor_id=operator_id, username=OPERATOR_USERNAME, role="analyst")


def test_password_reset_policy_and_unknown_users(
    accounts: AccountService, make_user: Callable[..., Account], operator_id: UUID
) -> None:
    target = make_user()
    with pytest.raises(AccountError, match="12-256"):
        accounts.reset_password(actor_id=operator_id, username=target.username, new_password="x")
    with pytest.raises(AccountError, match="No such user"):
        accounts.deactivate_user(actor_id=operator_id, username="nobody." + uuid4().hex)


# --- audit integrity ----------------------------------------------------------------------


@pytest.fixture
def broken_audit(app: FastAPI) -> AuditWriter:
    """An audit writer that fails to sign: its active key version has no key."""
    return AuditWriter({"v1": b"k" * 32}, "missing-version", timedelta(days=30))


def test_failed_audit_writes_roll_back_the_mutation(
    app: FastAPI,
    clock: FakeClock,
    broken_audit: AuditWriter,
    make_user: Callable[..., Account],
    operator_id: UUID,
    migration_engine: Engine,
) -> None:
    target = make_user()
    accounts = AccountService(
        sessions=app.state.db_sessions,
        passwords=app.state.auth.passwords,
        audit=broken_audit,
        clock=clock,
    )
    keys = IngestKeyService(sessions=app.state.db_sessions, audit=broken_audit, clock=clock)
    with pytest.raises(KeyError):
        accounts.deactivate_user(actor_id=operator_id, username=target.username)
    with pytest.raises(KeyError):
        accounts.change_role(actor_id=operator_id, username=target.username, role="admin")
    keys_before = scalar(migration_engine, select(func.count()).select_from(IngestKey))
    with pytest.raises(KeyError):
        keys.create(actor_id=operator_id, name="rolled back", source="simulator")
    with migration_engine.connect() as connection:
        active, role = connection.execute(
            select(User.is_active, User.role).where(User.id == target.id)
        ).one()
    assert (active, role) == (True, "analyst")
    assert scalar(migration_engine, select(func.count()).select_from(IngestKey)) == keys_before


def test_audit_detects_modification_but_not_deletion(
    app: FastAPI,
    make_user: Callable[..., Account],
    accounts: AccountService,
    operator_id: UUID,
    migration_engine: Engine,
) -> None:
    target = make_user()
    accounts.change_role(actor_id=operator_id, username=target.username, role="viewer")
    writer = app.state.auth.audit
    query = select(AuditRecord).where(AuditRecord.resource_id == target.id)
    with migration_engine.begin() as connection:
        provisioned, changed = (
            connection.execute(query.order_by(AuditRecord.created_at, AuditRecord.action))
            .mappings()
            .all()
        )
        assert writer.verify(provisioned) and writer.verify(changed)
        # Modification by a privileged database user is detectable...
        connection.execute(
            update(AuditRecord)
            .where(AuditRecord.id == changed["id"])
            .values(action="user.provision")
        )
        tampered = (
            connection.execute(select(AuditRecord).where(AuditRecord.id == changed["id"]))
            .mappings()
            .one()
        )
        assert not writer.verify(tampered)
        # ...but deletion is not: what remains still verifies and nothing marks the gap.
        connection.execute(delete(AuditRecord).where(AuditRecord.id == changed["id"]))
        remaining = connection.execute(query).mappings().all()
        assert len(remaining) == 1 and all(writer.verify(row) for row in remaining)


# --- CLI ----------------------------------------------------------------------------------


@pytest.fixture
def run_cli(keys: tuple[str, str], clock: FakeClock, migrated_schema: None) -> Callable[..., Any]:
    settings = auth_settings(
        *keys, retention_database_url=os.environ["TEST_RETENTION_DATABASE_URL"]
    )

    def run(argv: list[str], *stdin_lines: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = cli(
            [*argv, "--stdin"],
            stdin=io.StringIO("".join(f"{line}\n" for line in stdin_lines)),
            out=out,
            err=err,
            clock=clock,
            settings=settings,
        )
        return code, out.getvalue(), err.getvalue()

    return run


def operator(*argv: str) -> list[str]:
    return [*argv, "--actor", OPERATOR_USERNAME]


def test_cli_user_lifecycle(
    run_cli: Callable[..., Any], operator_id: UUID, migration_engine: Engine, clock: FakeClock
) -> None:
    username, password = f"cli.{uuid4().hex[:10]}", "cli first passphrase"
    code, out, err = run_cli(
        operator(
            "user",
            "create",
            "--username",
            username,
            "--display-name",
            "CLI User",
            "--role",
            "viewer",
        ),
        OPERATOR_PASSWORD,
        password,
    )
    assert code == 0, err
    assert password not in out + err and OPERATOR_PASSWORD not in out + err
    user_id = UUID(out.split()[-1])
    steps = [
        (operator("user", "set-role", "--username", username, "--role", "analyst"), ()),
        (operator("user", "reset-password", "--username", username), ("cli second passphrase",)),
        (operator("user", "deactivate", "--username", username), ()),
    ]
    for argv, extra in steps:
        clock.advance(seconds=1)  # distinct timestamps, so the audit order below is real
        code, out, err = run_cli(argv, OPERATOR_PASSWORD, *extra)
        assert code == 0, err
    assert audit_actions(migration_engine, user_id) == [
        "user.provision",
        "user.role_change",
        "user.password_reset",
        "user.deactivate",
    ]
    code, _, err = run_cli(operator("user", "deactivate", "--username", username), "wrong pass")
    assert (code, err.strip()) == (1, "Refused: Operator authentication failed")
    code, _, err = run_cli(
        ["user", "create", "--username", "x.y", "--display-name", "X", "--bootstrap"],
        "a long enough passphrase",
    )
    assert code == 1 and "active admin exists" in err


def test_cli_key_lifecycle_prints_the_secret_exactly_once(
    run_cli: Callable[..., Any], client: TestClient, operator_id: UUID
) -> None:
    code, out, err = run_cli(
        operator(
            "key",
            "create",
            "--name",
            "cli feed",
            "--source",
            "partner-a",
            "--expires-in-days",
            "30",
        ),
        OPERATOR_PASSWORD,
    )
    assert code == 0, err
    plaintext = out.strip().splitlines()[-1]
    key_id = out.split()[2]
    assert plaintext.startswith("kvk_") and out.count(plaintext) == 1
    assert probe(client, "partner-a", f"Bearer {plaintext}").status_code == 200
    code, listing, _ = run_cli(operator("key", "list"), OPERATOR_PASSWORD)
    assert code == 0 and key_id in listing and plaintext not in listing
    assert f"{key_id}  active" in listing
    code, rotated, _ = run_cli(operator("key", "rotate", "--key-id", key_id), OPERATOR_PASSWORD)
    new_plaintext = rotated.strip().splitlines()[-1]
    assert code == 0 and new_plaintext != plaintext
    assert probe(client, "partner-a", f"Bearer {plaintext}").status_code == 401
    new_id = rotated.split("Created key ")[1].split()[0]
    code, _, _ = run_cli(operator("key", "revoke", "--key-id", new_id), OPERATOR_PASSWORD)
    assert code == 0
    assert probe(client, "partner-a", f"Bearer {new_plaintext}").status_code == 401
    code, _, err = run_cli(operator("key", "revoke", "--key-id", new_id), OPERATOR_PASSWORD)
    assert code == 1 and "already revoked" in err


# --- retention ----------------------------------------------------------------------------

CUTOFF = datetime(2001, 1, 1, 12, 0, tzinfo=UTC)
JUST_BEFORE = CUTOFF - timedelta(microseconds=1)
JUST_AFTER = CUTOFF + timedelta(microseconds=1)


@pytest.fixture
def expiring_rows(
    migrated_schema: None, migration_engine: Engine, make_user: Callable[..., Account]
) -> Iterator[dict[str, Any]]:
    """Rows on both sides of CUTOFF (far in the past, so other tests' rows are untouched)."""
    analyst = make_user()
    ids: dict[str, Any] = {"analyst": analyst.id}
    with migration_engine.begin() as connection:
        for label, expiry in (
            ("expired", JUST_BEFORE),
            ("at_cutoff", CUTOFF),
            ("kept", JUST_AFTER),
        ):
            event_id = rows.add(connection, Event, rows.event("sms", expires_at=expiry))
            incident_id = rows.add(connection, Incident, rows.incident(expires_at=expiry))
            rows.add(
                connection,
                IncidentEvent,
                {"incident_id": incident_id, "event_id": event_id, "channel": "sms"},
            )
            rows.add(connection, Assessment, rows.assessment(incident_id))
            review_id = rows.add(connection, Review, rows.review(incident_id, analyst.id))
            connection.execute(
                update(Incident)
                .where(Incident.id == incident_id)
                .values(latest_review_id=review_id)
            )
            ids[f"{label}_event"], ids[f"{label}_incident"] = event_id, incident_id
            ids[f"{label}_audit"] = rows.add(
                connection,
                AuditRecord,
                rows.audit(actor_kind="user", actor_user_id=analyst.id, expires_at=expiry),
            )
        # An expired event still linked to a live incident must survive.
        ids["linked_event"] = rows.add(
            connection, Event, rows.event("call", expires_at=JUST_BEFORE)
        )
        live = rows.add(
            connection, Incident, rows.incident(expires_at=JUST_AFTER + timedelta(days=1))
        )
        rows.add(
            connection,
            IncidentEvent,
            {"incident_id": live, "event_id": ids["linked_event"], "channel": "call"},
        )
        rows.add(connection, Assessment, rows.assessment(live))
        ids["live_incident"] = live
        far = datetime(2001, 1, 2, tzinfo=UTC)
        for label, values in (
            ("expired_session", {"expires_at": JUST_BEFORE}),
            ("revoked_session", {"expires_at": far, "revoked_at": JUST_BEFORE}),
            ("kept_session", {"expires_at": JUST_AFTER}),
        ):
            ids[label] = rows.add(
                connection,
                UserSession,
                rows.user_session(analyst.id, created_at=CUTOFF - timedelta(hours=1), **values),
            )
    yield ids
    # Everything this fixture created expires in early 2001; remove whatever is left of it.
    early = datetime(2001, 1, 3, tzinfo=UTC)
    with migration_engine.begin() as connection:
        connection.execute(delete(Incident).where(Incident.expires_at <= early))
        connection.execute(delete(Event).where(Event.expires_at <= early))
        connection.execute(delete(AuditRecord).where(AuditRecord.expires_at <= early))
        connection.execute(delete(UserSession).where(UserSession.user_id == analyst.id))


def counts_by_id(engine: Engine, ids: dict[str, Any]) -> dict[str, int]:
    tables = {
        "event": Event,
        "incident": Incident,
        "audit": AuditRecord,
        "session": UserSession,
    }
    result: dict[str, int] = {}
    with engine.connect() as connection:
        for label, value in ids.items():
            model = next((m for suffix, m in tables.items() if label.endswith(suffix)), None)
            if model is not None:
                result[label] = connection.execute(
                    select(func.count()).select_from(model).where(model.id == value)
                ).scalar_one()
    return result


def expected_deleted(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            "incidents": connection.execute(
                select(func.count()).select_from(Incident).where(Incident.expires_at <= CUTOFF)
            ).scalar_one(),
            "audit_records": connection.execute(
                select(func.count())
                .select_from(AuditRecord)
                .where(AuditRecord.expires_at <= CUTOFF)
            ).scalar_one(),
        }


def test_retention_dry_run_is_exact_and_changes_nothing(
    expiring_rows: dict[str, Any], retention_engine: Engine, migration_engine: Engine
) -> None:
    before = counts_by_id(migration_engine, expiring_rows)
    expected = expected_deleted(migration_engine)
    report = run_retention(
        retention_engine, confirm_database="kavach_test", as_of=CUTOFF, dry_run=True
    )
    assert report.dry_run and report.database == "kavach_test"
    assert report.deleted["incidents"] == expected["incidents"] >= 2
    assert report.deleted["audit_records"] == expected["audit_records"] >= 2
    assert report.deleted["events"] >= 2 and report.deleted["sessions"] >= 2
    assert counts_by_id(migration_engine, expiring_rows) == before


def test_retention_deletes_at_or_before_the_cutoff_in_dependency_order(
    expiring_rows: dict[str, Any], retention_engine: Engine, migration_engine: Engine
) -> None:
    run_retention(
        retention_engine, confirm_database="kavach_test", as_of=CUTOFF, dry_run=False, batch_size=1
    )
    remaining = counts_by_id(migration_engine, expiring_rows)
    for label in ("expired", "at_cutoff"):
        assert remaining[f"{label}_incident"] == 0
        assert remaining[f"{label}_event"] == 0
        assert remaining[f"{label}_audit"] == 0
    assert remaining["kept_incident"] == remaining["kept_event"] == remaining["kept_audit"] == 1
    assert remaining["linked_event"] == 1 and remaining["live_incident"] == 1
    assert remaining["expired_session"] == remaining["revoked_session"] == 0
    assert remaining["kept_session"] == 1
    with migration_engine.connect() as connection:
        for incident in ("expired_incident", "at_cutoff_incident"):
            for model, column in (
                (Assessment, Assessment.incident_id),
                (Review, Review.incident_id),
            ):
                assert (
                    connection.execute(
                        select(func.count())
                        .select_from(model)
                        .where(column == expiring_rows[incident])
                    ).scalar_one()
                    == 0
                )
        # Users referenced by audit rows and reviews are never deleted by retention.
        assert (
            connection.execute(
                select(func.count()).select_from(User).where(User.id == expiring_rows["analyst"])
            ).scalar_one()
            == 1
        )


def test_retention_is_refused_for_unnamed_or_mismatched_databases(
    retention_engine: Engine,
) -> None:
    with pytest.raises(RetentionRefused):
        run_retention(retention_engine, confirm_database="kavach_dev", as_of=CUTOFF, dry_run=False)
    with pytest.raises(RetentionRefused):
        run_retention(retention_engine, confirm_database="kavach_dev", as_of=CUTOFF, dry_run=True)


def test_retention_role_cannot_touch_users_keys_or_append_only_rows(
    retention_engine: Engine,
) -> None:
    for statement in (
        "DELETE FROM users",
        "DELETE FROM ingest_keys",
        "DELETE FROM reviews",
        "UPDATE audit_records SET expires_at = now()",
        "INSERT INTO sessions (user_id) VALUES (gen_random_uuid())",
    ):
        with retention_engine.connect() as connection:
            with pytest.raises(Exception, match="permission denied"):
                connection.execute(text(statement))


def test_cli_retention_run_is_audited_only_when_destructive(
    run_cli: Callable[..., Any],
    expiring_rows: dict[str, Any],
    operator_id: UUID,
    migration_engine: Engine,
) -> None:
    def retention_audits() -> int:
        return scalar(
            migration_engine,
            select(func.count())
            .select_from(AuditRecord)
            .where(AuditRecord.action == "retention.run"),
        )

    before = retention_audits()
    base = operator("retention", "run", "--database", "kavach_test", "--as-of", CUTOFF.isoformat())
    code, out, err = run_cli([*base, "--dry-run"], OPERATOR_PASSWORD)
    assert code == 0, err
    assert "would delete (dry run, rolled back)" in out
    assert retention_audits() == before
    code, out, err = run_cli(base, OPERATOR_PASSWORD)
    assert code == 0, err
    assert "incidents: deleted" in out
    assert retention_audits() == before + 1
    code, _, err = run_cli(
        operator("retention", "run", "--database", "kavach_test", "--as-of", "2001-01-01"),
        OPERATOR_PASSWORD,
    )
    assert code == 1 and "timezone" in err


def test_audit_rows_reference_existing_actors(migration_engine: Engine) -> None:
    # Retention never deletes users or keys, so every audit actor reference still resolves.
    with migration_engine.connect() as connection:
        dangling = connection.execute(
            select(func.count())
            .select_from(AuditRecord)
            .where(
                AuditRecord.actor_user_id.is_not(None),
                ~select(User.id).where(User.id == AuditRecord.actor_user_id).exists(),
            )
        ).scalar_one()
    assert dangling == 0
