"""DATABASE.md constraints against real PostgreSQL. Each case breaks exactly one rule.

All inserts run as the runtime role (kavach_app) inside a transaction that is rolled back.
"""

import math
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError

from kavach.db.models import (
    Assessment,
    AuditRecord,
    Event,
    Incident,
    IncidentEvent,
    IngestKey,
    Review,
    User,
    UserSession,
)

from . import schema_rows as rows
from .schema_rows import add, check_deferred_now, violated_constraint

pytestmark = pytest.mark.integration


def assert_rejected(connection: Connection, constraint: str, model: Any, values: Any) -> None:
    # A savepoint keeps the surrounding transaction usable after the expected failure.
    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            connection.execute(insert(model).values(**values))
            check_deferred_now(connection)
    assert violated_constraint(error) == constraint


# --- users, sessions, ingest keys ---------------------------------------------------------


@pytest.mark.parametrize(
    ("override", "constraint"),
    [
        ({"username": "Mixed_Case"}, "ck_users_username_canonical"),
        ({"username": ""}, "ck_users_username_canonical"),
        ({"role": "superuser"}, "ck_users_role"),
    ],
)
def test_user_checks(runtime_tx: Connection, override: dict[str, Any], constraint: str) -> None:
    assert_rejected(runtime_tx, constraint, User, rows.user(**override))


def test_username_is_unique(runtime_tx: Connection) -> None:
    add(runtime_tx, User, rows.user(username="duplicate"))
    assert_rejected(runtime_tx, "uq_users_username", User, rows.user(username="duplicate"))


def test_users_updated_at_is_maintained_by_the_server(runtime_tx: Connection) -> None:
    old = datetime(2001, 1, 1, tzinfo=UTC)
    user_id = add(runtime_tx, User, rows.user(updated_at=old))
    runtime_tx.execute(update(User).where(User.id == user_id).values(display_name="Renamed"))
    updated_at, now = runtime_tx.execute(
        select(User.updated_at, func.now()).where(User.id == user_id)
    ).one()
    assert updated_at == now != old


@pytest.mark.parametrize(
    ("override", "constraint"),
    [
        ({"token_digest": b"short"}, "ck_sessions_token_digest_length"),
        ({"csrf_digest": b"x" * 33}, "ck_sessions_csrf_digest_length"),
    ],
)
def test_session_checks(runtime_tx: Connection, override: dict[str, Any], constraint: str) -> None:
    user_id = add(runtime_tx, User, rows.user())
    assert_rejected(runtime_tx, constraint, UserSession, rows.user_session(user_id, **override))


def test_session_token_digest_is_unique(runtime_tx: Connection) -> None:
    user_id = add(runtime_tx, User, rows.user())
    token = rows.digest()
    add(runtime_tx, UserSession, rows.user_session(user_id, token_digest=token))
    assert_rejected(
        runtime_tx,
        "uq_sessions_token_digest",
        UserSession,
        rows.user_session(user_id, token_digest=token),
    )


def test_session_requires_an_existing_user(runtime_tx: Connection) -> None:
    missing = rows.uuid4()
    assert_rejected(
        runtime_tx, "fk_sessions_user_id_users", UserSession, rows.user_session(missing)
    )


def test_ingest_key_requires_an_existing_creator(runtime_tx: Connection) -> None:
    assert_rejected(
        runtime_tx,
        "fk_ingest_keys_created_by_users",
        IngestKey,
        rows.ingest_key(rows.uuid4()),
    )


def test_ingest_key_digest_is_32_bytes_and_unique(runtime_tx: Connection) -> None:
    user_id = add(runtime_tx, User, rows.user())
    key = rows.digest()
    add(runtime_tx, IngestKey, rows.ingest_key(user_id, key_digest=key))
    with pytest.raises(IntegrityError) as error:
        runtime_tx.execute(insert(IngestKey).values(**rows.ingest_key(user_id, key_digest=key)))
    assert violated_constraint(error) == "uq_ingest_keys_key_digest"


def test_ingest_key_digest_length(runtime_tx: Connection) -> None:
    user_id = add(runtime_tx, User, rows.user())
    assert_rejected(
        runtime_tx,
        "ck_ingest_keys_key_digest_length",
        IngestKey,
        rows.ingest_key(user_id, key_digest=b"\x00" * 16),
    )


# --- events ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "override", "constraint"),
    [
        ("sms", {"synthesis_score": 0.5}, "ck_events_kind_scores"),
        ("sms", {"voice_intent_score": 0.5}, "ck_events_kind_scores"),
        ("call", {"sms_score": 0.5}, "ck_events_kind_scores"),
        ("sms", {"sms_score": 1.5}, "ck_events_sms_score_range"),
        ("sms", {"sms_score": -0.01}, "ck_events_sms_score_range"),
        ("sms", {"sms_score": math.nan}, "ck_events_sms_score_range"),
        ("call", {"voice_intent_score": math.inf}, "ck_events_voice_intent_score_range"),
        ("call", {"synthesis_score": -math.inf}, "ck_events_synthesis_score_range"),
        ("email", {}, "ck_events_kind"),
        ("sms", {"analysis_status": "safe"}, "ck_events_analysis_status"),
        ("sms", {"processing_ms": -1}, "ck_events_processing_ms_non_negative"),
        ("sms", {"subscriber_digest": b"+15550100"}, "ck_events_subscriber_digest_length"),
        ("sms", {"payload_digest": b""}, "ck_events_payload_digest_length"),
        ("sms", {"signals": ["not", "an", "object"]}, "ck_events_signals_shape"),
        ("sms", {"signals": {"pad": "x" * 16_400}}, "ck_events_signals_shape"),
        ("sms", {"model_versions": {"pad": "x" * 4_100}}, "ck_events_model_versions_shape"),
    ],
)
def test_event_checks(
    runtime_tx: Connection, kind: str, override: dict[str, Any], constraint: str
) -> None:
    assert_rejected(runtime_tx, constraint, Event, rows.event(kind, **override))


def test_event_scores_accept_the_unit_interval_and_null(runtime_tx: Connection) -> None:
    add(runtime_tx, Event, rows.event("sms", sms_score=0.0))
    add(runtime_tx, Event, rows.event("sms", sms_score=1.0))
    add(runtime_tx, Event, rows.event("call", voice_intent_score=None, synthesis_score=0.9))
    check_deferred_now(runtime_tx)


def test_event_is_unique_per_source_and_external_id(runtime_tx: Connection) -> None:
    add(runtime_tx, Event, rows.event(external_event_id="retry-1"))
    assert_rejected(
        runtime_tx,
        "uq_events_source_external_event_id",
        Event,
        rows.event(external_event_id="retry-1"),
    )
    # The same external ID from a different source is a different event.
    add(runtime_tx, Event, rows.event(external_event_id="retry-1", source="other-source"))


# --- incidents, links and assessments -----------------------------------------------------


@pytest.mark.parametrize(
    ("override", "constraint"),
    [
        ({"kind": "cluster"}, "ck_incidents_kind"),
        ({"current_revision": 0}, "ck_incidents_current_revision_positive"),
        ({"version": 0}, "ck_incidents_version_positive"),
    ],
)
def test_incident_checks(runtime_tx: Connection, override: dict[str, Any], constraint: str) -> None:
    assert_rejected(runtime_tx, constraint, Incident, rows.incident(**override))


def test_incident_key_is_unique(runtime_tx: Connection) -> None:
    incident_id, _ = rows.standalone_incident(runtime_tx)
    key = runtime_tx.execute(
        select(Incident.incident_key).where(Incident.id == incident_id)
    ).scalar_one()
    assert_rejected(
        runtime_tx, "uq_incidents_incident_key", Incident, rows.incident(incident_key=key)
    )


def test_deferral_lets_an_incident_precede_its_assessment(runtime_tx: Connection) -> None:
    # Inserted in an order that an immediate foreign key would reject.
    rows.standalone_incident(runtime_tx)
    check_deferred_now(runtime_tx)


def test_incident_requires_its_current_assessment(runtime_tx: Connection) -> None:
    event_id = add(runtime_tx, Event, rows.event("sms"))
    incident_id = add(runtime_tx, Incident, rows.incident())
    add(
        runtime_tx,
        IncidentEvent,
        {"incident_id": incident_id, "event_id": event_id, "channel": "sms"},
    )
    with pytest.raises(IntegrityError) as error:
        check_deferred_now(runtime_tx)
    assert violated_constraint(error) == "fk_incidents_id_current_revision_assessments"


def test_latest_review_must_belong_to_the_same_incident(runtime_tx: Connection) -> None:
    analyst = add(runtime_tx, User, rows.user())
    first, _ = rows.standalone_incident(runtime_tx)
    second, _ = rows.standalone_incident(runtime_tx)
    other_review = add(runtime_tx, Review, rows.review(second, analyst))
    runtime_tx.execute(
        update(Incident)
        .where(Incident.id == first)
        .values(latest_review_id=other_review, version=2)
    )
    with pytest.raises(IntegrityError) as error:
        check_deferred_now(runtime_tx)
    assert violated_constraint(error) == "fk_incidents_id_latest_review_id_reviews"


def link(connection: Connection, incident_id: Any, event_id: Any, channel: str) -> None:
    add(
        connection,
        IncidentEvent,
        {"incident_id": incident_id, "event_id": event_id, "channel": channel},
    )


def test_link_channel_must_match_the_event_kind(runtime_tx: Connection) -> None:
    event_id = add(runtime_tx, Event, rows.event("sms"))
    incident_id = add(runtime_tx, Incident, rows.incident())
    add(runtime_tx, Assessment, rows.assessment(incident_id))
    link(runtime_tx, incident_id, event_id, "call")
    with pytest.raises(IntegrityError) as error:
        check_deferred_now(runtime_tx)
    assert violated_constraint(error) == "incident_events_channel_matches_kind"


def test_standalone_incident_needs_exactly_one_event(runtime_tx: Connection) -> None:
    incident_id = add(runtime_tx, Incident, rows.incident())
    add(runtime_tx, Assessment, rows.assessment(incident_id))
    with pytest.raises(IntegrityError) as error:
        check_deferred_now(runtime_tx)
    assert violated_constraint(error) == "incident_membership_cardinality"


def test_standalone_incident_cannot_link_two_events(runtime_tx: Connection) -> None:
    incident_id, _ = rows.standalone_incident(runtime_tx, "sms")
    link(runtime_tx, incident_id, add(runtime_tx, Event, rows.event("call")), "call")
    with pytest.raises(IntegrityError) as error:
        check_deferred_now(runtime_tx)
    assert violated_constraint(error) == "incident_membership_cardinality"


def pair_incident(connection: Connection, call_subscriber: bytes = rows.SUBSCRIBER_A) -> Any:
    sms_id = add(connection, Event, rows.event("sms"))
    call_id = add(connection, Event, rows.event("call", subscriber_digest=call_subscriber))
    incident_id = add(connection, Incident, rows.incident("pair"))
    link(connection, incident_id, sms_id, "sms")
    link(connection, incident_id, call_id, "call")
    return incident_id


def test_valid_pair_with_fusion_score(runtime_tx: Connection) -> None:
    incident_id = pair_incident(runtime_tx)
    add(
        runtime_tx,
        Assessment,
        rows.assessment(
            incident_id,
            base_score=0.41,
            fusion_score=0.77,
            final_score=0.77,
            tier="high",
            analysis_status="complete",
        ),
    )
    check_deferred_now(runtime_tx)


def test_pair_needs_one_sms_and_one_call(runtime_tx: Connection) -> None:
    incident_id = add(runtime_tx, Incident, rows.incident("pair"))
    add(runtime_tx, Assessment, rows.assessment(incident_id))
    link(runtime_tx, incident_id, add(runtime_tx, Event, rows.event("sms")), "sms")
    with pytest.raises(IntegrityError) as error:
        check_deferred_now(runtime_tx)
    assert violated_constraint(error) == "incident_membership_cardinality"


def test_pair_events_must_share_the_subscriber(runtime_tx: Connection) -> None:
    incident_id = pair_incident(runtime_tx, call_subscriber=rows.SUBSCRIBER_B)
    add(runtime_tx, Assessment, rows.assessment(incident_id))
    with pytest.raises(IntegrityError) as error:
        check_deferred_now(runtime_tx)
    assert violated_constraint(error) == "incident_membership_same_subscriber"


def test_pair_events_must_share_the_identity_key_version(runtime_tx: Connection) -> None:
    sms_id = add(runtime_tx, Event, rows.event("sms"))
    call_id = add(runtime_tx, Event, rows.event("call", identity_key_version="v2"))
    incident_id = add(runtime_tx, Incident, rows.incident("pair"))
    link(runtime_tx, incident_id, sms_id, "sms")
    link(runtime_tx, incident_id, call_id, "call")
    add(runtime_tx, Assessment, rows.assessment(incident_id))
    with pytest.raises(IntegrityError) as error:
        check_deferred_now(runtime_tx)
    assert violated_constraint(error) == "incident_membership_same_subscriber"


def test_one_link_per_channel(runtime_tx: Connection) -> None:
    incident_id = pair_incident(runtime_tx)
    with pytest.raises(IntegrityError) as error:
        link(runtime_tx, incident_id, add(runtime_tx, Event, rows.event("sms")), "sms")
    assert violated_constraint(error) == "uq_incident_events_incident_id_channel"


def test_link_requires_an_existing_event(runtime_tx: Connection) -> None:
    incident_id = add(runtime_tx, Incident, rows.incident())
    with pytest.raises(IntegrityError) as error:
        link(runtime_tx, incident_id, rows.uuid4(), "sms")
    assert violated_constraint(error) == "fk_incident_events_event_id_events"


def test_standalone_incident_cannot_carry_a_fusion_score(runtime_tx: Connection) -> None:
    event_id = add(runtime_tx, Event, rows.event("sms"))
    incident_id = add(runtime_tx, Incident, rows.incident())
    link(runtime_tx, incident_id, event_id, "sms")
    add(
        runtime_tx,
        Assessment,
        rows.assessment(incident_id, fusion_score=0.6, final_score=0.6, tier="medium"),
    )
    with pytest.raises(IntegrityError) as error:
        check_deferred_now(runtime_tx)
    assert violated_constraint(error) == "assessments_fusion_only_for_pairs"


@pytest.mark.parametrize(
    ("override", "constraint"),
    [
        ({"tier": "unknown", "final_score": 0.2}, "ck_assessments_tier_final_score"),
        ({"tier": "high", "final_score": None}, "ck_assessments_tier_final_score"),
        ({"tier": "severe"}, "ck_assessments_tier"),
        ({"analysis_status": "done"}, "ck_assessments_analysis_status"),
        ({"base_score": 2.0}, "ck_assessments_base_score_range"),
        ({"final_score": math.nan, "tier": "low"}, "ck_assessments_final_score_range"),
        ({"revision": 0}, "ck_assessments_revision_positive"),
        ({"evidence": {"pad": "x" * 32_800}}, "ck_assessments_evidence_shape"),
        ({"model_versions": []}, "ck_assessments_model_versions_shape"),
    ],
)
def test_assessment_checks(
    runtime_tx: Connection, override: dict[str, Any], constraint: str
) -> None:
    incident_id = add(runtime_tx, Incident, rows.incident())
    assert_rejected(runtime_tx, constraint, Assessment, rows.assessment(incident_id, **override))


# --- reviews and audit records ------------------------------------------------------------


@pytest.mark.parametrize(
    ("override", "constraint"),
    [
        ({"decision": "probably_fine"}, "ck_reviews_decision"),
        ({"payload_digest": b"x"}, "ck_reviews_payload_digest_length"),
        ({"assessment_revision": 2}, "fk_reviews_incident_id_assessment_revision_assessments"),
    ],
)
def test_review_checks(runtime_tx: Connection, override: dict[str, Any], constraint: str) -> None:
    analyst = add(runtime_tx, User, rows.user())
    incident_id, _ = rows.standalone_incident(runtime_tx)
    assert_rejected(runtime_tx, constraint, Review, rows.review(incident_id, analyst, **override))


def test_review_retry_key_is_unique_per_analyst(runtime_tx: Connection) -> None:
    analyst = add(runtime_tx, User, rows.user())
    other = add(runtime_tx, User, rows.user())
    incident_id, _ = rows.standalone_incident(runtime_tx)
    key = rows.uuid4()
    add(runtime_tx, Review, rows.review(incident_id, analyst, idempotency_key=key))
    add(runtime_tx, Review, rows.review(incident_id, other, idempotency_key=key))
    assert_rejected(
        runtime_tx,
        "uq_reviews_analyst_id_idempotency_key",
        Review,
        rows.review(incident_id, analyst, idempotency_key=key),
    )


@pytest.mark.parametrize(
    ("actor", "constraint"),
    [
        ({"actor_kind": "user"}, "ck_audit_records_actor_matches_kind"),
        ({"actor_kind": "ingestor"}, "ck_audit_records_actor_matches_kind"),
        ({"actor_kind": "system", "with_user": True}, "ck_audit_records_actor_matches_kind"),
        ({"actor_kind": "robot"}, "ck_audit_records_actor_kind"),
        ({"outcome": "maybe"}, "ck_audit_records_outcome"),
        ({"record_hmac": b"\x01"}, "ck_audit_records_record_hmac_length"),
    ],
)
def test_audit_checks(runtime_tx: Connection, actor: dict[str, Any], constraint: str) -> None:
    values = dict(actor)
    if values.pop("with_user", False):
        values["actor_user_id"] = add(runtime_tx, User, rows.user())
    assert_rejected(runtime_tx, constraint, AuditRecord, rows.audit(**values))


def test_audit_actor_kinds_accept_matching_actors(runtime_tx: Connection) -> None:
    user_id = add(runtime_tx, User, rows.user())
    key_id = add(runtime_tx, IngestKey, rows.ingest_key(user_id))
    add(runtime_tx, AuditRecord, rows.audit(actor_kind="user", actor_user_id=user_id))
    add(runtime_tx, AuditRecord, rows.audit(actor_kind="ingestor", actor_ingest_key_id=key_id))
    add(runtime_tx, AuditRecord, rows.audit(actor_kind="system"))
    check_deferred_now(runtime_tx)


# --- referential actions (as the owner, since the runtime role cannot delete) ---------------


def test_referenced_users_and_events_cannot_be_deleted(owner_tx: Connection) -> None:
    analyst = add(owner_tx, User, rows.user())
    incident_id, event_id = rows.standalone_incident(owner_tx)
    add(owner_tx, Review, rows.review(incident_id, analyst))
    check_deferred_now(owner_tx)
    with pytest.raises(IntegrityError) as error:
        with owner_tx.begin_nested():
            owner_tx.execute(text("DELETE FROM users WHERE id = :id"), {"id": analyst})
    assert violated_constraint(error) == "fk_reviews_analyst_id_users"
    with pytest.raises(IntegrityError) as error:
        with owner_tx.begin_nested():
            owner_tx.execute(text("DELETE FROM events WHERE id = :id"), {"id": event_id})
    assert violated_constraint(error) == "fk_incident_events_event_id_events"


def test_deleting_an_incident_removes_its_links_assessments_and_reviews(
    owner_tx: Connection,
) -> None:
    analyst = add(owner_tx, User, rows.user())
    incident_id, _ = rows.standalone_incident(owner_tx)
    review_id = add(owner_tx, Review, rows.review(incident_id, analyst))
    owner_tx.execute(
        update(Incident).where(Incident.id == incident_id).values(latest_review_id=review_id)
    )
    check_deferred_now(owner_tx)
    owner_tx.execute(text("DELETE FROM incidents WHERE id = :id"), {"id": incident_id})
    check_deferred_now(owner_tx)
    for model, column in (
        (IncidentEvent, IncidentEvent.incident_id),
        (Assessment, Assessment.incident_id),
        (Review, Review.incident_id),
    ):
        remaining = owner_tx.execute(
            select(func.count()).select_from(model).where(column == incident_id)
        ).scalar_one()
        assert remaining == 0


# --- commit-time enforcement --------------------------------------------------------------


def test_commit_rejects_an_incident_without_events(
    migrated_schema: None, runtime_engine: Engine, migration_engine: Engine
) -> None:
    key = rows.uuid4().hex
    with runtime_engine.connect() as connection:
        with pytest.raises(IntegrityError) as error:
            with connection.begin():
                incident_id = add(connection, Incident, rows.incident(incident_key=key))
                add(connection, Assessment, rows.assessment(incident_id))
    assert violated_constraint(error) == "incident_membership_cardinality"
    with migration_engine.connect() as connection:
        stored = connection.execute(
            select(func.count()).select_from(Incident).where(Incident.incident_key == key)
        ).scalar_one()
    assert stored == 0
