"""SQLAlchemy entities for the DATABASE.md schema (M2.2): persistence shape only, no rules.

Cross-row rules (incident membership, standalone fusion scores) are enforced by deferred
constraint triggers in the migrations; privileges are granted there too.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk() -> Mapped[UUID]:
    return mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def one_of(column: str, *values: str) -> CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=column)


def digest_32(column: str) -> CheckConstraint:
    return CheckConstraint(f"octet_length({column}) = 32", name=f"{column}_length")


def unit_score(column: str) -> CheckConstraint:
    # NaN compares greater than every number and infinities fall outside 0..1, so both fail.
    return CheckConstraint(f"{column} >= 0 AND {column} <= 1", name=f"{column}_range")


def json_object(column: str, max_bytes: int | None = None) -> CheckConstraint:
    rule = f"jsonb_typeof({column}) = 'object'"
    if max_bytes is not None:
        rule += f" AND octet_length({column}::text) <= {max_bytes}"
    return CheckConstraint(rule, name=f"{column}_shape")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username"),
        CheckConstraint(
            "username = lower(username) AND char_length(username) >= 1", name="username_canonical"
        ),
        one_of("role", "viewer", "analyst", "admin"),
    )

    id: Mapped[UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(String(80))
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = created_at()
    # Maintained by the users_set_updated_at trigger.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_digest"),
        digest_32("token_digest"),
        digest_32("csrf_digest"),
        Index("ix_sessions_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_digest: Mapped[bytes] = mapped_column(LargeBinary)
    csrf_digest: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = created_at()
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestKey(Base):
    __tablename__ = "ingest_keys"
    __table_args__ = (UniqueConstraint("key_digest"), digest_32("key_digest"))

    id: Mapped[UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(80))
    key_digest: Mapped[bytes] = mapped_column(LargeBinary)
    source: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = created_at()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("source", "external_event_id"),
        one_of("kind", "sms", "call"),
        one_of("analysis_status", "complete", "partial", "unavailable"),
        digest_32("subscriber_digest"),
        digest_32("payload_digest"),
        unit_score("sms_score"),
        unit_score("voice_intent_score"),
        unit_score("synthesis_score"),
        CheckConstraint(
            "(kind = 'sms' AND voice_intent_score IS NULL AND synthesis_score IS NULL)"
            " OR (kind = 'call' AND sms_score IS NULL)",
            name="kind_scores",
        ),
        CheckConstraint("processing_ms >= 0", name="processing_ms_non_negative"),
        json_object("signals", 16_384),
        json_object("model_versions", 4_096),
        Index(
            "ix_events_candidates",
            "subscriber_digest",
            "identity_key_version",
            "kind",
            "event_time",
            "id",
        ),
        Index("ix_events_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = uuid_pk()
    source: Mapped[str] = mapped_column(String(64))
    external_event_id: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(Text)
    subscriber_digest: Mapped[bytes] = mapped_column(LargeBinary)
    identity_key_version: Mapped[str] = mapped_column(String(32))
    payload_digest: Mapped[bytes] = mapped_column(LargeBinary)
    payload_key_version: Mapped[str] = mapped_column(String(32))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    analysis_status: Mapped[str] = mapped_column(Text)
    sms_score: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    voice_intent_score: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    synthesis_score: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB)
    model_versions: Mapped[dict[str, Any]] = mapped_column(JSONB)
    processing_ms: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        UniqueConstraint("incident_key"),
        one_of("kind", "standalone", "pair"),
        CheckConstraint("current_revision >= 1", name="current_revision_positive"),
        CheckConstraint("version >= 1", name="version_positive"),
        # Deferred so an incident and its first assessment/review can be inserted atomically.
        ForeignKeyConstraint(
            ["id", "current_revision"],
            ["assessments.incident_id", "assessments.revision"],
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["id", "latest_review_id"],
            ["reviews.incident_id", "reviews.id"],
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        Index("ix_incidents_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(Text)
    incident_key: Mapped[str] = mapped_column(String(160))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_revision: Mapped[int] = mapped_column(Integer)
    latest_review_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# Feed ordering indexes (occurred_at DESC, id DESC), declared from columns so Alembic compares them.
Index("ix_incidents_feed", Incident.occurred_at.desc(), Incident.id.desc())
Index("ix_incidents_kind_feed", Incident.kind, Incident.occurred_at.desc(), Incident.id.desc())


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    __table_args__ = (
        PrimaryKeyConstraint("incident_id", "event_id"),
        UniqueConstraint("incident_id", "channel"),
        one_of("channel", "sms", "call"),
        Index("ix_incident_events_event_id_incident_id", "event_id", "incident_id"),
    )

    incident_id: Mapped[UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    event_id: Mapped[UUID] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"))
    channel: Mapped[str] = mapped_column(Text)


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (
        PrimaryKeyConstraint("incident_id", "revision"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        unit_score("base_score"),
        unit_score("fusion_score"),
        unit_score("final_score"),
        one_of("tier", "unknown", "low", "medium", "high", "critical"),
        one_of("analysis_status", "complete", "partial", "unavailable"),
        CheckConstraint(
            "(tier = 'unknown' AND final_score IS NULL)"
            " OR (tier <> 'unknown' AND final_score IS NOT NULL)",
            name="tier_final_score",
        ),
        json_object("evidence", 32_768),
        json_object("model_versions"),
    )

    incident_id: Mapped[UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer)
    base_score: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    fusion_score: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    final_score: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    tier: Mapped[str] = mapped_column(Text)
    analysis_status: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    model_versions: Mapped[dict[str, Any]] = mapped_column(JSONB)
    policy_version: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = created_at()


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("incident_id", "id"),
        UniqueConstraint("analyst_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["incident_id", "assessment_revision"],
            ["assessments.incident_id", "assessments.revision"],
            ondelete="CASCADE",
        ),
        one_of("decision", "true_fraud", "false_alarm", "needs_investigation"),
        digest_32("payload_digest"),
        Index("ix_reviews_history", "incident_id", "created_at", "id"),
    )

    id: Mapped[UUID] = uuid_pk()
    incident_id: Mapped[UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    assessment_revision: Mapped[int] = mapped_column(Integer)
    analyst_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decision: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(String(1000))
    idempotency_key: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    payload_digest: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = created_at()


class AuditRecord(Base):
    __tablename__ = "audit_records"
    __table_args__ = (
        one_of("actor_kind", "user", "ingestor", "system"),
        CheckConstraint(
            "(actor_kind = 'user' AND actor_user_id IS NOT NULL AND actor_ingest_key_id IS NULL)"
            " OR (actor_kind = 'ingestor' AND actor_ingest_key_id IS NOT NULL"
            " AND actor_user_id IS NULL)"
            " OR (actor_kind = 'system' AND actor_user_id IS NULL AND actor_ingest_key_id IS NULL)",
            name="actor_matches_kind",
        ),
        one_of("outcome", "success", "denied"),
        digest_32("record_hmac"),
        Index("ix_audit_records_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = uuid_pk()
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    actor_ingest_key_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ingest_keys.id", ondelete="RESTRICT")
    )
    actor_kind: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(80))
    resource_type: Mapped[str] = mapped_column(String(40))
    # Intentionally not a foreign key: audit outlives expiring evidence.
    resource_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    request_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    outcome: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    key_version: Mapped[str] = mapped_column(String(32))
    record_hmac: Mapped[bytes] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
