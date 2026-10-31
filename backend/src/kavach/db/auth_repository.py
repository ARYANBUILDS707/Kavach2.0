"""Database access for users and sessions, within the runtime role's grants."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from kavach.db.models import User, UserSession


@dataclass(frozen=True)
class UserRecord:
    id: UUID
    username: str
    display_name: str
    role: str
    password_hash: str
    is_active: bool


@dataclass(frozen=True)
class SessionRecord:
    id: UUID
    user_id: UUID
    csrf_digest: bytes
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    display_name: str
    role: str
    user_is_active: bool


def find_user(db: Session, username: str) -> UserRecord | None:
    row = db.execute(
        select(
            User.id,
            User.username,
            User.display_name,
            User.role,
            User.password_hash,
            User.is_active,
        ).where(User.username == username)
    ).one_or_none()
    return UserRecord(*row) if row else None


def insert_user(
    db: Session, *, username: str, display_name: str, role: str, password_hash: str
) -> UUID:
    return db.execute(
        insert(User)
        .values(
            username=username, display_name=display_name, role=role, password_hash=password_hash
        )
        .returning(User.id)
    ).scalar_one()


def update_password_hash(db: Session, user_id: UUID, password_hash: str) -> None:
    db.execute(update(User).where(User.id == user_id).values(password_hash=password_hash))


def set_user_active(db: Session, user_id: UUID, active: bool) -> None:
    db.execute(update(User).where(User.id == user_id).values(is_active=active))


def insert_session(
    db: Session,
    *,
    user_id: UUID,
    token_digest: bytes,
    csrf_digest: bytes,
    now: datetime,
    expires_at: datetime,
) -> UUID:
    return db.execute(
        insert(UserSession)
        .values(
            user_id=user_id,
            token_digest=token_digest,
            csrf_digest=csrf_digest,
            created_at=now,
            last_seen_at=now,
            expires_at=expires_at,
        )
        .returning(UserSession.id)
    ).scalar_one()


def find_session(db: Session, token_digest: bytes) -> SessionRecord | None:
    row = db.execute(
        select(
            UserSession.id,
            UserSession.user_id,
            UserSession.csrf_digest,
            UserSession.last_seen_at,
            UserSession.expires_at,
            UserSession.revoked_at,
            User.display_name,
            User.role,
            User.is_active,
        )
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.token_digest == token_digest)
    ).one_or_none()
    return SessionRecord(*row) if row else None


def touch_session(db: Session, session_id: UUID, now: datetime) -> None:
    db.execute(update(UserSession).where(UserSession.id == session_id).values(last_seen_at=now))


def revoke_session(db: Session, session_id: UUID, now: datetime) -> bool:
    result = db.execute(
        update(UserSession)
        .where(UserSession.id == session_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return result.rowcount == 1


def revoke_session_by_digest(db: Session, token_digest: bytes, now: datetime) -> None:
    db.execute(
        update(UserSession)
        .where(UserSession.token_digest == token_digest, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def revoke_user_sessions(db: Session, user_id: UUID, now: datetime) -> int:
    result = db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return result.rowcount
