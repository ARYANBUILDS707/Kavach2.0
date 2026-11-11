"""Valid synthetic rows for schema tests; each test overrides one field to break one rule."""

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, insert, text
from sqlalchemy.exc import IntegrityError

from kavach.db.models import Assessment, Base, Event, Incident, IncidentEvent

SUBSCRIBER_A = b"A" * 32
SUBSCRIBER_B = b"B" * 32


def digest() -> bytes:
    return os.urandom(32)


def later(days: int = 7) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


def add(connection: Connection, model: type[Base], values: dict[str, Any]) -> Any:
    """Insert one row and return its primary key (a UUID, or a row for composite keys)."""
    keys = list(model.__table__.primary_key.columns)
    row = connection.execute(insert(model).values(**values).returning(*keys)).one()
    return row[0] if len(keys) == 1 else row


def user(**override: Any) -> dict[str, Any]:
    return {
        "username": f"user_{uuid4().hex[:12]}",
        "display_name": "Synthetic Analyst",
        "password_hash": "not-a-real-hash",
        "role": "analyst",
    } | override


def user_session(user_id: UUID, **override: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "user_id": user_id,
        "token_digest": digest(),
        "csrf_digest": digest(),
        "last_seen_at": now,
        "expires_at": now + timedelta(hours=8),
    } | override


def ingest_key(created_by: UUID, **override: Any) -> dict[str, Any]:
    return {
        "name": "simulator key",
        "key_digest": digest(),
        "source": "simulator",
        "created_by": created_by,
        "expires_at": later(90),
    } | override


def event(kind: str = "sms", **override: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "source": "simulator",
        "external_event_id": f"evt_{uuid4().hex}",
        "kind": kind,
        "subscriber_digest": SUBSCRIBER_A,
        "identity_key_version": "v1",
        "payload_digest": digest(),
        "payload_key_version": "v1",
        "event_time": now,
        "received_at": now,
        "analysis_status": "unavailable",
        "signals": {},
        "model_versions": {},
        "processing_ms": 0,
        "expires_at": later(),
    } | override


def incident(kind: str = "standalone", **override: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "kind": kind,
        "incident_key": uuid4().hex,
        "occurred_at": now,
        "current_revision": 1,
        "version": 1,
        "updated_at": now,
        "expires_at": later(),
    } | override


def assessment(incident_id: UUID, **override: Any) -> dict[str, Any]:
    return {
        "incident_id": incident_id,
        "revision": 1,
        "tier": "unknown",
        "analysis_status": "unavailable",
        "evidence": {},
        "model_versions": {},
        "policy_version": "test-policy-0",
    } | override


def review(incident_id: UUID, analyst_id: UUID, **override: Any) -> dict[str, Any]:
    return {
        "incident_id": incident_id,
        "assessment_revision": 1,
        "analyst_id": analyst_id,
        "decision": "needs_investigation",
        "idempotency_key": uuid4(),
        "payload_digest": digest(),
    } | override


def audit(**override: Any) -> dict[str, Any]:
    return {
        "actor_kind": "system",
        "action": "test.action",
        "resource_type": "test",
        "request_id": uuid4(),
        "outcome": "success",
        "key_version": "v1",
        "record_hmac": digest(),
        "expires_at": later(30),
    } | override


def standalone_incident(connection: Connection, kind: str = "sms") -> tuple[UUID, UUID]:
    """A complete, valid standalone incident; returns (incident_id, event_id)."""
    event_id = add(connection, Event, event(kind))
    incident_id = add(connection, Incident, incident("standalone"))
    add(
        connection,
        IncidentEvent,
        {"incident_id": incident_id, "event_id": event_id, "channel": kind},
    )
    add(connection, Assessment, assessment(incident_id))
    return incident_id, event_id


def check_deferred_now(connection: Connection) -> None:
    """Run deferred constraints and triggers immediately instead of waiting for COMMIT."""
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def violated_constraint(error: pytest.ExceptionInfo[IntegrityError]) -> str | None:
    # psycopg exposes the server's diagnostics, including the constraint that was violated.
    diagnostics = getattr(error.value.orig, "diag", None)
    return getattr(diagnostics, "constraint_name", None)
