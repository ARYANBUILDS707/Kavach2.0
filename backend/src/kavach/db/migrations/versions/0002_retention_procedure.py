"""Narrow the retention role to an expiry procedure; make revocation final (M2.5).

Revision ID: 0002_retention_procedure
Revises: 0001_initial_schema
Create Date: 2026-11-03

DATABASE.md specifies that "retention uses narrowly scoped expiry procedures". Revision 0001
instead gave kavach_retention table-level DELETE, which let it delete *unexpired* rows (for
example every audit record). This revision replaces those grants with EXECUTE on one
SECURITY DEFINER function that can only delete expired rows, in batches, with a cutoff that
is never in the future. It also forbids un-revoking a session or an ingestion key: once
`revoked_at` is set it can no longer change, for any role.

No table or column changes; `alembic check` is unaffected.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0002_retention_procedure"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Exactly the grants 0001 gave the retention role; restored only by a guarded downgrade.
RETENTION_TABLE_GRANTS = [
    "GRANT SELECT (id, expires_at, revoked_at), DELETE ON sessions TO kavach_retention",
    "GRANT SELECT (id, expires_at), DELETE ON incidents TO kavach_retention",
    "GRANT SELECT (id, expires_at), DELETE ON events TO kavach_retention",
    "GRANT SELECT (id, expires_at), DELETE ON audit_records TO kavach_retention",
    "GRANT SELECT (event_id) ON incident_events TO kavach_retention",
]
REVOKE_RETENTION_TABLE_GRANTS = [
    "REVOKE ALL ON sessions, incidents, events, audit_records, incident_events"
    " FROM kavach_retention",
    "REVOKE SELECT (id, expires_at, revoked_at) ON sessions FROM kavach_retention",
    "REVOKE SELECT (id, expires_at) ON incidents, events, audit_records FROM kavach_retention",
    "REVOKE SELECT (event_id) ON incident_events FROM kavach_retention",
]

UPGRADE_SQL = [
    # One batch of expiry deletions. The order and rules mirror DATABASE.md: incidents (their
    # links, assessments and reviews cascade), events no longer linked to any incident, audit
    # records, then expired or revoked sessions. Users and ingestion keys are never touched.
    """
    CREATE FUNCTION kavach_retention_purge(target text, cutoff timestamptz, batch_size integer)
    RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    DECLARE
        deleted integer;
    BEGIN
        IF cutoff IS NULL OR cutoff > clock_timestamp() THEN
            RAISE EXCEPTION 'retention cutoff must not be in the future'
                USING ERRCODE = 'invalid_parameter_value';
        END IF;
        IF batch_size IS NULL OR batch_size < 1 OR batch_size > 10000 THEN
            RAISE EXCEPTION 'retention batch size must be between 1 and 10000'
                USING ERRCODE = 'invalid_parameter_value';
        END IF;
        IF target = 'incidents' THEN
            DELETE FROM public.incidents WHERE id IN (
                SELECT id FROM public.incidents WHERE expires_at <= cutoff
                ORDER BY expires_at, id LIMIT batch_size);
        ELSIF target = 'events' THEN
            DELETE FROM public.events WHERE id IN (
                SELECT candidate.id FROM public.events AS candidate
                WHERE candidate.expires_at <= cutoff
                  AND NOT EXISTS (SELECT 1 FROM public.incident_events AS link
                                  WHERE link.event_id = candidate.id)
                ORDER BY candidate.expires_at, candidate.id LIMIT batch_size);
        ELSIF target = 'audit_records' THEN
            DELETE FROM public.audit_records WHERE id IN (
                SELECT id FROM public.audit_records WHERE expires_at <= cutoff
                ORDER BY expires_at, id LIMIT batch_size);
        ELSIF target = 'sessions' THEN
            DELETE FROM public.sessions WHERE id IN (
                SELECT id FROM public.sessions
                WHERE expires_at <= cutoff OR revoked_at <= cutoff
                ORDER BY id LIMIT batch_size);
        ELSE
            RAISE EXCEPTION 'unknown retention target'
                USING ERRCODE = 'invalid_parameter_value';
        END IF;
        GET DIAGNOSTICS deleted = ROW_COUNT;
        RETURN deleted;
    END
    $$
    """,
    "REVOKE ALL ON FUNCTION kavach_retention_purge(text, timestamptz, integer) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION kavach_retention_purge(text, timestamptz, integer)"
    " TO kavach_retention",
    *REVOKE_RETENTION_TABLE_GRANTS,
    """
    CREATE FUNCTION kavach_keep_revocation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
            RAISE EXCEPTION 'revocation is final'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'revocation_is_final';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    "REVOKE ALL ON FUNCTION kavach_keep_revocation() FROM PUBLIC",
    """
    CREATE TRIGGER sessions_keep_revocation BEFORE UPDATE OF revoked_at ON sessions
    FOR EACH ROW EXECUTE FUNCTION kavach_keep_revocation()
    """,
    """
    CREATE TRIGGER ingest_keys_keep_revocation BEFORE UPDATE OF revoked_at ON ingest_keys
    FOR EACH ROW EXECUTE FUNCTION kavach_keep_revocation()
    """,
]


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    # Restores the broader 0001 grants, so it is limited to disposable *_test databases.
    database = op.get_bind().execute(sa.text("SELECT current_database()")).scalar_one()
    allowed = context.get_x_argument(as_dictionary=True).get(
        "allow-destructive-downgrade"
    ) or context.config.attributes.get("allow_destructive_downgrade")
    if allowed != database or not database.endswith("_test"):
        raise RuntimeError(
            "Refusing to downgrade the KAVACH schema: downgrade is allowed only on a disposable"
            " *_test database named with -x allow-destructive-downgrade=<database>."
        )
    op.execute("DROP TRIGGER ingest_keys_keep_revocation ON ingest_keys")
    op.execute("DROP TRIGGER sessions_keep_revocation ON sessions")
    op.execute("DROP FUNCTION kavach_keep_revocation()")
    op.execute("DROP FUNCTION kavach_retention_purge(text, timestamptz, integer)")
    for statement in RETENTION_TABLE_GRANTS:
        op.execute(statement)
