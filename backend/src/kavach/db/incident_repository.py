"""Read-only incident queries for the analyst API (MVP-1). Selects only the columns the API may
return: never subscriber or payload digests, key versions, sources, external IDs or evidence."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, exists, select, tuple_
from sqlalchemy.orm import Session

from kavach.db.models import Assessment, Event, Incident, IncidentEvent


@dataclass(frozen=True)
class IncidentFilters:
    kind: str | None = None
    tier: str | None = None
    channel: str | None = None
    occurred_from: datetime | None = None  # inclusive
    occurred_to: datetime | None = None  # exclusive


@dataclass(frozen=True)
class IncidentRow:
    id: UUID
    kind: str
    occurred_at: datetime
    tier: str
    final_score: float | None
    analysis_status: str
    current_revision: int
    version: int
    updated_at: datetime


@dataclass(frozen=True)
class AssessmentRow:
    revision: int
    tier: str
    base_score: float | None
    fusion_score: float | None
    final_score: float | None
    analysis_status: str
    policy_version: str
    model_versions: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class LinkedEventRow:
    id: UUID
    channel: str
    occurred_at: datetime
    received_at: datetime
    analysis_status: str
    processing_ms: int
    sms_score: float | None
    signals: dict[str, Any]
    model_versions: dict[str, Any]


INCIDENT_COLUMNS = (
    Incident.id,
    Incident.kind,
    Incident.occurred_at,
    Assessment.tier,
    Assessment.final_score,
    Assessment.analysis_status,
    Incident.current_revision,
    Incident.version,
    Incident.updated_at,
)


def live_incidents(now: datetime) -> Select[Any]:
    """Incidents with their current assessment, excluding expired ones not yet deleted."""
    return (
        select(*INCIDENT_COLUMNS)
        .join(
            Assessment,
            (Assessment.incident_id == Incident.id)
            & (Assessment.revision == Incident.current_revision),
        )
        .where(Incident.expires_at > now)
    )


def list_incidents(
    db: Session,
    filters: IncidentFilters,
    now: datetime,
    after: tuple[datetime, UUID] | None,
    limit: int,
) -> list[IncidentRow]:
    """Feed order `occurred_at DESC, id DESC`; `after` is the last row of the previous page."""
    query = live_incidents(now)
    if filters.kind is not None:
        query = query.where(Incident.kind == filters.kind)
    if filters.tier is not None:
        query = query.where(Assessment.tier == filters.tier)
    if filters.channel is not None:
        query = query.where(
            exists().where(
                IncidentEvent.incident_id == Incident.id,
                IncidentEvent.channel == filters.channel,
            )
        )
    if filters.occurred_from is not None:
        query = query.where(Incident.occurred_at >= filters.occurred_from)
    if filters.occurred_to is not None:
        query = query.where(Incident.occurred_at < filters.occurred_to)
    if after is not None:
        query = query.where(tuple_(Incident.occurred_at, Incident.id) < tuple_(*after))
    rows = db.execute(query.order_by(Incident.occurred_at.desc(), Incident.id.desc()).limit(limit))
    return [IncidentRow(*row) for row in rows]


def find_incident(db: Session, incident_id: UUID, now: datetime) -> IncidentRow | None:
    row = db.execute(live_incidents(now).where(Incident.id == incident_id)).one_or_none()
    return IncidentRow(*row) if row else None


def current_assessment(db: Session, incident_id: UUID, revision: int) -> AssessmentRow:
    row = db.execute(
        select(
            Assessment.revision,
            Assessment.tier,
            Assessment.base_score,
            Assessment.fusion_score,
            Assessment.final_score,
            Assessment.analysis_status,
            Assessment.policy_version,
            Assessment.model_versions,
            Assessment.created_at,
        ).where(Assessment.incident_id == incident_id, Assessment.revision == revision)
    ).one()
    return AssessmentRow(*row)


def linked_events(db: Session, incident_id: UUID) -> list[LinkedEventRow]:
    rows = db.execute(
        select(
            Event.id,
            IncidentEvent.channel,
            Event.event_time,
            Event.received_at,
            Event.analysis_status,
            Event.processing_ms,
            Event.sms_score,
            Event.signals,
            Event.model_versions,
        )
        .join(IncidentEvent, IncidentEvent.event_id == Event.id)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(Event.event_time, Event.id)
    )
    return [LinkedEventRow(*row) for row in rows]


def related_incident_ids(db: Session, incident_id: UUID, now: datetime) -> list[UUID]:
    """Other live incidents sharing an event with this one (pair incidents arrive with M6)."""
    shared = select(IncidentEvent.event_id).where(IncidentEvent.incident_id == incident_id)
    rows = db.execute(
        select(Incident.id)
        .join(IncidentEvent, IncidentEvent.incident_id == Incident.id)
        .where(
            IncidentEvent.event_id.in_(shared),
            Incident.id != incident_id,
            Incident.expires_at > now,
        )
        .distinct()
        .order_by(Incident.id)
    )
    return list(rows.scalars())
