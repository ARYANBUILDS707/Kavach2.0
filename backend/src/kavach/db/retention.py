"""Operator-triggered expiry cleanup (DATABASE.md "Retention, migration and recovery", D07).

Runs as the kavach_retention role, whose grants allow only reading expiry columns and deleting
from incidents, events, audit_records and sessions. Users and ingestion keys are never deleted.

Order: expired incidents (links, assessments and reviews cascade), then expired events no
longer linked to any incident, then expired audit records, then expired or revoked sessions.
A row is removed when its `expires_at` (or a session's `revoked_at`) is at or before `as_of`.
Each batch commits separately. A dry run executes the same batches in one transaction, checks
the deferred constraints, and rolls back, so its counts are exact and nothing changes.

Destructive runs are refused unless the caller names the connected database and that
database is a disposable `*_test` database; any database may be dry-run.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Connection, Engine, text

DEFAULT_BATCH_SIZE = 500
MAX_BATCH_SIZE = 10_000

BATCHES = {
    "incidents": """
        DELETE FROM incidents WHERE id IN (
            SELECT id FROM incidents WHERE expires_at <= :as_of
            ORDER BY expires_at, id LIMIT :limit)
    """,
    "events": """
        DELETE FROM events WHERE id IN (
            SELECT candidate.id FROM events AS candidate
            WHERE candidate.expires_at <= :as_of
              AND NOT EXISTS (
                  SELECT 1 FROM incident_events AS link WHERE link.event_id = candidate.id)
            ORDER BY candidate.expires_at, candidate.id LIMIT :limit)
    """,
    "audit_records": """
        DELETE FROM audit_records WHERE id IN (
            SELECT id FROM audit_records WHERE expires_at <= :as_of
            ORDER BY expires_at, id LIMIT :limit)
    """,
    "sessions": """
        DELETE FROM sessions WHERE id IN (
            SELECT id FROM sessions WHERE expires_at <= :as_of OR revoked_at <= :as_of
            ORDER BY id LIMIT :limit)
    """,
}


class RetentionRefused(Exception):
    """The run was refused before anything was deleted; the message is safe to show."""


@dataclass
class RetentionReport:
    database: str
    as_of: datetime
    dry_run: bool
    deleted: dict[str, int] = field(default_factory=dict)


def connected_database(connection: Connection) -> str:
    return connection.execute(text("SELECT current_database()")).scalar_one()


def check_target(database: str, confirm_database: str, *, dry_run: bool) -> None:
    if confirm_database != database:
        raise RetentionRefused("The named database does not match the connected database")
    if not dry_run and not database.endswith("_test"):
        raise RetentionRefused(
            "Destructive cleanup is limited to disposable *_test databases in this phase;"
            " use --dry-run elsewhere"
        )


def drain(connection: Connection, statement: str, as_of: datetime, batch_size: int) -> int:
    total = 0
    while True:
        deleted = connection.execute(text(statement), {"as_of": as_of, "limit": batch_size})
        total += deleted.rowcount
        if deleted.rowcount < batch_size:
            return total


def run_retention(
    engine: Engine,
    *,
    confirm_database: str,
    as_of: datetime,
    dry_run: bool,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> RetentionReport:
    if as_of.tzinfo is None:
        raise RetentionRefused("The cutoff must include a timezone")
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise RetentionRefused(f"Batch size must be between 1 and {MAX_BATCH_SIZE}")
    with engine.connect() as connection:
        database = connected_database(connection)
    check_target(database, confirm_database, dry_run=dry_run)
    report = RetentionReport(database=database, as_of=as_of, dry_run=dry_run)

    if dry_run:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                for table, statement in BATCHES.items():
                    report.deleted[table] = drain(connection, statement, as_of, batch_size)
                connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            finally:
                transaction.rollback()
        return report

    for table, statement in BATCHES.items():
        total = 0
        while True:
            with engine.begin() as connection:
                deleted = connection.execute(
                    text(statement), {"as_of": as_of, "limit": batch_size}
                ).rowcount
            total += deleted
            if deleted < batch_size:
                break
        report.deleted[table] = total
    return report
