"""Least-privilege grants for the runtime and retention roles (DATABASE.md, M2.2)."""

from collections.abc import Iterator
from uuid import UUID

import pytest
from psycopg import errors as pg_errors
from sqlalchemy import Connection, Engine, func, select, text, update
from sqlalchemy.exc import ProgrammingError

from kavach.db.models import (
    Assessment,
    AuditRecord,
    Base,
    Event,
    Incident,
    IncidentEvent,
    Review,
    User,
)

from . import schema_rows as rows
from .conftest import rolled_back
from .schema_rows import add

pytestmark = pytest.mark.integration

APPEND_ONLY = {"events", "incident_events", "assessments", "reviews", "audit_records"}
RUNTIME_UPDATABLE = {
    "users": {"display_name", "password_hash", "role", "is_active"},
    "sessions": {"last_seen_at", "revoked_at"},
    "ingest_keys": {"revoked_at"},
    "incidents": {"current_revision", "latest_review_id", "version", "updated_at"},
}
RETENTION_DELETABLE = {"sessions", "incidents", "events", "audit_records"}
RETENTION_READABLE = {
    "sessions": {"id", "expires_at", "revoked_at"},
    "incidents": {"id", "expires_at"},
    "events": {"id", "expires_at"},
    "audit_records": {"id", "expires_at"},
    "incident_events": {"event_id"},
}


def table_privilege(connection: Connection, role: str, table: str, privilege: str) -> bool:
    return connection.execute(
        text("SELECT has_table_privilege(:role, :table, :privilege)"),
        {"role": role, "table": table, "privilege": privilege},
    ).scalar_one()


def column_privilege(
    connection: Connection, role: str, table: str, column: str, privilege: str
) -> bool:
    return connection.execute(
        text("SELECT has_column_privilege(:role, :table, :column, :privilege)"),
        {"role": role, "table": table, "column": column, "privilege": privilege},
    ).scalar_one()


@pytest.mark.parametrize("table", sorted(Base.metadata.tables))
def test_runtime_privileges_per_table(owner_tx: Connection, table: str) -> None:
    role = "kavach_app"
    assert table_privilege(owner_tx, role, table, "SELECT")
    assert table_privilege(owner_tx, role, table, "INSERT")
    for privilege in ("UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        assert not table_privilege(owner_tx, role, table, privilege), privilege
    updatable = {
        column.name
        for column in Base.metadata.tables[table].columns
        if column_privilege(owner_tx, role, table, column.name, "UPDATE")
    }
    assert updatable == RUNTIME_UPDATABLE.get(table, set())
    if table in APPEND_ONLY:
        assert updatable == set()


@pytest.mark.parametrize("table", sorted(Base.metadata.tables))
def test_retention_privileges_per_table(owner_tx: Connection, table: str) -> None:
    role = "kavach_retention"
    assert table_privilege(owner_tx, role, table, "DELETE") == (table in RETENTION_DELETABLE)
    for privilege in ("SELECT", "INSERT", "UPDATE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        assert not table_privilege(owner_tx, role, table, privilege), privilege
    columns = Base.metadata.tables[table].columns
    readable = {
        c.name for c in columns if column_privilege(owner_tx, role, table, c.name, "SELECT")
    }
    writable = {
        c.name
        for c in columns
        for privilege in ("INSERT", "UPDATE")
        if column_privilege(owner_tx, role, table, c.name, privilege)
    }
    assert readable == RETENTION_READABLE.get(table, set())
    assert writable == set()


@pytest.mark.parametrize("role", ["kavach_app", "kavach_retention"])
def test_application_roles_cannot_change_the_schema(owner_tx: Connection, role: str) -> None:
    for privilege in ("CREATE", "USAGE"):
        allowed = owner_tx.execute(
            text("SELECT has_schema_privilege(:role, 'public', :privilege)"),
            {"role": role, "privilege": privilege},
        ).scalar_one()
        assert allowed is (privilege == "USAGE")
    assert not table_privilege(owner_tx, role, "alembic_version", "SELECT")


def assert_denied(connection: Connection, statement: str) -> None:
    with pytest.raises(ProgrammingError) as error:
        connection.execute(text(statement))
    assert isinstance(error.value.orig, pg_errors.InsufficientPrivilege), statement


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE reviews SET note = 'rewritten'",
        "UPDATE assessments SET tier = 'low'",
        "UPDATE audit_records SET outcome = 'denied'",
        "UPDATE events SET processing_ms = 1",
        "UPDATE incident_events SET channel = 'call'",
        "UPDATE users SET username = 'renamed'",
        "UPDATE incidents SET occurred_at = now()",
        "UPDATE ingest_keys SET source = 'other'",
        "DELETE FROM reviews",
        "DELETE FROM users",
        "DELETE FROM audit_records",
        "DELETE FROM sessions",
        "TRUNCATE events CASCADE",
        "ALTER TABLE users ADD COLUMN extra integer",
        "DROP TABLE events",
        "CREATE INDEX runtime_index ON events (source)",
        "SELECT version_num FROM alembic_version",
    ],
)
def test_runtime_role_is_denied(runtime_tx: Connection, statement: str) -> None:
    assert_denied(runtime_tx, statement)


@pytest.fixture
def retention_tx(migrated_schema: None, retention_engine: Engine) -> Iterator[Connection]:
    yield from rolled_back(retention_engine)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT password_hash FROM users",
        "SELECT note FROM reviews",
        "SELECT signals FROM events",
        "SELECT subscriber_digest FROM events",
        "UPDATE sessions SET revoked_at = now()",
        "INSERT INTO audit_records (actor_kind) VALUES ('system')",
        "DELETE FROM reviews",
        "DELETE FROM users",
        "DELETE FROM assessments",
    ],
)
def test_retention_role_is_denied(retention_tx: Connection, statement: str) -> None:
    assert_denied(retention_tx, statement)


@pytest.fixture
def committed_incident(
    migrated_schema: None, runtime_engine: Engine, migration_engine: Engine
) -> Iterator[dict[str, UUID]]:
    """Write a reviewed incident as the runtime role and commit it; the owner cleans up."""
    with runtime_engine.connect() as connection, connection.begin():
        analyst = add(connection, User, rows.user(role="analyst"))
        incident_id, event_id = rows.standalone_incident(connection)
        review_id = add(connection, Review, rows.review(incident_id, analyst))
        connection.execute(
            update(Incident)
            .where(Incident.id == incident_id)
            .values(latest_review_id=review_id, version=2, updated_at=func.now())
        )
        audit_id = add(
            connection,
            AuditRecord,
            rows.audit(actor_kind="user", actor_user_id=analyst, resource_id=review_id),
        )
    ids = {"incident": incident_id, "event": event_id, "analyst": analyst, "audit": audit_id}
    yield ids
    with migration_engine.connect() as connection, connection.begin():
        for statement, key in (
            ("DELETE FROM incidents WHERE id = :id", "incident"),
            ("DELETE FROM events WHERE id = :id", "event"),
            ("DELETE FROM audit_records WHERE id = :id", "audit"),
            ("DELETE FROM users WHERE id = :id", "analyst"),
        ):
            connection.execute(text(statement), {"id": ids[key]})


def test_runtime_role_can_write_the_documented_incident_path(
    committed_incident: dict[str, UUID], migration_engine: Engine
) -> None:
    with migration_engine.connect() as connection:
        version, latest = connection.execute(
            select(Incident.version, Incident.latest_review_id).where(
                Incident.id == committed_incident["incident"]
            )
        ).one()
    assert version == 2
    assert latest is not None


def test_retention_role_deletes_an_expired_incident_graph(
    committed_incident: dict[str, UUID], retention_engine: Engine, migration_engine: Engine
) -> None:
    incident_id, event_id = committed_incident["incident"], committed_incident["event"]
    with retention_engine.connect() as connection, connection.begin():
        # Same shape as the future cleanup job: incidents first, then unreferenced events.
        connection.execute(text("DELETE FROM incidents WHERE id = :id"), {"id": incident_id})
        connection.execute(
            text(
                "DELETE FROM events WHERE id = :id AND NOT EXISTS"
                " (SELECT 1 FROM incident_events WHERE event_id = events.id)"
            ),
            {"id": event_id},
        )
    with migration_engine.connect() as connection:
        for model, column, value in (
            (Incident, Incident.id, incident_id),
            (IncidentEvent, IncidentEvent.incident_id, incident_id),
            (Assessment, Assessment.incident_id, incident_id),
            (Review, Review.incident_id, incident_id),
            (Event, Event.id, event_id),
        ):
            remaining = connection.execute(
                select(func.count()).select_from(model).where(column == value)
            ).scalar_one()
            assert remaining == 0, model.__tablename__
