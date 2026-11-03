"""KAVACH operator commands (M2.4).

    python -m kavach.cli user create --username U --display-name D --role R --actor ADMIN
    python -m kavach.cli user create --username U --display-name D --bootstrap
    python -m kavach.cli user deactivate --username U --actor ADMIN
    python -m kavach.cli user reset-password --username U --actor ADMIN
    python -m kavach.cli user set-role --username U --role R --actor ADMIN
    python -m kavach.cli key create --name N --source S [--expires-in-days 90] --actor ADMIN
    python -m kavach.cli key rotate --key-id ID [--expires-in-days 90] --actor ADMIN
    python -m kavach.cli key revoke --key-id ID --actor ADMIN
    python -m kavach.cli key list --actor ADMIN
    python -m kavach.cli retention run --database DB [--dry-run] [--as-of ISO] --actor ADMIN

Every state-changing command authenticates `--actor` as an active admin first; the only
exception is `user create --bootstrap`, which creates the first admin and is refused once an
active admin exists. Secrets are never accepted as arguments. They are prompted for, or, with
`--stdin`, read one per line in this order: the actor's password (when --actor is used), then
the new password (user create and user reset-password). A new API key is printed exactly once.

Needs the authentication configuration from .env.example (DATABASE_URL with the runtime role,
AUDIT_HMAC_KEYS, ...); `retention run` also needs RETENTION_DATABASE_URL.
"""

import argparse
import getpass
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TextIO
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from kavach.auth.accounts import ROLES, AccountError, AccountService
from kavach.auth.ingest_keys import IngestKeyService
from kavach.auth.passwords import PasswordService
from kavach.core.clock import Clock, utc_now
from kavach.core.config import Settings, parse_audit_keys
from kavach.db.engine import create_db_engine, create_session_factory
from kavach.db.retention import DEFAULT_BATCH_SIZE, RetentionRefused, run_retention
from kavach.privacy.audit import AuditWriter


class SecretInput:
    def __init__(self, from_stdin: bool, stdin: TextIO) -> None:
        self.from_stdin = from_stdin
        self.stdin = stdin

    def read(self, prompt: str, *, confirm: bool = False) -> str:
        if self.from_stdin:
            line = self.stdin.readline()
            if not line:
                raise AccountError("Expected another secret on standard input")
            return line.rstrip("\n")
        value = getpass.getpass(prompt)
        if confirm and value != getpass.getpass("Repeat: "):
            raise AccountError("The two entries did not match")
        return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m kavach.cli", description=__doc__.split("\n")[0]
    )
    groups = parser.add_subparsers(dest="group", required=True)

    def command(
        group: "argparse._SubParsersAction[argparse.ArgumentParser]", name: str, actor: bool = True
    ) -> argparse.ArgumentParser:
        sub = group.add_parser(name)
        if actor:
            sub.add_argument("--actor", required=True, help="username of an active admin")
        sub.add_argument("--stdin", action="store_true", help="read secrets from stdin lines")
        return sub

    users = groups.add_parser("user").add_subparsers(dest="action", required=True)
    create = command(users, "create", actor=False)
    create.add_argument("--username", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument("--role", choices=ROLES)
    who = create.add_mutually_exclusive_group(required=True)
    who.add_argument("--actor", help="username of an active admin")
    who.add_argument("--bootstrap", action="store_true", help="create the first admin")
    command(users, "deactivate").add_argument("--username", required=True)
    command(users, "reset-password").add_argument("--username", required=True)
    set_role = command(users, "set-role")
    set_role.add_argument("--username", required=True)
    set_role.add_argument("--role", required=True, choices=ROLES)

    keys = groups.add_parser("key").add_subparsers(dest="action", required=True)
    key_create = command(keys, "create")
    key_create.add_argument("--name", required=True)
    key_create.add_argument("--source", required=True)
    key_create.add_argument("--expires-in-days", type=int, default=90)
    key_rotate = command(keys, "rotate")
    key_rotate.add_argument("--key-id", required=True, type=UUID)
    key_rotate.add_argument("--expires-in-days", type=int, default=90)
    command(keys, "revoke").add_argument("--key-id", required=True, type=UUID)
    command(keys, "list")

    retention = groups.add_parser("retention").add_subparsers(dest="action", required=True)
    run = command(retention, "run")
    run.add_argument("--database", required=True, help="must equal the connected database")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--as-of", help="ISO 8601 cutoff with timezone (default: now)")
    run.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    return parser


def key_status(expires_at: datetime, revoked_at: datetime | None, now: datetime) -> str:
    if revoked_at is not None:
        return "revoked"
    return "expired" if now >= expires_at else "active"


class Operator:
    def __init__(self, settings: Settings, engine: Engine, clock: Clock, out: TextIO) -> None:
        if settings.audit_hmac_keys is None or settings.audit_hmac_active_version is None:
            raise AccountError("The authentication configuration (see .env.example) is required")
        self.settings = settings
        self.clock = clock
        self.out = out
        self.sessions: sessionmaker[Session] = create_session_factory(engine)
        self.audit = AuditWriter(
            parse_audit_keys(settings.audit_hmac_keys),
            settings.audit_hmac_active_version,
            timedelta(days=settings.audit_retention_days),
        )
        self.accounts = AccountService(
            sessions=self.sessions, passwords=PasswordService(), audit=self.audit, clock=clock
        )
        self.keys = IngestKeyService(sessions=self.sessions, audit=self.audit, clock=clock)

    def run(self, args: argparse.Namespace, secrets: SecretInput) -> None:
        if args.group == "user" and args.action == "create" and args.bootstrap:
            password = secrets.read("New admin password: ", confirm=True)
            user_id = self.accounts.bootstrap_admin(
                username=args.username, display_name=args.display_name, password=password
            )
            print(f"Bootstrapped admin {user_id}", file=self.out)
            return
        actor = self.accounts.authenticate_operator(
            args.actor, secrets.read(f"Password for operator {args.actor}: ")
        )
        handler = getattr(self, f"{args.group}_{args.action.replace('-', '_')}")
        handler(args, actor, secrets)

    def user_create(self, args: argparse.Namespace, actor: UUID, secrets: SecretInput) -> None:
        if args.role is None:
            raise AccountError("--role is required unless --bootstrap is used")
        password = secrets.read("New user's password: ", confirm=True)
        user_id = self.accounts.provision_user(
            actor_id=actor,
            username=args.username,
            display_name=args.display_name,
            role=args.role,
            password=password,
        )
        print(f"Provisioned user {user_id}", file=self.out)

    def user_deactivate(self, args: argparse.Namespace, actor: UUID, secrets: SecretInput) -> None:
        user_id = self.accounts.deactivate_user(actor_id=actor, username=args.username)
        print(f"Deactivated user {user_id}; their sessions are revoked", file=self.out)

    def user_reset_password(
        self, args: argparse.Namespace, actor: UUID, secrets: SecretInput
    ) -> None:
        password = secrets.read("New password: ", confirm=True)
        user_id = self.accounts.reset_password(
            actor_id=actor, username=args.username, new_password=password
        )
        print(f"Reset the password of user {user_id}; their sessions are revoked", file=self.out)

    def user_set_role(self, args: argparse.Namespace, actor: UUID, secrets: SecretInput) -> None:
        user_id = self.accounts.change_role(actor_id=actor, username=args.username, role=args.role)
        print(f"Changed the role of user {user_id} to {args.role}", file=self.out)

    def key_create(self, args: argparse.Namespace, actor: UUID, secrets: SecretInput) -> None:
        issued = self.keys.create(
            actor_id=actor,
            name=args.name,
            source=args.source,
            lifetime=timedelta(days=args.expires_in_days),
        )
        self._print_key(issued.key_id, issued.source, issued.expires_at, issued.plaintext)

    def key_rotate(self, args: argparse.Namespace, actor: UUID, secrets: SecretInput) -> None:
        issued = self.keys.rotate(
            actor_id=actor, key_id=args.key_id, lifetime=timedelta(days=args.expires_in_days)
        )
        print(f"Revoked key {args.key_id}", file=self.out)
        self._print_key(issued.key_id, issued.source, issued.expires_at, issued.plaintext)

    def key_revoke(self, args: argparse.Namespace, actor: UUID, secrets: SecretInput) -> None:
        self.keys.revoke(actor_id=actor, key_id=args.key_id)
        print(f"Revoked key {args.key_id}", file=self.out)

    def key_list(self, args: argparse.Namespace, actor: UUID, secrets: SecretInput) -> None:
        now = self.clock()
        for key in self.keys.list_keys(actor_id=actor):
            status = key_status(key.expires_at, key.revoked_at, now)
            print(
                f"{key.id}  {status:<7}  source={key.source}  expires={key.expires_at.isoformat()}"
                f"  name={key.name}",
                file=self.out,
            )

    def retention_run(self, args: argparse.Namespace, actor: UUID, secrets: SecretInput) -> None:
        if self.settings.retention_database_url is None:
            raise AccountError("RETENTION_DATABASE_URL is required for retention runs")
        try:
            as_of = datetime.fromisoformat(args.as_of) if args.as_of else self.clock()
        except ValueError:
            raise AccountError("--as-of must be an ISO 8601 timestamp with a timezone") from None
        engine = create_db_engine(self.settings.retention_database_url)
        try:
            report = run_retention(
                engine,
                confirm_database=args.database,
                as_of=as_of,
                dry_run=args.dry_run,
                batch_size=args.batch_size,
            )
        finally:
            engine.dispose()
        mode = "would delete (dry run, rolled back)" if report.dry_run else "deleted"
        print(f"Retention on {report.database} as of {report.as_of.isoformat()}:", file=self.out)
        for table, count in report.deleted.items():
            print(f"  {table}: {mode} {count}", file=self.out)
        if not report.dry_run:
            # The retention role cannot write audit rows (by design), so the run is recorded
            # after it commits, through the runtime role. A crash in between leaves no record.
            with self.sessions.begin() as db:
                self.audit.record(
                    db,
                    actor_kind="user",
                    actor_user_id=actor,
                    action="retention.run",
                    resource_type="retention",
                    resource_id=None,
                    request_id=None,
                    now=self.clock(),
                )

    def _print_key(self, key_id: UUID, source: str, expires_at: datetime, plaintext: str) -> None:
        print(
            f"Created key {key_id} for source {source}, expires {expires_at.isoformat()}",
            file=self.out,
        )
        print("API key (shown once; store it now, it cannot be retrieved again):", file=self.out)
        print(plaintext, file=self.out)


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO = sys.stdin,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
    clock: Clock = utc_now,
    settings: Settings | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    settings = settings or Settings()
    if settings.database_url is None:
        print("DATABASE_URL must be set (runtime role)", file=err)
        return 2
    engine = create_db_engine(settings.database_url)
    try:
        Operator(settings, engine, clock, out).run(args, SecretInput(args.stdin, stdin))
    except (AccountError, RetentionRefused) as error:
        print(f"Refused: {error}", file=err)
        return 1
    except DBAPIError:
        # Each change is one transaction; only already-committed retention batches persist.
        print("Database unavailable; the command did not complete", file=err)
        return 3
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
