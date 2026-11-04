# KAVACH Database Specification

## Status and conventions

Approved for M2 under PRD D02, D03 and D07 (31 October 2026); D05 remains proposed. Use PostgreSQL for durable state and Redis only for temporary cache/rate counters. The schema below is implemented by Alembic revision `0001_initial_schema` (M2.2) with SQLAlchemy models in `backend/src/kavach/db/models.py`; see "Implementation notes (M2.2)" for the database-level details that this specification left to implementation. [ARCHITECTURE.md](ARCHITECTURE.md) defines transaction flow; [API.md](API.md) defines exposure.

All durable IDs are UUIDs unless stated otherwise. All timestamps are UTC `timestamptz`. Fields are required unless marked nullable. Server-generated `created_at` defaults to the database current time. Scores use `double precision` with finite range checks 0–1; nonfinite values are forbidden. Enum-like fields use text plus CHECK constraints so additions are explicit migrations. JSONB has an application schema and a bounded size; it is not an unrestricted payload archive.

## Tables and columns

### users

| Column | Type | Constraints |
| --- | --- | --- |
| id | uuid | Primary key |
| username | varchar(80) | Unique canonical lowercase username |
| display_name | varchar(120) | Required; not an authorization key |
| password_hash | text | Argon2id encoded hash; never returned |
| role | text | viewer, analyst, admin |
| is_active | boolean | Default true |
| created_at | timestamptz | Server assigned |
| updated_at | timestamptz | Server updated |

No email/phone is required. Provision and disable users with audited operator commands. Deactivate rather than delete users referenced by reviews/audit.

### sessions

| Column | Type | Constraints |
| --- | --- | --- |
| id | uuid | Primary key |
| user_id | uuid | FK users, ON DELETE CASCADE |
| token_digest | bytea | Unique 32-byte digest of high-entropy token |
| csrf_digest | bytea | 32-byte digest of session-bound CSRF token |
| created_at | timestamptz | Required |
| last_seen_at | timestamptz | Required |
| expires_at | timestamptz | Absolute deadline after creation |
| revoked_at | timestamptz | Nullable |

Idle timeout is evaluated from `last_seen_at`; absolute timeout from `expires_at`. Do not persist browser fingerprint, raw IP or user agent by default.

### ingest_keys

| Column | Type | Constraints |
| --- | --- | --- |
| id | uuid | Primary key |
| name | varchar(80) | Operator-readable identifier |
| key_digest | bytea | Unique 32-byte digest; plaintext shown only on provisioning |
| source | varchar(64) | Approved source scope |
| created_by | uuid | FK users, RESTRICT |
| created_at | timestamptz | Required |
| expires_at | timestamptz | Required |
| revoked_at | timestamptz | Nullable |

One capability: submit events and read receipts for its own source. Do not add arbitrary JSON permission grants.

### events

| Column | Type | Constraints |
| --- | --- | --- |
| id | uuid | Primary key |
| source | varchar(64) | Matches authenticated scope; admin simulator source is `simulator` |
| external_event_id | varchar(128) | Unique together with source |
| kind | text | sms or call |
| subscriber_digest | bytea | 32-byte keyed digest, never raw subscriber token |
| identity_key_version | varchar(32) | Version needed for digest lookup and rotation |
| payload_digest | bytea | 32-byte HMAC over canonical validated request for idempotency |
| payload_key_version | varchar(32) | HMAC key version |
| event_time | timestamptz | Client event time, validated |
| received_at | timestamptz | Server arrival time |
| analysis_status | text | complete, partial, unavailable |
| sms_score | double precision | Nullable; only for sms |
| voice_intent_score | double precision | Nullable; only for call |
| synthesis_score | double precision | Nullable; only for call |
| signals | jsonb | Allowlisted structure described below |
| model_versions | jsonb | Map stage name to immutable artifact/version ID |
| processing_ms | integer | ≥0 |
| expires_at | timestamptz | Required; retention deadline |

`signals` contains reason-code arrays, approved canonical organization labels, intent category, boolean URL-risk indicators, context confidence where supported, per-stage status/duration, audio duration/sample ID for synthetic fixtures, and late-event status. Never store arbitrary entity text, URLs, phone numbers, OTPs, raw sender IDs, SMS, transcript, audio or feature vectors. Missing-score reason is required for every unavailable stage. Cap serialized signals at 16 KiB and versions at 4 KiB.

Store only post-analysis events; a pending raw job table is intentionally absent. `kind` consistency CHECKs prohibit voice scores on SMS and SMS scores on calls. Stronger status/signal-schema validation is enforced at the service boundary.

### incidents

| Column | Type | Constraints |
| --- | --- | --- |
| id | uuid | Primary key |
| kind | text | standalone or pair |
| incident_key | varchar(160) | Unique canonical key: one event UUID or ordered SMS/call UUIDs |
| occurred_at | timestamptz | Latest constituent event time, immutable |
| current_revision | integer | ≥1; matches latest assessment |
| latest_review_id | uuid | Nullable FK reviews; same-incident requirement |
| version | integer | ≥1; increment on review/assessment change |
| created_at | timestamptz | Required |
| updated_at | timestamptz | Required |
| expires_at | timestamptz | Minimum expiry of constituent events |

### incident_events

| Column | Type | Constraints |
| --- | --- | --- |
| incident_id | uuid | FK incidents, CASCADE; part of primary key |
| event_id | uuid | FK events, RESTRICT; part of primary key |
| channel | text | sms or call; must match event kind |

Unique `(incident_id, channel)` permits at most one event of each channel. Standalone requires exactly one event; pair requires exactly one SMS and one call. Enforce cardinality, matching channel and same subscriber/key version using a deferred database constraint trigger plus service validation. Do not merge different subscribers through a client-provided incident ID.

### assessments

| Column | Type | Constraints |
| --- | --- | --- |
| incident_id | uuid | FK incidents, CASCADE; composite primary key |
| revision | integer | ≥1; composite primary key |
| base_score | double precision | Nullable |
| fusion_score | double precision | Nullable; only pairs |
| final_score | double precision | Nullable |
| tier | text | unknown, low, medium, high, critical |
| analysis_status | text | complete, partial, unavailable |
| evidence | jsonb | Bounded structured snapshot: signal scores/statuses, event IDs, time delta, subscriber/context checks, reasons |
| model_versions | jsonb | Exact artifacts used |
| policy_version | varchar(80) | Immutable policy identifier |
| created_at | timestamptz | Required |

`unknown` requires null final score; a known tier requires a finite final score. Policy thresholds and score-floor equality are validated by the domain service and tests against `policy_version`. Cap evidence at 32 KiB. No raw content. Enforce `(incidents.id, current_revision)` → `(assessments.incident_id, revision)` with a deferred FK so initial incident and assessment can be inserted atomically.

### reviews

| Column | Type | Constraints |
| --- | --- | --- |
| id | uuid | Primary key |
| incident_id | uuid | FK incidents, CASCADE |
| assessment_revision | integer | Composite FK with incident_id to assessments |
| analyst_id | uuid | FK users, RESTRICT |
| decision | text | true_fraud, false_alarm, needs_investigation |
| note | varchar(1000) | Nullable; sanitized; no raw communications |
| idempotency_key | uuid | Unique together with analyst_id |
| payload_digest | bytea | 32-byte digest for conflict detection |
| created_at | timestamptz | Server assigned |

Reviews are append-only; corrections are new reviews. Add unique `(incident_id, id)` and use composite FK `(incidents.id, latest_review_id)` to ensure the latest review belongs to that incident. This nullable deferred FK is checked within the same transaction as review insertion. Review history retains the exact assessment revision viewed.

### audit_records

| Column | Type | Constraints |
| --- | --- | --- |
| id | uuid | Primary key |
| actor_user_id | uuid | Nullable FK users, RESTRICT |
| actor_ingest_key_id | uuid | Nullable FK ingest_keys, RESTRICT |
| actor_kind | text | user, ingestor, system |
| action | varchar(80) | Allowlisted action code |
| resource_type | varchar(40) | Allowlisted type |
| resource_id | uuid | Nullable; intentionally not FK to expiring evidence |
| request_id | uuid | Correlation ID, never request content |
| outcome | text | success or denied |
| created_at | timestamptz | Required |
| key_version | varchar(32) | Signing key identifier |
| record_hmac | bytea | 32-byte HMAC over canonical stored fields except signature |
| expires_at | timestamptz | Required |

Actor CHECKs require matching non-null actor FK for user/ingestor and neither for system. No raw text, IP, subscriber digest, review note or credential in audit records. The application has INSERT/SELECT only on audit records; the retention role alone deletes expired records. HMAC detects alteration when checked with protected keys; it does not establish append-only external storage or prove that records were not deleted. Independently controlled backups are needed for stronger assurance.

## Relationships

```mermaid
erDiagram
  users ||--o{ sessions : owns
  users ||--o{ ingest_keys : provisions
  users ||--o{ reviews : writes
  users o|--o{ audit_records : acts
  ingest_keys o|--o{ audit_records : acts
  events ||--o{ incident_events : appears_in
  incidents ||--|{ incident_events : contains
  incidents ||--|{ assessments : versions
  assessments ||--o{ reviews : reviewed_at
  incidents ||--o{ reviews : receives
```

## Queries and indexes

| Query | Index |
| --- | --- |
| Login lookup | Unique users(username) |
| Session/key validation | Unique token_digest / key_digest |
| Idempotent event receipt | Unique events(source, external_event_id) |
| Candidate opposite-channel events | events(subscriber_digest, identity_key_version, kind, event_time, id) |
| Feed ordered by occurred_at/id | incidents(occurred_at DESC, id DESC) |
| Incident kind filter | incidents(kind, occurred_at DESC, id DESC) |
| Assessment revision lookup | Primary key assessments(incident_id, revision) |
| Evidence reverse links | incident_events(event_id, incident_id) |
| Review history | reviews(incident_id, created_at, id) |
| Review retry | Unique reviews(analyst_id, idempotency_key) |
| Expiry cleanup | events(expires_at), incidents(expires_at), sessions(expires_at), audit_records(expires_at) |

Tier/status filters join the current assessment/latest review. Inspect actual query plans before adding indexes for these filters; at the MVP data size do not denormalize scores into multiple tables merely for speculative speed. Do not index unqueried JSONB indiscriminately.

## Ownership and database privileges

Single organization per deployment. Only backend/operator jobs connect to PostgreSQL; browsers never do. Every route enforces role permissions. Ingestors see only event receipts scoped by their key source. Dashboard users see the single organization's evidence; user/session/key administration is operator-only.

Use distinct migration-owner, runtime and retention roles. Runtime has no schema DDL, user-role bypass, review/assessment UPDATE/DELETE, or audit UPDATE/DELETE. Retention uses narrowly scoped expiry procedures. Table grants and service authorization are the proposed MVP boundary. Row-level security is not required for one deployment scope and no direct client database access; if tenant ownership is introduced, add tenant keys and default-deny policies before enabling tenant traffic. PostgreSQL RLS policy behavior and owner bypass must be explicitly tested in that change. [PostgreSQL row security](https://www.postgresql.org/docs/17/ddl-rowsecurity.html)

## Implementation notes (M2.2)

These record how the tables above are enforced in PostgreSQL. They do not change any documented column, type or relationship.

- **Roles.** `kavach_migrator` owns the schema and runs migrations; `kavach_app` is the runtime role; `kavach_retention` is the expiry role. Development/test roles are created by `deployment/postgres/initdb/10-kavach-roles.sql`; other environments must create roles with the same names before migrating. PUBLIC has no access to the databases and no `CREATE` on schema `public`.
- **Runtime grants.** SELECT and INSERT on all nine tables. UPDATE only on named columns: `users` (display_name, password_hash, role, is_active), `sessions` (last_seen_at, revoked_at), `ingest_keys` (revoked_at), `incidents` (current_revision, latest_review_id, version, updated_at). No UPDATE on events, incident_events, assessments, reviews or audit_records; no DELETE, TRUNCATE, REFERENCES, TRIGGER or DDL anywhere; no access to `alembic_version`.
- **Retention privileges (revision `0002_retention_procedure`, M2.5).** The retention role holds **no table privileges**. It may only execute `kavach_retention_purge(target, cutoff, batch_size)`, a `SECURITY DEFINER` procedure (pinned `search_path`, PUBLIC cannot execute it) that deletes one batch (1–10,000) of *expired* rows and refuses a cutoff later than the database clock (SQLSTATE 22023). Targets, in the order the cleanup uses them: `incidents` (their links, assessments and reviews cascade), `events` no longer linked to any incident, `audit_records`, and `sessions` that are expired or revoked. Users and ingestion keys are never deleted, so audit and review references stay valid. A row is removed when its `expires_at` (or a session's `revoked_at`) is at or before the cutoff. Revision 0001 had granted table-level DELETE, which allowed deleting unexpired rows, including every audit record; M2.5 found and closed that.
- **Retention runs** (`kavach.db.retention`, `python -m kavach.cli retention run`). The cutoff defaults to the database clock. Destructive runs require naming the connected database and are limited to `*_test` databases in this phase; dry runs execute the same batches in one transaction and roll back. Because the retention role cannot write audit rows, a destructive run is bracketed by audit records written through the runtime role: `retention.start` is committed **before** the first deletion (if it cannot be written, nothing is deleted) and `retention.complete` after the last, both carrying the run ID as `request_id`. A start without a completion marks an interrupted run.
- **Revocation is final (0002).** A `BEFORE UPDATE OF revoked_at` trigger on `sessions` and `ingest_keys` rejects any change to a set `revoked_at` (SQLSTATE 23514, constraint `revocation_is_final`), for every role. The runtime role's column grant would otherwise allow un-revoking.
- **Deferred cross-row rules.** A deferred constraint trigger on incident_events, incidents, assessments and events calls `kavach_check_incident_integrity()` at commit. It enforces: link channel equals event kind (`incident_events_channel_matches_kind`); standalone = exactly one event, pair = exactly one SMS and one call (`incident_membership_cardinality`); one subscriber digest and key version per incident (`incident_membership_same_subscriber`); `fusion_score` only on pair incidents (`assessments_fusion_only_for_pairs`). Violations raise SQLSTATE 23514 with those constraint names. The functions are `SECURITY DEFINER` with a pinned `search_path`, and PUBLIC cannot execute them.
- **Deferred foreign keys.** `(incidents.id, current_revision)` → `assessments` and `(incidents.id, latest_review_id)` → `reviews(incident_id, id)` are `DEFERRABLE INITIALLY DEFERRED`.
- **Checks added at the database boundary** (consistent with the column rules above): 32-byte length for every digest/HMAC column; canonical non-empty lowercase usernames; JSONB columns must be objects, with the documented 16 KiB (`events.signals`), 4 KiB (`events.model_versions`) and 32 KiB (`assessments.evidence`) caps; NaN and infinities fail the 0–1 score checks.
- **Server defaults.** UUID primary keys default to `gen_random_uuid()`; `created_at` defaults to `now()`; `users.updated_at` is maintained by a `BEFORE UPDATE` trigger. `incidents.updated_at` is set by the service.
- **Operator lifecycle (M2.4).** Account and key changes require an active admin actor, re-checked in the same transaction, and are audited in it. The first admin is created by an explicit bootstrap that is refused once any active admin exists; bootstrap, deactivation and demotion are serialized with a transaction-scoped advisory lock so the last active admin cannot be removed. Ingestion keys store only a SHA-256 digest and are revoked, never deleted.
- **Event writes (M3.1).** One transaction per new event: a transaction-scoped advisory lock derived from the subscriber digest, `INSERT ... ON CONFLICT (source, external_event_id) DO NOTHING`, the standalone incident (`incident_key = standalone:<event UUID>`, expiry equal to the event's) with its link and assessment revision 1 (tier `unknown`, all scores null, `policy_version` `kavach-m3.1-no-models`), and an `event.ingest` audit record whose actor is the ingestion key (`actor_kind = ingestor`). `subscriber_digest` and `payload_digest` are HMAC-SHA256 under the versioned `SUBSCRIBER_HMAC_KEYS` and `PAYLOAD_HMAC_KEYS`; raw text, sender IDs and subscriber tokens are never stored. `signals` holds `{"schema_version": 1, "stages": {<stage>: {"status", "reason", "duration_ms"}}, "reason_codes": []}`; `expires_at` is `received_at + EVENT_RETENTION_DAYS` (default 7).
- **Migrations.** `alembic -c backend/alembic.ini upgrade head` with `MIGRATION_DATABASE_URL` set to the migration owner. Repeated upgrades are no-ops; `alembic check` must report no differences. The downgrade drops the schema and is refused unless the target database name ends in `_test` and is passed explicitly (`-x allow-destructive-downgrade=<database>`); deployed databases use forward repair only.

## Redis keys

Candidate key `candidate:{identity_key_version}:{subscriber_digest}` stores only event IDs, kinds and event times with TTL 40 minutes, refreshed on write. Candidate validation always uses event time and durable records. Login/read/ingest counters have policy-defined TTLs. Never store raw text/audio/transcripts or secrets in Redis. Disable persistence for candidate state; separate namespaces for test/development. Loss of cache does not lose reviews or authoritative idempotency.

Implemented layout (M3.2; every key is prefixed `kavach:{APP_ENV}:`):

| Key | Type | Contents | Expiry |
| --- | --- | --- | --- |
| `candidate:{identity_key_version}:{subscriber_digest hex}` | sorted set | member `{kind}:{event UUID}`, score = event time (epoch ms) | 40 min, refreshed on write; members older than arrival − 40 min pruned on write; at most 1,200 members (D08 rate × 40 min), oldest evicted with an `operational_event` |
| `ratelimit:login:acct:{HMAC}` / `ratelimit:login:ip:{HMAC}` | counter | failed-login reservations (M2.3) | 15 min |
| `ratelimit:bearer:ip:{HMAC}` | counter | rejected Bearer credentials per client IP | 15 min |
| `ratelimit:ingest:key:{HMAC}` | sorted set | accepted submissions per key (request IDs, Redis-time scores) | 60 s sliding |

HMACs use `RATE_LIMIT_HMAC_KEY`; no username, IP, key material, subscriber token or content appears in a key or value. D05 (proposed, adopted for M3.2): a pair needs |Δ event time| ≤ 30 min and an arriving event may start a pair only if it is at most 10 min late, so no candidate older than 40 min can ever match. Events already older than that at arrival are not indexed. The index is only an accelerator: it creates no incidents, a candidate match is not a trusted correlation, and `python -m kavach.cli candidates rebuild` restores it from PostgreSQL (events inside the 40-minute horizon).

## Retention, migration and recovery

Proposed D07 retention: events and linked incidents/assessments/reviews expire after seven days; audit records after 30 days; expired/revoked sessions are removed promptly. A daily job first deletes expired incidents and their cascading links/assessments/reviews, then unreferenced expired events, then expired audits/sessions. Circular deferred FKs must be tested in cleanup transactions. Remove cache references opportunistically; stale IDs are ignored. Logs use bounded retention and exclude communications. Account/key records are retained while audit/history references exist; deactivation/revocation is immediate.

Backups have a documented finite retention; expired sensitive records may remain only until backup expiry. Restoring a backup must run retention cleanup before exposing service. Do not claim immediate erasure from historical backups.

Use reviewed Alembic migrations with a fresh-database path and an upgrade path. Test constraints and rollback on a disposable database. Prefer forward repair for deployed data; never drop data automatically to fix a failed migration. Seed synthetic users/events only via explicit development commands with operator-supplied passwords, not embedded defaults. Keep evaluation corpora out of production seeds.

Before a pilot: encrypted daily backups, isolated access, key recovery procedures, proposed RPO 24 hours/RTO 4 hours, and a recorded restore drill verifying incidents, reviews, constraints, HMAC verification, retention and session revocation. Local Compose volumes are persistence, not backups. Key rotation must keep old verification keys protected for the retention window; subscriber HMAC rotation requires a planned overlap or deliberate correlation-window reset.
