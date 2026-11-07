"""Database access for event receipts and their standalone incidents (runtime role grants)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from kavach.db.models import Assessment, Event, Incident, IncidentEvent


@dataclass(frozen=True)
class EventRecord:
    id: UUID
    source: str
    external_event_id: str
    kind: str
    payload_digest: bytes
    payload_key_version: str
    analysis_status: str
    received_at: datetime
    processing_ms: int
    signals: dict[str, Any]
    # Used to (re)index candidates; never returned to clients.
    subscriber_digest: bytes
    identity_key_version: str
    event_time: datetime


RECEIPT_COLUMNS = (
    Event.id,
    Event.source,
    Event.external_event_id,
    Event.kind,
    Event.payload_digest,
    Event.payload_key_version,
    Event.analysis_status,
    Event.received_at,
    Event.processing_ms,
    Event.signals,
    Event.subscriber_digest,
    Event.identity_key_version,
    Event.event_time,
)


def lock_subscriber(db: Session, subscriber_digest: bytes) -> None:
    """Serialize writes for one subscriber (ARCHITECTURE.md data flow step 4)."""
    key = int.from_bytes(subscriber_digest[:8], "big", signed=True)
    db.execute(select(func.pg_advisory_xact_lock(key)))


def find_event(db: Session, source: str, external_event_id: str) -> EventRecord | None:
    row = db.execute(
        select(*RECEIPT_COLUMNS).where(
            Event.source == source, Event.external_event_id == external_event_id
        )
    ).one_or_none()
    return EventRecord(*row) if row else None


def events_since(db: Session, earliest_event_time: datetime) -> list[EventRecord]:
    """Events still inside the candidate horizon, for rebuilding the Redis index."""
    rows = db.execute(
        select(*RECEIPT_COLUMNS)
        .where(Event.event_time >= earliest_event_time)
        .order_by(Event.event_time, Event.id)
    )
    return [EventRecord(*row) for row in rows]


def set_local_statement_timeout(db: Session, milliseconds: int) -> None:
    """Bound every statement in this transaction by the request's remaining deadline."""
    db.execute(select(func.set_config("statement_timeout", str(max(1, milliseconds)), True)))


def find_event_for_source(db: Session, event_id: UUID, source: str) -> EventRecord | None:
    row = db.execute(
        select(*RECEIPT_COLUMNS).where(Event.id == event_id, Event.source == source)
    ).one_or_none()
    return EventRecord(*row) if row else None


def insert_event_if_absent(db: Session, values: dict[str, Any]) -> UUID | None:
    """Insert unless (source, external_event_id) already exists; None means it does.

    The unique constraint is the arbiter: a concurrent insert of the same ID waits for the
    other transaction and then does nothing.
    """
    return db.execute(
        insert(Event)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_events_source_external_event_id")
        .returning(Event.id)
    ).scalar_one_or_none()


def insert_standalone_incident(
    db: Session,
    *,
    event_id: UUID,
    kind: str,
    occurred_at: datetime,
    now: datetime,
    expires_at: datetime,
    evidence: dict[str, Any],
    policy_version: str,
    analysis_status: str = "unavailable",
    model_versions: dict[str, str] | None = None,
) -> UUID:
    """One standalone incident with its first assessment. The tier is always `unknown` here:
    no calibrated base signal exists (M4 model evidence is uncalibrated, D04-A1)."""
    incident_id = db.execute(
        insert(Incident)
        .values(
            kind="standalone",
            incident_key=f"standalone:{event_id}",
            occurred_at=occurred_at,
            current_revision=1,
            version=1,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )
        .returning(Incident.id)
    ).scalar_one()
    db.execute(
        insert(IncidentEvent).values(incident_id=incident_id, event_id=event_id, channel=kind)
    )
    db.execute(
        insert(Assessment).values(
            incident_id=incident_id,
            revision=1,
            base_score=None,
            fusion_score=None,
            final_score=None,
            tier="unknown",
            analysis_status=analysis_status,
            evidence=evidence,
            model_versions=model_versions or {},
            policy_version=policy_version,
            created_at=now,
        )
    )
    return incident_id
