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
from kavach.core.telemetry import operational_event, security_event
from kavach.correlation.candidates import (
    CANDIDATE_HORIZON,
    CandidateIndex,
    CandidateIndexUnavailable,
)
from kavach.db import event_repository as repo
from kavach.privacy.audit import AuditWriter
from kavach.privacy.digests import KeyedDigester

UNREACHABLE = (OperationalError, InterfaceError)
QUERY_CANCELED = "57014"  # statement_timeout fired: the request deadline was reached
DEFAULT_DEADLINE_SECONDS = 30.0
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


class ProcessingTimeout(Exception):
    """The request deadline passed before commit; nothing was stored (retry is safe)."""


def remaining_ms(deadline: float) -> int:
    remaining = int((deadline - time.monotonic()) * 1000)
    if remaining <= 0:
        raise ProcessingTimeout
    return remaining


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
        deadline: float = DEFAULT_DEADLINE_SECONDS,
        candidates: CandidateIndex | None = None,
    ) -> None:
        self.sessions = sessions
        self.subscriber_digests = subscriber_digests
        self.payload_digests = payload_digests
        self.audit = audit
        self.clock = clock
        self.retention = retention
        # Total request deadline in seconds (INFERENCE_TIMEOUT_SECONDS, D08: 30).
        self.deadline = deadline
        self.candidates = candidates

    def ingest(
        self, event: Event, principal: IngestPrincipal, request_id: UUID, started: float
    ) -> Receipt:
        """`started` is the request's time.monotonic(); past the deadline nothing is committed.

        A connection lost while committing is reported as 503 although the commit may have
        succeeded; the client resolves that by retrying the same event ID (200 replay) or by
        reading the receipt, as API.md specifies.
        """
        deadline = started + self.deadline
        if isinstance(event, CallEvent) and event.audio_reference is not None:
            if event.audio_reference not in APPROVED_AUDIO_REFERENCES:
                raise UnknownAudioReference
        canonical = canonical_payload(event)
        try:
            with self.sessions.begin() as db:
                repo.set_local_statement_timeout(db, remaining_ms(deadline))
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
                repo.set_local_statement_timeout(db, remaining_ms(deadline))
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
                if time.monotonic() >= deadline:
                    # Roll back rather than commit after the deadline (API.md: 503, no result).
                    raise ProcessingTimeout
        except OperationalError as error:
            if getattr(error.orig, "sqlstate", None) == QUERY_CANCELED:
                raise ProcessingTimeout from None
            raise IngestionUnavailable from None
        except InterfaceError:
            raise IngestionUnavailable from None
        if stored is None:
            raise RuntimeError("An event row vanished while it was being ingested")
        if event_id is None:
            # Another request committed this event ID first: replay or conflict against it.
            return self._replay(stored, canonical, request_id)
        # Committed: from here on the outcome is success, whatever Redis does.
        self._index(stored, request_id)
        return receipt_from(stored, replayed=False)

    def _index(self, record: repo.EventRecord, request_id: UUID) -> None:
        """Best effort after commit; PostgreSQL stays authoritative and `rebuild` recovers."""
        if self.candidates is None:
            return
        try:
            evicted = self.candidates.add(
                identity_key_version=record.identity_key_version,
                subscriber_digest=record.subscriber_digest,
                event_id=record.id,
                kind=record.kind,
                event_time=record.event_time,
                received_at=record.received_at,
            )
        except CandidateIndexUnavailable:
            operational_event("candidate.index_deferred", "redis_unavailable", request_id)
            return
        if evicted:
            operational_event("candidate.index_capped", "per_subscriber_cap", request_id)

    def rebuild_candidates(self) -> int:
        if self.candidates is None:
            raise RuntimeError("No candidate index is configured")
        return rebuild_candidate_index(self.sessions, self.candidates, self.clock)

    def _replay(self, existing: repo.EventRecord, canonical: bytes, request_id: UUID) -> Receipt:
        if self.payload_digests.matches(
            canonical, existing.payload_digest, existing.payload_key_version
        ):
            # Re-indexing is idempotent; it repairs an earlier deferred index write.
            self._index(existing, request_id)
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


def rebuild_candidate_index(
    sessions: sessionmaker[Session], candidates: CandidateIndex, clock: Clock
) -> int:
    """Re-add every event still inside the candidate horizon from PostgreSQL (idempotent).

    Recovers index writes deferred by a Redis outage; returns how many events were indexed.
    """
    now = clock()
    with sessions.begin() as db:
        records = repo.events_since(db, now - CANDIDATE_HORIZON)
    for record in records:
        candidates.add(
            identity_key_version=record.identity_key_version,
            subscriber_digest=record.subscriber_digest,
            event_id=record.id,
            kind=record.kind,
            event_time=record.event_time,
            received_at=now,
        )
    return len(records)
