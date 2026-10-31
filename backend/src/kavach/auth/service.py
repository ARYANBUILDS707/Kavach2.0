"""Authentication rules: login, session validation and logout (M2.3, D03 and C-06)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from kavach.auth.passwords import PasswordService
from kavach.auth.throttle import LoginThrottle, ThrottleUnavailable
from kavach.auth.tokens import csrf_token_for, new_session_token, token_digest
from kavach.core.clock import Clock
from kavach.core.telemetry import security_event
from kavach.db import auth_repository as repo
from kavach.privacy.audit import AuditWriter

# last_seen_at is written at most this often, so reads do not all become writes.
TOUCH_INTERVAL = timedelta(seconds=60)


class InvalidCredentials(Exception):
    """Unknown user, wrong password or inactive account; callers must not distinguish them."""


class SessionInvalid(Exception):
    """Missing, unknown, expired or revoked session, or an inactive account."""


class LoginThrottled(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("login throttled")
        self.retry_after_seconds = retry_after_seconds


class DependencyUnavailable(Exception):
    """PostgreSQL or Redis could not be reached; nothing was authenticated."""


@dataclass(frozen=True)
class SessionPolicy:
    idle: timedelta
    absolute: timedelta


@dataclass(frozen=True)
class ActiveSession:
    session_id: UUID
    user_id: UUID
    display_name: str
    role: str
    csrf_digest: bytes
    expires_at: datetime  # the earlier of the idle and absolute deadlines


@dataclass(frozen=True)
class IssuedSession:
    token: str
    csrf_token: str
    session: ActiveSession


class AuthService:
    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        passwords: PasswordService,
        throttle: LoginThrottle,
        audit: AuditWriter,
        policy: SessionPolicy,
        clock: Clock,
    ) -> None:
        self.sessions = sessions
        self.passwords = passwords
        self.throttle = throttle
        self.audit = audit
        self.policy = policy
        self.clock = clock

    def login(
        self,
        *,
        username: str,
        password: str,
        client_ip: str,
        request_id: UUID,
        previous_token: str | None,
    ) -> IssuedSession:
        canonical = username.lower()
        # Fail closed: without a confirmed reservation no password is checked.
        try:
            reservation = self.throttle.reserve(canonical, client_ip)
        except ThrottleUnavailable:
            security_event("auth.login_denied", "throttle_unavailable", request_id)
            raise DependencyUnavailable from None
        if not reservation.allowed:
            security_event("auth.login_denied", "throttled", request_id)
            raise LoginThrottled(reservation.retry_after_seconds)

        try:
            with self.sessions.begin() as db:
                user = repo.find_user(db, canonical)
        except DBAPIError:
            raise DependencyUnavailable from None
        # Always one Argon2 verification, whether or not the user exists or is active.
        verified = self.passwords.verify(user.password_hash if user else None, password)
        if user is None or not verified or not user.is_active:
            security_event("auth.login_denied", "invalid_credentials", request_id)
            raise InvalidCredentials

        now = self.clock()
        token = new_session_token()
        csrf_token = csrf_token_for(token)
        try:
            with self.sessions.begin() as db:
                if previous_token:
                    # Rotation: a session presented at login never survives it.
                    repo.revoke_session_by_digest(db, token_digest(previous_token), now)
                if self.passwords.needs_rehash(user.password_hash):
                    repo.update_password_hash(db, user.id, self.passwords.hash(password))
                session_id = repo.insert_session(
                    db,
                    user_id=user.id,
                    token_digest=token_digest(token),
                    csrf_digest=token_digest(csrf_token),
                    now=now,
                    expires_at=now + self.policy.absolute,
                )
                self.audit.record(
                    db,
                    actor_kind="user",
                    actor_user_id=user.id,
                    action="auth.login",
                    resource_type="session",
                    resource_id=session_id,
                    request_id=request_id,
                    now=now,
                )
        except DBAPIError:
            raise DependencyUnavailable from None
        self.throttle.release(canonical, client_ip)
        return IssuedSession(
            token=token,
            csrf_token=csrf_token,
            session=ActiveSession(
                session_id=session_id,
                user_id=user.id,
                display_name=user.display_name,
                role=user.role,
                csrf_digest=token_digest(csrf_token),
                expires_at=min(now + self.policy.idle, now + self.policy.absolute),
            ),
        )

    def authenticate(self, token: str | None) -> ActiveSession:
        if not token:
            raise SessionInvalid
        now = self.clock()
        try:
            with self.sessions.begin() as db:
                record = repo.find_session(db, token_digest(token))
                if (
                    record is None
                    or record.revoked_at is not None
                    or not record.user_is_active
                    or now >= record.expires_at
                    or now >= record.last_seen_at + self.policy.idle
                ):
                    raise SessionInvalid
                last_seen = record.last_seen_at
                if now - last_seen >= TOUCH_INTERVAL:
                    repo.touch_session(db, record.id, now)
                    last_seen = now
        except DBAPIError:
            raise DependencyUnavailable from None
        return ActiveSession(
            session_id=record.id,
            user_id=record.user_id,
            display_name=record.display_name,
            role=record.role,
            csrf_digest=record.csrf_digest,
            expires_at=min(last_seen + self.policy.idle, record.expires_at),
        )

    def logout(self, session: ActiveSession, request_id: UUID) -> None:
        now = self.clock()
        try:
            with self.sessions.begin() as db:
                if repo.revoke_session(db, session.session_id, now):
                    self.audit.record(
                        db,
                        actor_kind="user",
                        actor_user_id=session.user_id,
                        action="auth.logout",
                        resource_type="session",
                        resource_id=session.session_id,
                        request_id=request_id,
                        now=now,
                    )
        except DBAPIError:
            raise DependencyUnavailable from None
