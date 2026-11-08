"""Incident reads for the analyst API (API.md "SMS MVP-1 contract"). Read-only: no write, no
audit row, no review. Expired incidents are invisible even before the retention job runs.

The list cursor is opaque base64url JSON holding the last row's `(occurred_at, id)` and a
fingerprint of the active filters, so a cursor cannot be replayed under different filters.
It carries no secret and is not signed: a well-formed cursor only moves the page position
within data the caller may already read.
"""

import base64
import binascii
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

import kavach.db.incident_repository as repo
from kavach.core.clock import Clock

UNREACHABLE = (OperationalError, InterfaceError)
CURSOR_VERSION = 1
MAX_CURSOR_LENGTH = 512


class IncidentsUnavailable(Exception):
    """PostgreSQL could not answer (unreachable or statement timeout)."""


class InvalidCursor(Exception):
    """Malformed cursor, or one issued under different filters."""


@dataclass(frozen=True)
class IncidentPage:
    items: list[repo.IncidentRow]
    next_cursor: str | None


@dataclass(frozen=True)
class IncidentDetail:
    incident: repo.IncidentRow
    assessment: repo.AssessmentRow
    events: list[repo.LinkedEventRow]
    related_incident_ids: list[UUID]


def filters_fingerprint(filters: repo.IncidentFilters) -> str:
    canonical = {
        name: value.isoformat() if isinstance(value, datetime) else value
        for name, value in asdict(filters).items()
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:32]


def encode_cursor(filters: repo.IncidentFilters, row: repo.IncidentRow) -> str:
    payload = {
        "v": CURSOR_VERSION,
        "at": row.occurred_at.isoformat(),
        "id": str(row.id),
        "f": filters_fingerprint(filters),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, filters: repo.IncidentFilters) -> tuple[datetime, UUID]:
    if not cursor or len(cursor) > MAX_CURSOR_LENGTH:
        raise InvalidCursor
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {"v", "at", "id", "f"}:
            raise InvalidCursor
        if payload["v"] != CURSOR_VERSION or payload["f"] != filters_fingerprint(filters):
            raise InvalidCursor
        if not isinstance(payload["at"], str) or not isinstance(payload["id"], str):
            raise InvalidCursor
        occurred_at = datetime.fromisoformat(payload["at"])
        incident_id = UUID(payload["id"])
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError):
        raise InvalidCursor from None
    if occurred_at.tzinfo is None:
        raise InvalidCursor
    return occurred_at, incident_id


class IncidentReadService:
    def __init__(self, *, sessions: sessionmaker[Session], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    def list(self, filters: repo.IncidentFilters, limit: int, cursor: str | None) -> IncidentPage:
        after = decode_cursor(cursor, filters) if cursor is not None else None
        try:
            with self.sessions.begin() as db:
                rows = repo.list_incidents(db, filters, self.clock(), after, limit + 1)
        except UNREACHABLE:
            raise IncidentsUnavailable from None
        items = rows[:limit]
        has_more = len(rows) > limit
        return IncidentPage(
            items=items, next_cursor=encode_cursor(filters, items[-1]) if has_more else None
        )

    def detail(self, incident_id: UUID) -> IncidentDetail | None:
        """None for a missing or expired incident (the caller returns the same 404)."""
        now = self.clock()
        try:
            with self.sessions.begin() as db:
                incident = repo.find_incident(db, incident_id, now)
                if incident is None:
                    return None
                return IncidentDetail(
                    incident=incident,
                    assessment=repo.current_assessment(db, incident.id, incident.current_revision),
                    events=repo.linked_events(db, incident.id),
                    related_incident_ids=repo.related_incident_ids(db, incident.id, now),
                )
        except UNREACHABLE:
            raise IncidentsUnavailable from None
