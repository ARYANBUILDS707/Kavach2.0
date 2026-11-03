"""Authenticated SMS/call event ingestion with transactional PostgreSQL idempotency (M3.1).

Idempotency (API.md "Event requests and receipts"): the canonical validated payload is
fingerprinted with a versioned HMAC. `(source, external_event_id)` is unique in PostgreSQL:
the first committed insert wins (201); a later request with the same fingerprint is a replay
(200, original receipt); a different fingerprint is a conflict (409). Redis is not involved.

No inference models exist yet: every model stage is recorded as unavailable with a reason,
scores stay null, and the standalone incident's assessment has tier `unknown`.
Raw SMS text, sender IDs and subscriber tokens are never stored; only keyed digests are.
"""

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from kavach.api.schemas.events import CallEvent, SMSEvent
from kavach.auth.ingest_keys import IngestPrincipal
from kavach.core.clock import Clock
from kavach.core.telemetry import security_event
from kavach.db import event_repository as repo
from kavach.privacy.audit import AuditWriter
from kavach.privacy.digests import KeyedDigester

UNREACHABLE = (OperationalError, InterfaceError)
POLICY_VERSION = "kavach-m3.1-no-models"
SIGNALS_SCHEMA_VERSION = 1
# No controlled audio sample manifest is approved yet, so every non-null reference is unknown.
APPROVED_AUDIO_REFERENCES: frozenset[str] = frozenset()

Event = SMSEvent | CallEvent


class EventIdConflict(Exception):
    """The event ID was already used by this source with a different payload."""


class UnknownAudioReference(Exception):
    """The call names a sample that is not in the approved manifest."""


class IngestionUnavailable(Exception):
    """PostgreSQL could not be reached; nothing was stored."""


@dataclass(frozen=True)
class Receipt:
    event_id: UUID
    external_event_id: str
    source: str
    kind: str
    analysis_status: str
    received_at: datetime
    processing_ms: int
    replayed: bool
    warnings: list[str]


def canonical_payload(event: Event) -> bytes:
    """Deterministic bytes for the validated request.

    Timestamps are normalized to UTC with microseconds and absent optional fields become null,
    so equivalent requests match; text is kept exactly, so any wording change is a conflict.
    """
    fields = event.model_dump()
    fields["timestamp"] = event.timestamp.astimezone(UTC).isoformat(timespec="microseconds")
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def unavailable_stages(event: Event) -> dict[str, dict[str, Any]]:
    if isinstance(event, SMSEvent):
        stages, reason = ("sms_classifier",), "model_not_deployed"
    else:
        stages = ("transcription", "voice_intent", "synthesis")
        reason = "audio_not_provided" if event.audio_reference is None else "model_not_deployed"
    return {
        stage: {"status": "unavailable", "reason": reason, "duration_ms": 0} for stage in stages
    }


def warnings_from(signals: Mapping[str, Any]) -> list[str]:
    stages = signals.get("stages", {})
    return [
        f"{name.upper()}_UNAVAILABLE"
        for name, stage in sorted(stages.items())
        if stage.get("status") != "complete"
    ]


def receipt_from(record: repo.EventRecord, *, replayed: bool) -> Receipt:
    return Receipt(
        event_id=record.id,
        external_event_id=record.external_event_id,
        source=record.source,
        kind=record.kind,
        analysis_status=record.analysis_status,
        received_at=record.received_at,
        processing_ms=record.processing_ms,
        replayed=replayed,
        warnings=warnings_from(record.signals),
    )


class IngestionService:
    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        subscriber_digests: KeyedDigester,
        payload_digests: KeyedDigester,
        audit: AuditWriter,
        clock: Clock,
        retention: timedelta,
    ) -> None:
        self.sessions = sessions
        self.subscriber_digests = subscriber_digests
        self.payload_digests = payload_digests
        self.audit = audit
        self.clock = clock
        self.retention = retention

    def ingest(
        self, event: Event, principal: IngestPrincipal, request_id: UUID, started: float
    ) -> Receipt:
        if isinstance(event, CallEvent) and event.audio_reference is not None:
            if event.audio_reference not in APPROVED_AUDIO_REFERENCES:
                raise UnknownAudioReference
        canonical = canonical_payload(event)
        try:
            with self.sessions.begin() as db:
                existing = repo.find_event(db, event.source, event.event_id)
            if existing is not None:
                return self._replay(existing, canonical, request_id)

            subscriber = self.subscriber_digests.digest(event.subscriber_token.encode())
            stages = unavailable_stages(event)
            now = self.clock()
            expires_at = now + self.retention
            # Analysis would run here, outside any transaction; no models are deployed yet.
            processing_ms = max(0, int((time.monotonic() - started) * 1000))
            with self.sessions.begin() as db:
                repo.lock_subscriber(db, subscriber)
                event_id = repo.insert_event_if_absent(
                    db,
                    {
                        "source": event.source,
                        "external_event_id": event.event_id,
                        "kind": event.kind,
                        "subscriber_digest": subscriber,
                        "identity_key_version": self.subscriber_digests.active_version,
                        "payload_digest": self.payload_digests.digest(canonical),
                        "payload_key_version": self.payload_digests.active_version,
                        "event_time": event.timestamp,
                        "received_at": now,
                        "analysis_status": "unavailable",
                        "signals": {
                            "schema_version": SIGNALS_SCHEMA_VERSION,
                            "stages": stages,
                            "reason_codes": [],
                        },
                        "model_versions": {},
                        "processing_ms": processing_ms,
                        "expires_at": expires_at,
                    },
                )
                if event_id is not None:
                    repo.insert_standalone_incident(
                        db,
                        event_id=event_id,
                        kind=event.kind,
                        occurred_at=event.timestamp,
                        now=now,
                        expires_at=expires_at,
                        evidence={
                            "schema_version": SIGNALS_SCHEMA_VERSION,
                            "event_ids": [str(event_id)],
                            "signal_status": {name: s["status"] for name, s in stages.items()},
                            "reasons": ["no_base_signal_available"],
                        },
                        policy_version=POLICY_VERSION,
                    )
                    self.audit.record(
                        db,
                        actor_kind="ingestor",
                        actor_ingest_key_id=principal.key_id,
                        action="event.ingest",
                        resource_type="event",
                        resource_id=event_id,
                        request_id=request_id,
                        now=now,
                    )
                stored = repo.find_event(db, event.source, event.event_id)
        except UNREACHABLE:
            raise IngestionUnavailable from None
        if stored is None:
            raise RuntimeError("An event row vanished while it was being ingested")
        if event_id is None:
            # Another request committed this event ID first: replay or conflict against it.
            return self._replay(stored, canonical, request_id)
        return receipt_from(stored, replayed=False)

    def _replay(self, existing: repo.EventRecord, canonical: bytes, request_id: UUID) -> Receipt:
        if self.payload_digests.matches(
            canonical, existing.payload_digest, existing.payload_key_version
        ):
            return receipt_from(existing, replayed=True)
        security_event("ingest.event_conflict", "payload_mismatch", request_id)
        raise EventIdConflict

    def receipt(self, event_id: UUID, principal: IngestPrincipal) -> Receipt | None:
        """The receipt if this key's source owns the event; otherwise None (same as missing)."""
        try:
            with self.sessions.begin() as db:
                record = repo.find_event_for_source(db, event_id, principal.source)
        except UNREACHABLE:
            raise IngestionUnavailable from None
        return receipt_from(record, replayed=False) if record else None
