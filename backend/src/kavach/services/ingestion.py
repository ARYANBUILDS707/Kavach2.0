"""Authenticated SMS/call event ingestion with transactional PostgreSQL idempotency (M3.1).

Idempotency (API.md "Event requests and receipts"): the canonical validated payload is
fingerprinted with a versioned HMAC. `(source, external_event_id)` is unique in PostgreSQL:
the first committed insert wins (201); a later request with the same fingerprint is a replay
(200, original receipt); a different fingerprint is a conflict (409). Redis is not involved.

Models (M4-I.2, docs/M4_SMS_INFERENCE_ARCHITECTURE.md §6.4 and §9):
- Without an SMS classifier every model stage is recorded as unavailable with a reason, scores
  stay null, and the standalone incident's assessment has tier `unknown` (signals version 1,
  unchanged).
- With the pretrained SMS worker enabled:
  - the SMS text is classified **after** the replay/conflict lookup and **outside** any
    transaction;
  - no admission slot, or a starting worker, raises `AnalysisRejected` before anything is stored
    (429/503, retried with the same event ID);
  - a completed or failed inference is stored as a signals version 2 stage.
- Model evidence is uncalibrated: `sms_score` stays null and the tier stays `unknown`.

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
from kavach.models.sms_worker import SmsInferenceResult, SmsWorkerSupervisor
from kavach.privacy.audit import AuditWriter
from kavach.privacy.digests import KeyedDigester, UnknownKeyVersion

UNREACHABLE = (OperationalError, InterfaceError)
QUERY_CANCELED = "57014"  # statement_timeout fired: the request deadline was reached
DEFAULT_DEADLINE_SECONDS = 30.0
POLICY_VERSION = "kavach-m3.1-no-models"
SIGNALS_SCHEMA_VERSION = 1
# Signals written while the SMS worker is enabled (design §9); version 1 rows stay as they are.
SMS_POLICY_VERSION = "kavach-m4-uncalibrated-sms-evidence"
SMS_SIGNALS_SCHEMA_VERSION = 2
SMS_STAGE = "sms_classifier"
UNCALIBRATED = "uncalibrated_softmax"
SMS_STAGE_KEYS = {"status", "reason", "duration_ms"}
SMS_OUTPUT_KEYS = {"labels", "top_label", "score_semantics", "truncated"}
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


class AnalysisRejected(Exception):
    """Inference could not be admitted (no free slot, or the worker is starting or restarting).
    Nothing was stored: the client retries with the same event ID and gets a fresh analysis."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

    @property
    def saturated(self) -> bool:
        return self.reason == "inference_saturated"


@dataclass(frozen=True)
class Analysis:
    """Everything the event and its standalone assessment store about model stages."""

    signals: dict[str, Any]
    model_versions: dict[str, str]
    analysis_status: str  # of the event
    assessment_status: str
    assessment_reasons: list[str]
    assessment_extra: dict[str, Any]
    policy_version: str


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
    # Filled only for an admin browser submission (MVP-B4); ingestors never see incidents.
    incident_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class SessionSubmitter:
    """An admin submitting from the browser session (MVP-B4). Audited as the user."""

    user_id: UUID
    source: str = "simulator"


Submitter = IngestPrincipal | SessionSubmitter


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
    """Receipt warnings, derived from what was stored, so a replay repeats them exactly."""
    stages = signals.get("stages", {})
    warnings = [
        f"{name.upper()}_UNAVAILABLE"
        for name, stage in sorted(stages.items())
        if stage.get("status") != "complete"
    ]
    sms = stages.get(SMS_STAGE, {})
    if (
        sms.get("status") == "complete"
        and sms.get("model_output", {}).get("score_semantics") == UNCALIBRATED
    ):
        warnings.append("SMS_SCORE_UNCALIBRATED")
    return warnings


def no_model_analysis(event: Event) -> Analysis:
    """The M3 behaviour, unchanged: every model stage unavailable, signals version 1."""
    stages = unavailable_stages(event)
    return Analysis(
        signals={"schema_version": SIGNALS_SCHEMA_VERSION, "stages": stages, "reason_codes": []},
        model_versions={},
        analysis_status="unavailable",
        assessment_status="unavailable",
        assessment_reasons=["no_base_signal_available"],
        assessment_extra={},
        policy_version=POLICY_VERSION,
    )


def sms_analysis(result: SmsInferenceResult) -> Analysis:
    """Signals version 2 for an SMS whose inference completed or failed (never rejected).

    Model evidence keeps the native labels and uncalibrated scores. It never becomes
    `sms_score`, base risk or a tier (D04-A1).
    """
    duration = result.model_ms or 0
    if result.outcome == "complete" and result.evidence is not None:
        evidence = result.evidence
        output = {
            "labels": dict(evidence.labels),
            "top_label": evidence.top_label,
            "score_semantics": evidence.score_semantics,
            "truncated": evidence.truncated,
        }
        stage = {
            "status": "complete",
            "reason": None,
            "duration_ms": duration,
            "model_output": output,
        }
        signals = {
            "schema_version": SMS_SIGNALS_SCHEMA_VERSION,
            "stages": {SMS_STAGE: stage},
            "reason_codes": ["sms_model_uncalibrated"],
        }
        versions = {SMS_STAGE: evidence.model_version}
        check_sms_signals(signals)
        return Analysis(
            signals=signals,
            model_versions=versions,
            analysis_status="complete",
            assessment_status="partial",
            assessment_reasons=["sms_model_uncalibrated", "no_calibrated_base_signal"],
            assessment_extra={
                "sms_model_evidence": output | {"model_version": evidence.model_version}
            },
            policy_version=SMS_POLICY_VERSION,
        )
    if result.outcome != "unavailable" or not result.reason:
        raise ValueError("A rejected or malformed result cannot be stored")
    stage = {"status": "unavailable", "reason": result.reason, "duration_ms": duration}
    signals = {
        "schema_version": SMS_SIGNALS_SCHEMA_VERSION,
        "stages": {SMS_STAGE: stage},
        "reason_codes": [],
    }
    check_sms_signals(signals)
    return Analysis(
        signals=signals,
        model_versions={},
        analysis_status="unavailable",
        assessment_status="unavailable",
        assessment_reasons=["no_base_signal_available"],
        assessment_extra={},
        policy_version=SMS_POLICY_VERSION,
    )


def check_sms_signals(signals: Mapping[str, Any]) -> None:
    """Service-boundary allowlist for signals version 2 (DATABASE.md): fixed keys, numbers and
    codes only. Anything else is a programming error, never stored."""
    if set(signals) != {"schema_version", "stages", "reason_codes"}:
        raise ValueError("signals keys")
    if signals["schema_version"] != SMS_SIGNALS_SCHEMA_VERSION or set(signals["stages"]) != {
        SMS_STAGE
    }:
        raise ValueError("signals stages")
    stage = signals["stages"][SMS_STAGE]
    complete = stage.get("status") == "complete"
    if set(stage) != SMS_STAGE_KEYS | ({"model_output"} if complete else set()):
        raise ValueError("stage keys")
    if not isinstance(stage["duration_ms"], int) or stage["duration_ms"] < 0:
        raise ValueError("stage duration")
    if not complete:
        if stage["status"] != "unavailable" or not isinstance(stage["reason"], str):
            raise ValueError("stage status")
        return
    output = stage["model_output"]
    if set(output) != SMS_OUTPUT_KEYS or output["score_semantics"] != UNCALIBRATED:
        raise ValueError("model output keys")
    labels = output["labels"]
    if not labels or not all(
        isinstance(k, str) and isinstance(v, float) and 0.0 <= v <= 1.0 for k, v in labels.items()
    ):
        raise ValueError("model output labels")
    if output["top_label"] not in labels or not isinstance(output["truncated"], bool):
        raise ValueError("model output fields")


def audit_actor(submitter: Submitter) -> dict[str, Any]:
    """The audit actor for an accepted event: the ingestion key, or the admin user."""
    if isinstance(submitter, SessionSubmitter):
        return {"actor_kind": "user", "actor_user_id": submitter.user_id}
    return {"actor_kind": "ingestor", "actor_ingest_key_id": submitter.key_id}


def receipt_from(
    record: repo.EventRecord, *, replayed: bool, incident_ids: tuple[UUID, ...] = ()
) -> Receipt:
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
        incident_ids=incident_ids,
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
        sms_classifier: SmsWorkerSupervisor | None = None,
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
        # None: no model path at all (M3 behaviour). Otherwise every SMS goes through it.
        self.sms_classifier = sms_classifier

    def ingest(
        self, event: Event, submitter: Submitter, request_id: UUID, started: float
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
        wants_incidents = isinstance(submitter, SessionSubmitter)
        try:
            with self.sessions.begin() as db:
                repo.set_local_statement_timeout(db, remaining_ms(deadline))
                existing = repo.find_event(db, event.source, event.event_id)
                incidents = (
                    repo.incident_ids_for_event(db, existing.id)
                    if existing is not None and wants_incidents
                    else ()
                )
            if existing is not None:
                return self._replay(existing, canonical, request_id, incidents)

            subscriber = self.subscriber_digests.digest(event.subscriber_token.encode())
            # Analysis runs here, outside any transaction and before anything is stored.
            analysis = self._analyze(event, deadline, request_id)
            stages = analysis.signals["stages"]
            now = self.clock()
            expires_at = now + self.retention
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
                        "analysis_status": analysis.analysis_status,
                        "signals": analysis.signals,
                        "model_versions": analysis.model_versions,
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
                            "schema_version": analysis.signals["schema_version"],
                            "event_ids": [str(event_id)],
                            "signal_status": {name: s["status"] for name, s in stages.items()},
                            "reasons": analysis.assessment_reasons,
                        }
                        | analysis.assessment_extra,
                        policy_version=analysis.policy_version,
                        analysis_status=analysis.assessment_status,
                        model_versions=analysis.model_versions,
                    )
                    self.audit.record(
                        db,
                        **audit_actor(submitter),
                        action="event.ingest",
                        resource_type="event",
                        resource_id=event_id,
                        request_id=request_id,
                        now=now,
                    )
                stored = repo.find_event(db, event.source, event.event_id)
                incidents = (
                    repo.incident_ids_for_event(db, stored.id)
                    if stored is not None and wants_incidents
                    else ()
                )
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
            return self._replay(stored, canonical, request_id, incidents)
        # Committed: from here on the outcome is success, whatever Redis does.
        self._index(stored, request_id, now)
        return receipt_from(stored, replayed=False, incident_ids=incidents)

    def _analyze(self, event: Event, deadline: float, request_id: UUID) -> Analysis:
        if not isinstance(event, SMSEvent) or self.sms_classifier is None:
            return no_model_analysis(event)
        result = self.sms_classifier.classify(event.text, deadline)
        if result.outcome == "rejected":
            operational_event("ingest.analysis_rejected", result.reason or "rejected", request_id)
            raise AnalysisRejected(result.reason or "worker_busy")
        if result.outcome == "unavailable":
            operational_event("ingest.analysis_unavailable", result.reason or "", request_id)
        return sms_analysis(result)

    def _index(self, record: repo.EventRecord, request_id: UUID, now: datetime) -> None:
        """Best effort after commit; PostgreSQL stays authoritative and `rebuild` recovers.

        `now` (not the original arrival) decides indexability, so a late replay never brings
        back a candidate that is already outside the 40-minute horizon.
        """
        if self.candidates is None:
            return
        try:
            evicted = self.candidates.add(
                identity_key_version=record.identity_key_version,
                subscriber_digest=record.subscriber_digest,
                event_id=record.id,
                kind=record.kind,
                event_time=record.event_time,
                received_at=now,
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

    def _replay(
        self,
        existing: repo.EventRecord,
        canonical: bytes,
        request_id: UUID,
        incident_ids: tuple[UUID, ...] = (),
    ) -> Receipt:
        try:
            same = self.payload_digests.matches(
                canonical, existing.payload_digest, existing.payload_key_version
            )
        except UnknownKeyVersion:
            # Retired PAYLOAD_HMAC_KEYS versions must stay configured for the retention window;
            # without it neither replay nor conflict can be decided (500, nothing changes).
            operational_event(
                "ingest.payload_key_missing", "key_version_not_configured", request_id
            )
            raise
        if same:
            # Re-indexing is idempotent; it repairs an earlier deferred index write.
            self._index(existing, request_id, self.clock())
            return receipt_from(existing, replayed=True, incident_ids=incident_ids)
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
