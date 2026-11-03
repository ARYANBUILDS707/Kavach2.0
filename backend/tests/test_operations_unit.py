"""Service-free M2.4 checks: API key format and scope, CLI argument safety, retention guards."""

import io
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr

from kavach.auth.dependencies import require_source
from kavach.auth.ingest_keys import IngestPrincipal, new_ingest_key
from kavach.cli import build_parser, key_status, main
from kavach.core.config import Settings
from kavach.core.errors import ApiError
from kavach.db.engine import create_db_engine
from kavach.db.retention import RetentionRefused, check_target, run_retention


def test_ingest_keys_are_prefixed_random_and_unique() -> None:
    first, second = new_ingest_key(), new_ingest_key()
    assert first.startswith("kvk_") and len(first) == 47
    assert first != second


def test_a_key_only_acts_for_its_own_source() -> None:
    principal = IngestPrincipal(key_id=uuid4(), source="simulator")
    require_source(principal, "simulator")
    for other in ("Simulator", "simulator2", "partner-a", ""):
        with pytest.raises(ApiError) as error:
            require_source(principal, other)
        assert (error.value.status, error.value.code) == (403, "FORBIDDEN")


@pytest.mark.parametrize(
    "argv",
    [
        [
            "user",
            "create",
            "--username",
            "a",
            "--display-name",
            "A",
            "--role",
            "viewer",
            "--actor",
            "root",
            "--password",
            "secret-on-argv",
        ],
        ["user", "reset-password", "--username", "a", "--actor", "root", "--new-password", "x"],
        ["key", "create", "--name", "n", "--source", "s", "--actor", "root", "--key", "kvk_x"],
        ["user", "create", "--username", "a", "--display-name", "A", "--role", "viewer"],
        ["user", "create", "--username", "a", "--display-name", "A", "--actor", "r", "--bootstrap"],
        ["user", "deactivate", "--username", "a"],
    ],
)
def test_cli_never_accepts_secrets_or_missing_actors_as_arguments(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        build_parser().parse_args(argv)
    assert exit_.value.code == 2


def test_key_status_reporting() -> None:
    now = datetime(2026, 11, 3, tzinfo=UTC)
    assert key_status(datetime(2026, 12, 1, tzinfo=UTC), None, now) == "active"
    assert key_status(now, None, now) == "expired"
    assert key_status(datetime(2026, 12, 1, tzinfo=UTC), now, now) == "revoked"


@pytest.mark.parametrize("database", ["kavach_dev", "kavach", "production", "kavach_test_copy"])
def test_destructive_retention_is_limited_to_test_databases(database: str) -> None:
    with pytest.raises(RetentionRefused):
        check_target(database, database, dry_run=False)
    check_target(database, database, dry_run=True)


def test_retention_requires_naming_the_connected_database() -> None:
    with pytest.raises(RetentionRefused):
        check_target("kavach_test", "kavach_dev", dry_run=True)
    check_target("kavach_test", "kavach_test", dry_run=False)


@pytest.mark.parametrize(
    ("as_of", "batch_size"),
    [
        (datetime(2026, 11, 3), 500),
        (datetime(2026, 11, 3, tzinfo=UTC), 0),
        (datetime(2026, 11, 3, tzinfo=UTC), 10_001),
    ],
)
def test_retention_rejects_naive_cutoffs_and_bad_batches_before_connecting(
    as_of: datetime, batch_size: int
) -> None:
    # Points at a closed port: the guard must refuse before any connection is attempted.
    engine = create_db_engine(SecretStr("postgresql+psycopg://x:y@127.0.0.1:1/kavach_test"))
    try:
        with pytest.raises(RetentionRefused):
            run_retention(
                engine,
                confirm_database="kavach_test",
                as_of=as_of,
                dry_run=True,
                batch_size=batch_size,
            )
    finally:
        engine.dispose()


def test_cli_reports_missing_database_configuration() -> None:
    err = io.StringIO()
    code = main(["key", "list", "--actor", "root"], err=err, settings=Settings(app_env="test"))
    assert code == 2
    assert "DATABASE_URL" in err.getvalue()
