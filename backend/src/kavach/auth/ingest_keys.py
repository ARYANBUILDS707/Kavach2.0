"""Source-scoped ingestion API keys (DATABASE.md ingest_keys, API.md "Identity and permissions").

A key is `kvk_` plus 32 random bytes (URL-safe). Only its SHA-256 digest is stored; the
plaintext is returned once, by `create`/`rotate`, and never again. Each key authorizes exactly
one `source` and always expires (default 90 days, at most 365). Lifecycle changes require an
active admin actor and are audited in the same transaction.
"""

import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from kavach.auth.accounts import AccountError, require_active_admin
from kavach.auth.tokens import token_digest
from kavach.core.clock import Clock
from kavach.core.telemetry import security_event
from kavach.db import auth_repository as repo
from kavach.privacy.audit import AuditWriter

# Connection-level failures only; privilege or programming errors must surface as 500s.
UNREACHABLE = (OperationalError, InterfaceError)

KEY_PREFIX = "kvk_"
KEY_BYTES = 32
MAX_PRESENTED_KEY_LENGTH = 128
DEFAULT_KEY_LIFETIME = timedelta(days=90)
MAX_KEY_LIFETIME = timedelta(days=365)
# Same syntax as the event `source` field (api/schemas/events.py).
SOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class InvalidIngestKey(Exception):
    """Malformed, unknown, expired or revoked; callers must not distinguish these."""


class IngestKeysUnavailable(Exception):
    """The database could not be reached; nothing was authenticated."""


@dataclass(frozen=True)
class IngestPrincipal:
    key_id: UUID
    source: str


@dataclass(frozen=True)
class IssuedKey:
    key_id: UUID
    plaintext: str
    source: str
    expires_at: datetime


def new_ingest_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(KEY_BYTES)


def well_formed_key(presented: str) -> bool:
    """Shape only (no lookup); anything else can never authenticate."""
    return presented.startswith(KEY_PREFIX) and len(presented) <= MAX_PRESENTED_KEY_LENGTH


class IngestKeyService:
    def __init__(
        self, *, sessions: sessionmaker[Session], audit: AuditWriter, clock: Clock
    ) -> None:
        self.sessions = sessions
        self.audit = audit
        self.clock = clock

    # --- request authentication -------------------------------------------------------------

    def authenticate(self, presented: str, request_id: UUID | None) -> IngestPrincipal:
        if not well_formed_key(presented):
            security_event("ingest.key_rejected", "malformed", request_id)
            raise InvalidIngestKey
        digest = token_digest(presented)
        try:
            with self.sessions.begin() as db:
                record = repo.find_ingest_key_by_digest(db, digest)
        except UNREACHABLE:
            raise IngestKeysUnavailable from None
        now = self.clock()
        if record is None or not hmac.compare_digest(record.key_digest, digest):
            reason = "unknown"
        elif record.revoked_at is not None:
            reason = "revoked"
        elif now >= record.expires_at:
            reason = "expired"
        else:
            return IngestPrincipal(key_id=record.id, source=record.source)
        security_event("ingest.key_rejected", reason, request_id)
        raise InvalidIngestKey

    # --- operator lifecycle -----------------------------------------------------------------

    def create(
        self,
        *,
        actor_id: UUID,
        name: str,
        source: str,
        lifetime: timedelta = DEFAULT_KEY_LIFETIME,
    ) -> IssuedKey:
        self._validate(name, source, lifetime)
        with self.sessions.begin() as db:
            require_active_admin(db, actor_id)
            issued = self._issue(db, actor_id, name, source, lifetime, "key.create")
        return issued

    def rotate(
        self, *, actor_id: UUID, key_id: UUID, lifetime: timedelta = DEFAULT_KEY_LIFETIME
    ) -> IssuedKey:
        """Issue a replacement for the same name and source and revoke the old key atomically.

        For an overlap window, use `create` and revoke the old key later instead.
        """
        with self.sessions.begin() as db:
            require_active_admin(db, actor_id)
            old = self._active_key(db, key_id)
            self._validate(old.name, old.source, lifetime)
            issued = self._issue(db, actor_id, old.name, old.source, lifetime, "key.rotate")
            self._revoke(db, actor_id, old.id)
        return issued

    def revoke(self, *, actor_id: UUID, key_id: UUID) -> None:
        with self.sessions.begin() as db:
            require_active_admin(db, actor_id)
            self._active_key(db, key_id)
            self._revoke(db, actor_id, key_id)

    def list_keys(self, *, actor_id: UUID) -> list[repo.IngestKeyRecord]:
        with self.sessions.begin() as db:
            require_active_admin(db, actor_id)
            return repo.list_ingest_keys(db)

    def _validate(self, name: str, source: str, lifetime: timedelta) -> None:
        if not 1 <= len(name.strip()) <= 80:
            raise AccountError("Key names must be 1-80 characters")
        if not SOURCE.fullmatch(source):
            raise AccountError(
                "Sources are 1-64 letters, digits, '_' or '-', starting alphanumeric"
            )
        if not timedelta(0) < lifetime <= MAX_KEY_LIFETIME:
            raise AccountError("Key lifetime must be between 1 and 365 days")

    def _active_key(self, db: Session, key_id: UUID) -> repo.IngestKeyRecord:
        record = repo.find_ingest_key(db, key_id)
        if record is None:
            raise AccountError("No such key")
        if record.revoked_at is not None:
            raise AccountError("That key is already revoked")
        return record

    def _issue(
        self,
        db: Session,
        actor_id: UUID,
        name: str,
        source: str,
        lifetime: timedelta,
        action: str,
    ) -> IssuedKey:
        plaintext = new_ingest_key()
        now = self.clock()
        key_id = repo.insert_ingest_key(
            db,
            name=name.strip(),
            key_digest=token_digest(plaintext),
            source=source,
            created_by=actor_id,
            now=now,
            expires_at=now + lifetime,
        )
        self._audit(db, actor_id, action, key_id)
        return IssuedKey(
            key_id=key_id, plaintext=plaintext, source=source, expires_at=now + lifetime
        )

    def _revoke(self, db: Session, actor_id: UUID, key_id: UUID) -> None:
        repo.revoke_ingest_key(db, key_id, self.clock())
        self._audit(db, actor_id, "key.revoke", key_id)

    def _audit(self, db: Session, actor_id: UUID, action: str, key_id: UUID) -> None:
        self.audit.record(
            db,
            actor_kind="user",
            actor_user_id=actor_id,
            action=action,
            resource_type="ingest_key",
            resource_id=key_id,
            request_id=None,
            now=self.clock(),
        )
