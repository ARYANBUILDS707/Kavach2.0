"""Operator account lifecycle (minimal M2.3 subset): provision, deactivate, reset password.

Every change is audited as a `system` actor in the same transaction. Deactivation and password
reset revoke all of the user's sessions. The full operator CLI and key lifecycle are M2.4.
"""

from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from kavach.auth.passwords import PasswordService, validate_new_password
from kavach.core.clock import Clock
from kavach.db import auth_repository as repo
from kavach.privacy.audit import AuditWriter

Role = Literal["viewer", "analyst", "admin"]
ROLES: tuple[Role, ...] = ("viewer", "analyst", "admin")


class AccountError(Exception):
    """A provisioning request that cannot be applied; the message is safe to show operators."""


class AccountService:
    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        passwords: PasswordService,
        audit: AuditWriter,
        clock: Clock,
    ) -> None:
        self.sessions = sessions
        self.passwords = passwords
        self.audit = audit
        self.clock = clock

    def provision_user(self, *, username: str, display_name: str, role: str, password: str) -> UUID:
        canonical = username.lower()
        if role not in ROLES:
            raise AccountError(f"Role must be one of: {', '.join(ROLES)}")
        if not 1 <= len(canonical) <= 80 or not 1 <= len(display_name.strip()) <= 120:
            raise AccountError("Username must be 1-80 and display name 1-120 characters")
        try:
            validate_new_password(canonical, password)
        except ValueError as error:
            raise AccountError(str(error)) from None
        password_hash = self.passwords.hash(password)
        with self.sessions.begin() as db:
            if repo.find_user(db, canonical) is not None:
                raise AccountError("That username is already provisioned")
            user_id = repo.insert_user(
                db,
                username=canonical,
                display_name=display_name.strip(),
                role=role,
                password_hash=password_hash,
            )
            self._audit(db, "user.provision", user_id)
        return user_id

    def deactivate_user(self, username: str) -> UUID:
        with self.sessions.begin() as db:
            user = self._existing(db, username)
            repo.set_user_active(db, user, False)
            repo.revoke_user_sessions(db, user, self.clock())
            self._audit(db, "user.deactivate", user)
        return user

    def reset_password(self, username: str, new_password: str) -> UUID:
        try:
            validate_new_password(username, new_password)
        except ValueError as error:
            raise AccountError(str(error)) from None
        password_hash = self.passwords.hash(new_password)
        with self.sessions.begin() as db:
            user = self._existing(db, username)
            repo.update_password_hash(db, user, password_hash)
            repo.revoke_user_sessions(db, user, self.clock())
            self._audit(db, "user.password_reset", user)
        return user

    def _existing(self, db: Session, username: str) -> UUID:
        user = repo.find_user(db, username.lower())
        if user is None:
            raise AccountError("No such user")
        return user.id

    def _audit(self, db: Session, action: str, user_id: UUID) -> None:
        self.audit.record(
            db,
            actor_kind="system",
            action=action,
            resource_type="user",
            resource_id=user_id,
            request_id=None,
            now=self.clock(),
        )
