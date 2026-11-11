"""Initial KAVACH schema (DATABASE.md): nine tables, integrity triggers and role grants.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-31

Tables are created by the migration owner. The runtime role (kavach_app) and the retention
role (kavach_retention) receive only the privileges listed in RUNTIME_GRANTS and
RETENTION_GRANTS. The downgrade drops everything and is refused unless the target is an
explicitly named disposable *_test database.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Role names are created by the bootstrap (deployment/postgres/initdb/10-kavach-roles.sql).
# Append-only tables get SELECT/INSERT only; mutable state is limited to named columns.
RUNTIME_GRANTS = [
    "GRANT SELECT, INSERT ON users, sessions, ingest_keys, events, incidents, incident_events,"
    " assessments, reviews, audit_records TO kavach_app",
    "GRANT UPDATE (display_name, password_hash, role, is_active) ON users TO kavach_app",
    "GRANT UPDATE (last_seen_at, revoked_at) ON sessions TO kavach_app",
    "GRANT UPDATE (revoked_at) ON ingest_keys TO kavach_app",
    "GRANT UPDATE (current_revision, latest_review_id, version, updated_at)"
    " ON incidents TO kavach_app",
]

# Expiry cleanup only: read the expiry columns and delete expired roots; links, assessments
# and reviews go with their incident through ON DELETE CASCADE.
RETENTION_GRANTS = [
    "GRANT SELECT (id, expires_at, revoked_at), DELETE ON sessions TO kavach_retention",
    "GRANT SELECT (id, expires_at), DELETE ON incidents TO kavach_retention",
    "GRANT SELECT (id, expires_at), DELETE ON events TO kavach_retention",
    "GRANT SELECT (id, expires_at), DELETE ON audit_records TO kavach_retention",
    "GRANT SELECT (event_id) ON incident_events TO kavach_retention",
]

INTEGRITY_SQL = [
    """
    CREATE FUNCTION kavach_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        NEW.updated_at := now();
        RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER users_set_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION kavach_set_updated_at()
    """,
    # Cross-row rules from DATABASE.md, checked at commit (deferred) so an incident, its links
    # and its first assessment can be written in any order within one transaction.
    """
    CREATE FUNCTION kavach_check_incident_integrity(target uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    DECLARE
        incident_kind text;
        total integer;
        sms_links integer;
        call_links integer;
        subjects integer;
        mismatched integer;
    BEGIN
        SELECT kind INTO incident_kind FROM public.incidents WHERE id = target;
        IF NOT FOUND THEN
            RETURN;  -- the incident was deleted; its links are cascading away with it
        END IF;

        SELECT count(*),
               count(*) FILTER (WHERE link.channel = 'sms'),
               count(*) FILTER (WHERE link.channel = 'call'),
               count(DISTINCT (event.subscriber_digest, event.identity_key_version)),
               count(*) FILTER (WHERE link.channel <> event.kind)
          INTO total, sms_links, call_links, subjects, mismatched
          FROM public.incident_events AS link
          JOIN public.events AS event ON event.id = link.event_id
         WHERE link.incident_id = target;

        IF mismatched > 0 THEN
            RAISE EXCEPTION 'incident % links an event through a channel unlike its kind', target
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'incident_events_channel_matches_kind';
        END IF;
        IF incident_kind = 'standalone' AND total <> 1 THEN
            RAISE EXCEPTION 'standalone incident % must link exactly one event', target
                USING ERRCODE = 'check_violation', CONSTRAINT = 'incident_membership_cardinality';
        END IF;
        IF incident_kind = 'pair' AND NOT (total = 2 AND sms_links = 1 AND call_links = 1) THEN
            RAISE EXCEPTION 'pair incident % must link exactly one SMS and one call event', target
                USING ERRCODE = 'check_violation', CONSTRAINT = 'incident_membership_cardinality';
        END IF;
        IF subjects > 1 THEN
            RAISE EXCEPTION 'incident % links events of different subscribers', target
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'incident_membership_same_subscriber';
        END IF;
        IF incident_kind = 'standalone' AND EXISTS (
            SELECT 1 FROM public.assessments
             WHERE incident_id = target AND fusion_score IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'standalone incident % cannot carry a fusion score', target
                USING ERRCODE = 'check_violation', CONSTRAINT = 'assessments_fusion_only_for_pairs';
        END IF;
    END
    $$
    """,
    """
    CREATE FUNCTION kavach_incident_integrity_trigger() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    DECLARE
        linked record;
    BEGIN
        IF TG_TABLE_NAME = 'incident_events' THEN
            IF TG_OP <> 'DELETE' THEN
                PERFORM public.kavach_check_incident_integrity(NEW.incident_id);
            END IF;
            IF TG_OP <> 'INSERT' THEN
                PERFORM public.kavach_check_incident_integrity(OLD.incident_id);
            END IF;
        ELSIF TG_TABLE_NAME = 'incidents' THEN
            PERFORM public.kavach_check_incident_integrity(NEW.id);
        ELSIF TG_TABLE_NAME = 'assessments' THEN
            PERFORM public.kavach_check_incident_integrity(NEW.incident_id);
        ELSIF TG_TABLE_NAME = 'events' THEN
            FOR linked IN
                SELECT incident_id FROM public.incident_events WHERE event_id = NEW.id
            LOOP
                PERFORM public.kavach_check_incident_integrity(linked.incident_id);
            END LOOP;
        END IF;
        RETURN NULL;
    END
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER incident_events_integrity
    AFTER INSERT OR UPDATE OR DELETE ON incident_events
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION kavach_incident_integrity_trigger()
    """,
    """
    CREATE CONSTRAINT TRIGGER incidents_integrity
    AFTER INSERT OR UPDATE OF kind ON incidents
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION kavach_incident_integrity_trigger()
    """,
    """
    CREATE CONSTRAINT TRIGGER assessments_integrity
    AFTER INSERT OR UPDATE OF fusion_score ON assessments
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION kavach_incident_integrity_trigger()
    """,
    """
    CREATE CONSTRAINT TRIGGER events_integrity
    AFTER UPDATE OF kind, subscriber_digest, identity_key_version ON events
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION kavach_incident_integrity_trigger()
    """,
    # Functions are executable by PUBLIC by default; triggers do not need that grant.
    "REVOKE ALL ON FUNCTION kavach_set_updated_at() FROM PUBLIC",
    "REVOKE ALL ON FUNCTION kavach_check_incident_integrity(uuid) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION kavach_incident_integrity_trigger() FROM PUBLIC",
]


def uuid_pk() -> sa.Column[object]:
    return sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def timestamp(name: str, *, nullable: bool = False, now: bool = False) -> sa.Column[object]:
    default = sa.text("now()") if now else None
    return sa.Column(name, sa.DateTime(timezone=True), server_default=default, nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "users",
        uuid_pk(),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        timestamp("created_at", now=True),
        timestamp("updated_at", now=True),
        sa.CheckConstraint(
            "username = lower(username) AND char_length(username) >= 1",
            name=op.f("ck_users_username_canonical"),
        ),
        sa.CheckConstraint("role IN ('viewer', 'analyst', 'admin')", name=op.f("ck_users_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )

    op.create_table(
        "sessions",
        uuid_pk(),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_digest", sa.LargeBinary(), nullable=False),
        sa.Column("csrf_digest", sa.LargeBinary(), nullable=False),
        timestamp("created_at", now=True),
        timestamp("last_seen_at"),
        timestamp("expires_at"),
        timestamp("revoked_at", nullable=True),
        sa.CheckConstraint(
            "octet_length(token_digest) = 32", name=op.f("ck_sessions_token_digest_length")
        ),
        sa.CheckConstraint(
            "octet_length(csrf_digest) = 32", name=op.f("ck_sessions_csrf_digest_length")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_sessions_token_digest")),
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    op.create_table(
        "ingest_keys",
        uuid_pk(),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("key_digest", sa.LargeBinary(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        timestamp("created_at", now=True),
        timestamp("expires_at"),
        timestamp("revoked_at", nullable=True),
        sa.CheckConstraint(
            "octet_length(key_digest) = 32", name=op.f("ck_ingest_keys_key_digest_length")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_ingest_keys_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingest_keys")),
        sa.UniqueConstraint("key_digest", name=op.f("uq_ingest_keys_key_digest")),
    )

    op.create_table(
        "events",
        uuid_pk(),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_event_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("subscriber_digest", sa.LargeBinary(), nullable=False),
        sa.Column("identity_key_version", sa.String(length=32), nullable=False),
        sa.Column("payload_digest", sa.LargeBinary(), nullable=False),
        sa.Column("payload_key_version", sa.String(length=32), nullable=False),
        timestamp("event_time"),
        timestamp("received_at"),
        sa.Column("analysis_status", sa.Text(), nullable=False),
        sa.Column("sms_score", postgresql.DOUBLE_PRECISION(), nullable=True),
        sa.Column("voice_intent_score", postgresql.DOUBLE_PRECISION(), nullable=True),
        sa.Column("synthesis_score", postgresql.DOUBLE_PRECISION(), nullable=True),
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processing_ms", sa.Integer(), nullable=False),
        timestamp("expires_at"),
        sa.CheckConstraint("kind IN ('sms', 'call')", name=op.f("ck_events_kind")),
        sa.CheckConstraint(
            "analysis_status IN ('complete', 'partial', 'unavailable')",
            name=op.f("ck_events_analysis_status"),
        ),
        sa.CheckConstraint(
            "octet_length(subscriber_digest) = 32", name=op.f("ck_events_subscriber_digest_length")
        ),
        sa.CheckConstraint(
            "octet_length(payload_digest) = 32", name=op.f("ck_events_payload_digest_length")
        ),
        sa.CheckConstraint(
            "sms_score >= 0 AND sms_score <= 1", name=op.f("ck_events_sms_score_range")
        ),
        sa.CheckConstraint(
            "voice_intent_score >= 0 AND voice_intent_score <= 1",
            name=op.f("ck_events_voice_intent_score_range"),
        ),
        sa.CheckConstraint(
            "synthesis_score >= 0 AND synthesis_score <= 1",
            name=op.f("ck_events_synthesis_score_range"),
        ),
        sa.CheckConstraint(
            "(kind = 'sms' AND voice_intent_score IS NULL AND synthesis_score IS NULL)"
            " OR (kind = 'call' AND sms_score IS NULL)",
            name=op.f("ck_events_kind_scores"),
        ),
        sa.CheckConstraint("processing_ms >= 0", name=op.f("ck_events_processing_ms_non_negative")),
        sa.CheckConstraint(
            "jsonb_typeof(signals) = 'object' AND octet_length(signals::text) <= 16384",
            name=op.f("ck_events_signals_shape"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(model_versions) = 'object'"
            " AND octet_length(model_versions::text) <= 4096",
            name=op.f("ck_events_model_versions_shape"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.UniqueConstraint(
            "source", "external_event_id", name=op.f("uq_events_source_external_event_id")
        ),
    )
    op.create_index(
        "ix_events_candidates",
        "events",
        ["subscriber_digest", "identity_key_version", "kind", "event_time", "id"],
    )
    op.create_index("ix_events_expires_at", "events", ["expires_at"])

    op.create_table(
        "incidents",
        uuid_pk(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("incident_key", sa.String(length=160), nullable=False),
        timestamp("occurred_at"),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("latest_review_id", sa.UUID(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        timestamp("created_at", now=True),
        timestamp("updated_at"),
        timestamp("expires_at"),
        sa.CheckConstraint("kind IN ('standalone', 'pair')", name=op.f("ck_incidents_kind")),
        sa.CheckConstraint(
            "current_revision >= 1", name=op.f("ck_incidents_current_revision_positive")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_incidents_version_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
        sa.UniqueConstraint("incident_key", name=op.f("uq_incidents_incident_key")),
    )
    op.create_index("ix_incidents_expires_at", "incidents", ["expires_at"])
    op.create_index(
        "ix_incidents_feed",
        "incidents",
        [sa.literal_column("occurred_at DESC"), sa.literal_column("id DESC")],
    )
    op.create_index(
        "ix_incidents_kind_feed",
        "incidents",
        ["kind", sa.literal_column("occurred_at DESC"), sa.literal_column("id DESC")],
    )

    op.create_table(
        "incident_events",
        sa.Column("incident_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.CheckConstraint("channel IN ('sms', 'call')", name=op.f("ck_incident_events_channel")),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_incident_events_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_incident_events_event_id_events"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("incident_id", "event_id", name=op.f("pk_incident_events")),
        sa.UniqueConstraint(
            "incident_id", "channel", name=op.f("uq_incident_events_incident_id_channel")
        ),
    )
    op.create_index(
        "ix_incident_events_event_id_incident_id", "incident_events", ["event_id", "incident_id"]
    )

    op.create_table(
        "assessments",
        sa.Column("incident_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("base_score", postgresql.DOUBLE_PRECISION(), nullable=True),
        sa.Column("fusion_score", postgresql.DOUBLE_PRECISION(), nullable=True),
        sa.Column("final_score", postgresql.DOUBLE_PRECISION(), nullable=True),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("analysis_status", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        timestamp("created_at", now=True),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_assessments_revision_positive")),
        sa.CheckConstraint(
            "base_score >= 0 AND base_score <= 1", name=op.f("ck_assessments_base_score_range")
        ),
        sa.CheckConstraint(
            "fusion_score >= 0 AND fusion_score <= 1",
            name=op.f("ck_assessments_fusion_score_range"),
        ),
        sa.CheckConstraint(
            "final_score >= 0 AND final_score <= 1", name=op.f("ck_assessments_final_score_range")
        ),
        sa.CheckConstraint(
            "tier IN ('unknown', 'low', 'medium', 'high', 'critical')",
            name=op.f("ck_assessments_tier"),
        ),
        sa.CheckConstraint(
            "analysis_status IN ('complete', 'partial', 'unavailable')",
            name=op.f("ck_assessments_analysis_status"),
        ),
        sa.CheckConstraint(
            "(tier = 'unknown' AND final_score IS NULL)"
            " OR (tier <> 'unknown' AND final_score IS NOT NULL)",
            name=op.f("ck_assessments_tier_final_score"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'object' AND octet_length(evidence::text) <= 32768",
            name=op.f("ck_assessments_evidence_shape"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(model_versions) = 'object'",
            name=op.f("ck_assessments_model_versions_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_assessments_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("incident_id", "revision", name=op.f("pk_assessments")),
    )

    op.create_table(
        "reviews",
        uuid_pk(),
        sa.Column("incident_id", sa.UUID(), nullable=False),
        sa.Column("assessment_revision", sa.Integer(), nullable=False),
        sa.Column("analyst_id", sa.UUID(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("idempotency_key", sa.UUID(), nullable=False),
        sa.Column("payload_digest", sa.LargeBinary(), nullable=False),
        timestamp("created_at", now=True),
        sa.CheckConstraint(
            "decision IN ('true_fraud', 'false_alarm', 'needs_investigation')",
            name=op.f("ck_reviews_decision"),
        ),
        sa.CheckConstraint(
            "octet_length(payload_digest) = 32", name=op.f("ck_reviews_payload_digest_length")
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_reviews_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id", "assessment_revision"],
            ["assessments.incident_id", "assessments.revision"],
            name=op.f("fk_reviews_incident_id_assessment_revision_assessments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["analyst_id"],
            ["users.id"],
            name=op.f("fk_reviews_analyst_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
        sa.UniqueConstraint("incident_id", "id", name=op.f("uq_reviews_incident_id_id")),
        sa.UniqueConstraint(
            "analyst_id", "idempotency_key", name=op.f("uq_reviews_analyst_id_idempotency_key")
        ),
    )
    op.create_index("ix_reviews_history", "reviews", ["incident_id", "created_at", "id"])

    # Circular references, added once both sides exist. Deferred so an incident, its first
    # assessment and a review (with latest_review_id) can be written in one transaction.
    op.create_foreign_key(
        op.f("fk_incidents_id_current_revision_assessments"),
        "incidents",
        "assessments",
        ["id", "current_revision"],
        ["incident_id", "revision"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        op.f("fk_incidents_id_latest_review_id_reviews"),
        "incidents",
        "reviews",
        ["id", "latest_review_id"],
        ["incident_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "audit_records",
        uuid_pk(),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_ingest_key_id", sa.UUID(), nullable=True),
        sa.Column("actor_kind", sa.Text(), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        timestamp("created_at", now=True),
        sa.Column("key_version", sa.String(length=32), nullable=False),
        sa.Column("record_hmac", sa.LargeBinary(), nullable=False),
        timestamp("expires_at"),
        sa.CheckConstraint(
            "actor_kind IN ('user', 'ingestor', 'system')", name=op.f("ck_audit_records_actor_kind")
        ),
        sa.CheckConstraint(
            "(actor_kind = 'user' AND actor_user_id IS NOT NULL AND actor_ingest_key_id IS NULL)"
            " OR (actor_kind = 'ingestor' AND actor_ingest_key_id IS NOT NULL"
            " AND actor_user_id IS NULL)"
            " OR (actor_kind = 'system' AND actor_user_id IS NULL AND actor_ingest_key_id IS NULL)",
            name=op.f("ck_audit_records_actor_matches_kind"),
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'denied')", name=op.f("ck_audit_records_outcome")
        ),
        sa.CheckConstraint(
            "octet_length(record_hmac) = 32", name=op.f("ck_audit_records_record_hmac_length")
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_records_actor_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_ingest_key_id"],
            ["ingest_keys.id"],
            name=op.f("fk_audit_records_actor_ingest_key_id_ingest_keys"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_records")),
    )
    op.create_index("ix_audit_records_expires_at", "audit_records", ["expires_at"])

    for statement in INTEGRITY_SQL + RUNTIME_GRANTS + RETENTION_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    # Destroys every table. Only for disposable test databases, named explicitly by the caller:
    #   alembic -x allow-destructive-downgrade=<database> downgrade base
    database = op.get_bind().execute(sa.text("SELECT current_database()")).scalar_one()
    allowed = context.get_x_argument(as_dictionary=True).get(
        "allow-destructive-downgrade"
    ) or context.config.attributes.get("allow_destructive_downgrade")
    if allowed != database or not database.endswith("_test"):
        raise RuntimeError(
            "Refusing to drop the KAVACH schema: downgrade is allowed only on a disposable"
            " *_test database named with -x allow-destructive-downgrade=<database>."
        )

    op.drop_constraint(
        op.f("fk_incidents_id_latest_review_id_reviews"), "incidents", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_incidents_id_current_revision_assessments"), "incidents", type_="foreignkey"
    )
    for table in (
        "audit_records",
        "reviews",
        "assessments",
        "incident_events",
        "incidents",
        "events",
        "ingest_keys",
        "sessions",
        "users",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION kavach_incident_integrity_trigger()")
    op.execute("DROP FUNCTION kavach_check_incident_integrity(uuid)")
    op.execute("DROP FUNCTION kavach_set_updated_at()")
