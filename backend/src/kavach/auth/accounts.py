"""Operator account lifecycle: bootstrap, provision, deactivate, reset password, change role.

Every mutation names an actor that must be an *active admin*, re-checked inside the same
transaction as the change, and is audited in that transaction. The single exception is
`bootstrap_admin`, which only works while no active admin exists and is audited as `system`.
Changes that could leave no active admin are serialized with an advisory lock and refused.
Deactivation and password reset revoke all of the target's sessions.

The operator's own password check (authenticate_operator) gives attribution and policy
enforcement; the security boundary for these commands remains custody of the database
credentials they run with.
"""

from typing import Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from kavach.auth.passwords import PasswordService, validate_new_password
from kavach.core.clock import Clock
from kavach.db import auth_repository as repo
from kavach.privacy.audit import AuditWriter

Role = Literal["viewer", "analyst", "admin"]
ROLES: tuple[Role, ...] = ("viewer", "analyst", "admin")


class AccountError(Exception):
    """A request that cannot be applied; the message is safe to show operators."""


def require_active_admin(db: Session, actor_id: UUID) -> None:
    actor = repo.find_user_by_id(db, actor_id)
    if actor is None or not actor.is_active or actor.role != "admin":
        raise AccountError("The acting operator is not an active admin")


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

    def authenticate_operator(self, username: str, password: str) -> UUID:
        """Return the operator's user ID if the credentials belong to an active admin."""
        with self.sessions.begin() as db:
            user = repo.find_user(db, username.lower())
        verified = self.passwords.verify(user.password_hash if user else None, password)
        if user is None or not verified or not user.is_active or user.role != "admin":
            raise AccountError("Operator authentication failed")
        return user.id

    def bootstrap_admin(self, *, username: str, display_name: str, password: str) -> UUID:
        """Create the first admin. Refused once any active admin exists."""
        canonical, password_hash = self._new_account(username, display_name, "admin", password)
        with self.sessions.begin() as db:
            repo.lock_admin_changes(db)
            if repo.count_active_admins(db) > 0:
                raise AccountError("An active admin exists; create accounts as that admin")
            user_id = self._insert(db, canonical, display_name, "admin", password_hash)
            self._audit(db, None, "user.bootstrap_admin", user_id)
        return user_id

    def provision_user(
        self, *, actor_id: UUID, username: str, display_name: str, role: str, password: str
    ) -> UUID:
        canonical, password_hash = self._new_account(username, display_name, role, password)
        with self.sessions.begin() as db:
            require_active_admin(db, actor_id)
            user_id = self._insert(db, canonical, display_name, role, password_hash)
            self._audit(db, actor_id, "user.provision", user_id)
        return user_id

    def deactivate_user(self, *, actor_id: UUID, username: str) -> UUID:
        with self.sessions.begin() as db:
            repo.lock_admin_changes(db)
            require_active_admin(db, actor_id)
            target = self._existing(db, username)
            if target.id == actor_id:
                raise AccountError("Operators cannot deactivate their own account")
            if not target.is_active:
                raise AccountError("That account is already deactivated")
            if target.role == "admin" and repo.count_active_admins(db) <= 1:
                raise AccountError("Refusing to deactivate the last active admin")
            repo.set_user_active(db, target.id, False)
            repo.revoke_user_sessions(db, target.id, self.clock())
            self._audit(db, actor_id, "user.deactivate", target.id)
        return target.id

    def reset_password(self, *, actor_id: UUID, username: str, new_password: str) -> UUID:
        try:
            validate_new_password(username, new_password)
        except ValueError as error:
            raise AccountError(str(error)) from None
        password_hash = self.passwords.hash(new_password)
        with self.sessions.begin() as db:
            require_active_admin(db, actor_id)
            target = self._existing(db, username)
            repo.update_password_hash(db, target.id, password_hash)
            repo.revoke_user_sessions(db, target.id, self.clock())
            self._audit(db, actor_id, "user.password_reset", target.id)
        return target.id

    def change_role(self, *, actor_id: UUID, username: str, role: str) -> UUID:
        if role not in ROLES:
            raise AccountError(f"Role must be one of: {', '.join(ROLES)}")
        with self.sessions.begin() as db:
            repo.lock_admin_changes(db)
            require_active_admin(db, actor_id)
            target = self._existing(db, username)
            if target.role == role:
                raise AccountError(f"That account already has the {role} role")
            if target.role == "admin" and target.is_active and repo.count_active_admins(db) <= 1:
                raise AccountError("Refusing to demote the last active admin")
            repo.set_user_role(db, target.id, role)
            self._audit(db, actor_id, "user.role_change", target.id)
        return target.id

    def _new_account(
        self, username: str, display_name: str, role: str, password: str
    ) -> tuple[str, str]:
        canonical = username.lower()
        if role not in ROLES:
            raise AccountError(f"Role must be one of: {', '.join(ROLES)}")
        if not 1 <= len(canonical) <= 80 or not 1 <= len(display_name.strip()) <= 120:
            raise AccountError("Username must be 1-80 and display name 1-120 characters")
        try:
            validate_new_password(canonical, password)
        except ValueError as error:
            raise AccountError(str(error)) from None
        return canonical, self.passwords.hash(password)

    def _insert(
        self, db: Session, username: str, display_name: str, role: str, password_hash: str
    ) -> UUID:
        if repo.find_user(db, username) is not None:
            raise AccountError("That username is already provisioned")
        try:
            # A savepoint, so a concurrent duplicate surfaces as a clean refusal.
            with db.begin_nested():
                return repo.insert_user(
                    db,
                    username=username,
                    display_name=display_name.strip(),
                    role=role,
                    password_hash=password_hash,
                )
        except IntegrityError as error:
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            if constraint == "uq_users_username":
                raise AccountError("That username is already provisioned") from None
            raise

    def _existing(self, db: Session, username: str) -> repo.UserRecord:
        user = repo.find_user(db, username.lower())
        if user is None:
            raise AccountError("No such user")
        return user

    def _audit(self, db: Session, actor_id: UUID | None, action: str, user_id: UUID) -> None:
        self.audit.record(
            db,
            actor_kind="user" if actor_id else "system",
            actor_user_id=actor_id,
            action=action,
            resource_type="user",
            resource_id=user_id,
            request_id=None,
            now=self.clock(),
        )
