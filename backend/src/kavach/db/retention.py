"""Operator-triggered expiry cleanup (DATABASE.md "Retention, migration and recovery", D07).

Runs as the kavach_retention role, which (since revision 0002) can only call the
`kavach_retention_purge` procedure: one batch of deletions of *expired* rows, with a cutoff
that the database refuses if it lies in the future. The order is expired incidents (links,
assessments and reviews cascade), events no longer linked to any incident, audit records,
then expired or revoked sessions. Users and ingestion keys are never deleted. A row is removed
when its `expires_at` (or a session's `revoked_at`) is at or before the cutoff.

Each batch commits separately. A dry run executes the same batches in one transaction, checks
the deferred constraints, and rolls back, so its counts are exact and nothing changes.
Destructive runs are refused unless the caller names the connected database and that database
is a disposable `*_test` database; any database may be dry-run.

`run_audited_retention` brackets a destructive run with audit records written through the
runtime role *before* the first deletion and after the last, so a run can never delete without
a prior record; an interrupted run leaves a `retention.start` without a `retention.complete`.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

DEFAULT_BATCH_SIZE = 500
MAX_BATCH_SIZE = 10_000
TARGETS = ("incidents", "events", "audit_records", "sessions")
PURGE = text("SELECT kavach_retention_purge(:target, :as_of, :limit)")
INVALID_PARAMETER = "22023"


class RetentionRefused(Exception):
    """The run was refused before anything was deleted; the message is safe to show."""


@dataclass
class RetentionReport:
    database: str
    as_of: datetime
    dry_run: bool
    run_id: UUID = field(default_factory=uuid4)
    deleted: dict[str, int] = field(default_factory=dict)


def check_target(database: str, confirm_database: str, *, dry_run: bool) -> None:
    if confirm_database != database:
        raise RetentionRefused("The named database does not match the connected database")
    if not dry_run and not database.endswith("_test"):
        raise RetentionRefused(
            "Destructive cleanup is limited to disposable *_test databases in this phase;"
            " use --dry-run elsewhere"
        )


def purge_batch(connection: Connection, target: str, as_of: datetime, batch_size: int) -> int:
    try:
        return connection.execute(
            PURGE, {"target": target, "as_of": as_of, "limit": batch_size}
        ).scalar_one()
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) == INVALID_PARAMETER:
            raise RetentionRefused("The database refused the retention cutoff or batch") from None
        raise


def prepare(
    engine: Engine, confirm_database: str, as_of: datetime | None, batch_size: int, dry_run: bool
) -> RetentionReport:
    if as_of is not None and as_of.tzinfo is None:
        raise RetentionRefused("The cutoff must include a timezone")
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise RetentionRefused(f"Batch size must be between 1 and {MAX_BATCH_SIZE}")
    with engine.connect() as connection:
        database, database_now = connection.execute(text("SELECT current_database(), now()")).one()
    check_target(database, confirm_database, dry_run=dry_run)
    # The database clock is authoritative; expiry can never be brought forward.
    if as_of is not None and as_of > database_now:
        raise RetentionRefused("The cutoff must not be later than the database's current time")
    return RetentionReport(database=database, as_of=as_of or database_now, dry_run=dry_run)


def execute(engine: Engine, report: RetentionReport, batch_size: int) -> RetentionReport:
    if report.dry_run:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                for target in TARGETS:
                    total = 0
                    while (n := purge_batch(connection, target, report.as_of, batch_size)) > 0:
                        total += n
                        if n < batch_size:
                            break
                    report.deleted[target] = total
                connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            finally:
                transaction.rollback()
        return report

    for target in TARGETS:
        total = 0
        while True:
            with engine.begin() as connection:
                deleted = purge_batch(connection, target, report.as_of, batch_size)
            total += deleted
            if deleted < batch_size:
                break
        report.deleted[target] = total
    return report


def run_retention(
    engine: Engine,
    *,
    confirm_database: str,
    as_of: datetime | None = None,
    dry_run: bool,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> RetentionReport:
    report = prepare(engine, confirm_database, as_of, batch_size, dry_run)
    return execute(engine, report, batch_size)


def run_audited_retention(
    engine: Engine,
    *,
    record: Callable[[str, UUID], None],
    confirm_database: str,
    as_of: datetime | None = None,
    dry_run: bool,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> RetentionReport:
    """Like run_retention, but a destructive run is recorded before it deletes anything.

    `record(action, run_id)` must commit an audit record; if it fails, nothing is deleted.
    """
    report = prepare(engine, confirm_database, as_of, batch_size, dry_run)
    if not report.dry_run:
        record("retention.start", report.run_id)
    execute(engine, report, batch_size)
    if not report.dry_run:
        record("retention.complete", report.run_id)
    return report
