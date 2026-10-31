"""Minimal operator command to provision one account (M2.3). The full CLI is M2.4.

    python -m kavach.auth.provision --username alice --display-name "Alice" --role analyst

The password is read from an interactive prompt (asked twice) or, with --password-stdin, from
the first line of standard input; never from arguments, so it stays out of shell history and
process listings. Requires DATABASE_URL, AUDIT_HMAC_KEYS and AUDIT_HMAC_ACTIVE_VERSION.
"""

import argparse
import getpass
import sys
from collections.abc import Sequence
from datetime import timedelta
from typing import TextIO

from kavach.auth.accounts import ROLES, AccountError, AccountService
from kavach.auth.passwords import PasswordService
from kavach.core.clock import utc_now
from kavach.core.config import Settings, parse_audit_keys
from kavach.db.engine import create_db_engine, create_session_factory
from kavach.privacy.audit import AuditWriter


def read_password(from_stdin: bool, stdin: TextIO) -> str:
    if from_stdin:
        return stdin.readline().rstrip("\n")
    first = getpass.getpass("New password: ")
    if first != getpass.getpass("Repeat password: "):
        raise AccountError("The passwords did not match")
    return first


def main(argv: Sequence[str] | None = None, stdin: TextIO = sys.stdin) -> int:
    parser = argparse.ArgumentParser(description="Provision one KAVACH account.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--role", required=True, choices=ROLES)
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args(argv)

    settings = Settings()
    if (
        settings.database_url is None
        or settings.audit_hmac_keys is None
        or settings.audit_hmac_active_version is None
    ):
        print("The authentication configuration (see .env.example) must be set", file=sys.stderr)
        return 2
    engine = create_db_engine(settings.database_url)
    try:
        accounts = AccountService(
            sessions=create_session_factory(engine),
            passwords=PasswordService(),
            audit=AuditWriter(
                parse_audit_keys(settings.audit_hmac_keys),
                settings.audit_hmac_active_version,
                timedelta(days=settings.audit_retention_days),
            ),
            clock=utc_now,
        )
        user_id = accounts.provision_user(
            username=args.username,
            display_name=args.display_name,
            role=args.role,
            password=read_password(args.password_stdin, stdin),
        )
    except AccountError as error:
        print(f"Not provisioned: {error}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(f"Provisioned user {user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
