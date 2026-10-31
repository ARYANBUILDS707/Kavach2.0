# KAVACH API Contract

## Phase A/B implementation status

The user authorized a backend-only foundation after the initial specification. The current source implements `GET /health` and `GET /api/v1/health` as **public liveness aliases only**: 200 with `data.status = ok`, `data.scope = liveness`, `data.analysis_ready = false`, and a generated `request_id`. No dependency details or sensitive state are returned. This temporarily narrows the future authenticated detailed-health contract below; it does not bypass authorization for any implemented evidence route. `/api/v1/health/live` and detailed readiness are not yet implemented.

`SMSEvent` and `CallEvent` schemas are in `backend/src/kavach/api/schemas/events.py`. Their optional `kind` field defaults to `sms` or `call`; a conflicting value is rejected. Identifiers use bounded ASCII alphanumeric/underscore/hyphen syntax, with dot/colon also accepted for event and subscriber IDs. Call sample IDs exclude paths, extensions and URLs. Purely numeric/phone-like subscriber tokens are rejected as a syntax guard, not proof of authorized pseudonymization.

**Authentication (M2.3, implemented).** `POST /api/v1/auth/login`, `GET /api/v1/auth/session` and `POST /api/v1/auth/logout` follow "Authentication formats" below. Implementation details that the contract left open:

- Success bodies are `{"data": {"user": {"id", "display_name", "role"}, "expires_at", "csrf_token"}, "request_id"}`. `expires_at` is the earlier of the idle (30 min) and absolute (8 h) deadlines. Logout returns 204 and clears the cookie.
- Cookie: `__Host-kavach_session` (HttpOnly, Secure, SameSite=Lax, Path=/, no Domain, Max-Age = absolute lifetime) when `APP_ORIGIN` is https. `kavach_dev_session` without Secure is used only when `APP_ENV=development` and `APP_ORIGIN` is a plain-http loopback origin; any other http origin fails startup.
- The CSRF token is derived from the session token (HMAC), so `GET /auth/session` can return it without storing it; only its SHA-256 digest is stored. Login and logout require `Origin` to equal `APP_ORIGIN` exactly; logout also requires `X-CSRF-Token`. Either failure returns 403 `CSRF_REJECTED`.
- A request with both a session cookie and an `Authorization` header, or a login request carrying `Authorization`, returns 401 `MIXED_CREDENTIALS` (new code, listed in the error table).
- Order of checks: Origin, credential exclusivity, body validation, throttle reservation, password verification. Throttling is reserved atomically in Redis before the password is checked; if Redis cannot answer within its 0.5 s timeouts (no retries), login returns 503 `DEPENDENCY_UNAVAILABLE` without verifying the password. A database failure also returns 503.
- Without the complete authentication configuration (`APP_ORIGIN`, `RATE_LIMIT_HMAC_KEY`, `AUDIT_HMAC_KEYS`, `AUDIT_HMAC_ACTIVE_VERSION`, `DATABASE_URL`, `REDIS_URL`) the auth routes return 503; `APP_ENV=pilot` refuses to start without it, and setting only part of it fails startup.

Event POST routes are not exposed. Test-only HTTP handlers verify DTO validation without claiming ingestion, persistence, source authorization, sample-manifest membership or processing. No client-provided model scores or arbitrary feature objects are accepted. All endpoint contracts below describe later implementation unless explicitly identified above. The foundation was verified on 31 October 2026 in the local virtual environment (88 tests passed, Ruff clean); the dependency lockfile `backend/uv.lock` is still absent. See the root README and [MILESTONE_TRACKER.md](MILESTONE_TRACKER.md).

## Status and conventions

Proposed contract; implement only after relevant [PRD.md](PRD.md) decisions are approved. Follow [ARCHITECTURE.md](ARCHITECTURE.md) and [DATABASE.md](DATABASE.md). Base path `/api/v1`; JSON UTF-8; snake_case fields; UUID internal IDs; RFC 3339 timestamps with explicit timezone normalized to UTC; finite score values 0–1 or null. Reject unknown input fields. Dates without timezone are invalid.

Success body has `data` and `request_id`; list bodies also have `page` with `next_cursor` and `has_more`. Errors have `error` containing `code`, safe `message`, and optional `fields` mapping field names to safe messages, plus `request_id`. Do not echo invalid sensitive values. No stack traces, SQL, model paths or raw request bodies. Return `Cache-Control: no-store` on authenticated responses.

## Identity and permissions

Browser: server session cookie plus CSRF token header `X-CSRF-Token` for mutations and exact allowed Origin validation. Login uses Origin validation before a session exists. Ingestor: `Authorization: Bearer <scoped API key>`; keys only permit event submission and own-source receipts. Do not accept both identity mechanisms on one request. Cookie credentials never confer machine scopes. Admin may submit only simulator events through the browser.

| Endpoint | Method | Access | Purpose |
| --- | --- | --- | --- |
| `/auth/login` | POST | Public, rate limited | Start provisioned-user session |
| `/auth/session` | GET | Authenticated user | Current role and CSRF token |
| `/auth/logout` | POST | Authenticated user + CSRF | Revoke current session |
| `/events/sms` | POST | Ingestor or admin + CSRF | Analyze and persist an SMS event |
| `/events/call` | POST | Ingestor or admin + CSRF | Analyze allowlisted audio or metadata-only call |
| `/events/{id}` | GET | Own-source ingestor or admin | Recover submission receipt |
| `/incidents` | GET | Viewer, analyst, admin | Filtered incident records |
| `/incidents/{id}` | GET | Viewer, analyst, admin | Evidence, assessment and initial review page |
| `/incidents/{id}/reviews` | GET | Viewer, analyst, admin | Paginated immutable review history |
| `/incidents/{id}/review` | POST | Analyst/admin + CSRF | Append review |
| `/simulator/scenarios` | GET | Admin | Read fixed scenario and sample catalog |
| `/health/live` | GET | Public | Process liveness only |
| `/health` | GET | Viewer, analyst, admin | Dependencies and model readiness |
| `/stream` | WebSocket | Authenticated user; allowed Origin | Incident/system invalidations |

No public registration, account management API, arbitrary media upload/download, provider webhook, call-control or training endpoint is in scope. Provisioning is a secured operator command with an audit record.

## Authentication formats

- Login request: `username` string 1–80 and `password` string 1–256. Reject overlength without silently truncating. Success 200 sets cookie and returns user `{id, display_name, role}`, session expiry, and CSRF token. Wrong credentials/inactive account: generic 401 `INVALID_CREDENTIALS`.
- Session response 200: same user/expiry/CSRF fields. Expired/revoked session: 401 `SESSION_EXPIRED`.
- Logout response 204 with no body, clears cookie and revokes database session. Include request ID header. Never require client-side token deletion as the sole revocation mechanism.

## Event requests and receipts

Common request fields:

| Field | Type | Rules |
| --- | --- | --- |
| event_id | string | 1–128, bounded safe ID characters; stable across retries |
| subscriber_token | string | 1–128 opaque authorized identity; never a raw phone number |
| timestamp | string | RFC 3339; at most 60 seconds future skew; at most seven days old |
| source | string | 1–64; must equal key scope or `simulator` for admin |

SMS additionally requires `text` string 1–4096 characters; optional `sender_id` up to 64 characters is transient analysis input only. Call additionally accepts nullable `audio_reference`, an ID from the approved sample manifest. Null is valid for metadata-only calls and produces explicitly unavailable voice evidence. A non-null unknown ID is 422, not silently ignored. No supplied filesystem path, URL, base64 audio, transcript, phone number field or arbitrary metadata object.

Proposed limits: JSON request ≤32 KiB; referenced decoded audio ≤60 seconds and source file ≤10 MiB; allowlisted WAV fixtures with decoder validation. These are D08 operational assumptions. Three-second overlapping chunks are internal processing units, not evidence that a live stream exists.

Success: 201 on first durable creation; 200 on identical replay. Receipt fields: `event_id` (internal UUID), `external_event_id`, `source`, `kind`, `analysis_status`, `received_at`, `processing_ms`, `replayed`, and `warnings` (codes). For admin receipts include `incident_ids`; omit these for ingestors to preserve their restricted read scope. Persist original processing status across a replay; do not silently recompute against a new model.

Same source/event ID with changed canonical payload: 409 `EVENT_ID_CONFLICT`. Canonicalization normalizes timestamps and optional nulls consistently and preserves meaningful text differences. Raw payload HMAC keys are versioned; keep required old keys available for the retention window. A lost response may be retried using the original payload and ID. Database success is the commit boundary.

Inference failure within the deadline may return a committed partial/unavailable result with warnings. Saturation before acceptance returns 429 `CAPACITY_EXCEEDED`; deadline with no committed result returns 503 `PROCESSING_TIMEOUT`. Client uncertainty is resolved with same-ID retry or receipt lookup. The server must not let a timed-out worker later commit an untracked result.

## Incident read formats

List query parameters: `limit` integer 1–100, default 25; optional opaque `cursor`; `tier` enum including unknown; `review_status` enum `unreviewed`, `true_fraud`, `false_alarm`, `needs_investigation`; `kind` standalone/pair; `from` inclusive and `to` exclusive RFC 3339 event-time bounds. Reject invalid ranges. No subscriber lookup or unrestricted text search in MVP.

Sort by `occurred_at DESC, id DESC`. Cursor binds this tuple and active filters; validate schema and bounds, never interpolate it into SQL. Feed ordering is stable because occurred_at is immutable. New rows require refresh; review-status changes can alter filtered membership, which the UI must explain. Pagination is not a transactional historical snapshot.

List item fields: `id`, `kind`, `occurred_at`, `tier`, nullable `final_score`, `analysis_status`, `current_revision`, `version`, `latest_review` summary or null, `updated_at`. Counts, if returned, count incident records, not unique attacks.

Detail adds `events` with sanitized channel/time/availability/score/model fields; `assessment` with base/fusion/final score, structured reason codes, policy/model versions, time delta and match checks; `related_incident_ids`; and first `reviews` page. Never expose subscriber digests, payload digests, raw text, audio paths, transcript, credentials or audit signatures. No score is labeled calibrated probability without supporting model metadata.

Reviews GET uses limit 1–100/default 25 and a cursor over `(created_at, id)` ascending. Review response fields: `id`, `assessment_revision`, `decision`, sanitized `note`, reviewer display name/ID and `created_at`. Inaccessible and missing resources return the same safe 404.

## Review mutation

Header `Idempotency-Key` is a client-generated UUID reused for retries of the same save. Body: `decision` enum, nullable `note` ≤1000 characters, `assessment_revision` positive integer, and `expected_version` positive integer from incident detail.

Within a transaction: resolve prior idempotent request first; same key/payload returns 200 original review even if current version advanced. Different payload under same key returns 409 `IDEMPOTENCY_CONFLICT`. For a new key, lock incident, confirm current revision and expected version, append review and audit, update latest_review_id and increment incident version. First success 201 returns review, new incident version and request ID. Stale version/revision returns 409 `REVIEW_CONFLICT`; UI retains draft and requires comparison before retry.

No PUT/PATCH/DELETE reviews. Notes are plaintext rendered safely and screened for obvious sensitive patterns; reject rather than persist detected secrets. Imperfect screening means notes remain sensitive and share incident retention.

## Live updates and simulator

WebSocket `/stream` uses the browser session and Origin checks. Messages: `incident_changed` with ID/version; `system_changed` with a safe status; heartbeat without evidence. No user-provided subscription to arbitrary source scopes. Revalidate sessions at least every minute, close expired connections, bound outgoing buffers and disconnect slow consumers. No reliable replay log is promised. On reconnect refetch the current REST view; if disconnected poll every 10 seconds with jitter and backoff. Do not clear stale evidence until replacement arrives or access expires.

Simulator catalog returns synthetic scenario ID/name/description, ordered SMS/call templates, and allowlisted sample IDs/display labels. It contains no real communications. The browser replaces scenario timestamps with fresh controlled timestamps and generates stable run-specific event IDs. Submission uses the ordinary event endpoints; no bypass to fabricate scores. Expected qualitative results are visibly separated from actual outputs.

## Errors and rate limiting

| HTTP | Code examples | Client behavior |
| --- | --- | --- |
| 400 | INVALID_CURSOR | Correct request; preserve filters |
| 401 | INVALID_CREDENTIALS, SESSION_EXPIRED, MIXED_CREDENTIALS | Authenticate; clear protected client state; send exactly one credential type |
| 403 | FORBIDDEN, CSRF_REJECTED | Explain access restriction; no retry loop |
| 404 | NOT_FOUND | Resource unavailable/expired |
| 409 | EVENT_ID_CONFLICT, REVIEW_CONFLICT | Resolve conflict; never overwrite silently |
| 413 | PAYLOAD_TOO_LARGE | Reduce input |
| 422 | VALIDATION_ERROR, UNKNOWN_AUDIO_REFERENCE | Field-level correction |
| 429 | RATE_LIMITED, CAPACITY_EXCEEDED | Honor Retry-After |
| 500 | INTERNAL_ERROR | Request ID and safe retry guidance |
| 503 | DEPENDENCY_UNAVAILABLE, PROCESSING_TIMEOUT | Backoff; same-ID retry for writes |

D08 proposal: failed login 5/15 minutes per account+IP plus IP ceiling 30/15 minutes; reads 120/minute/user; ingestion 30/minute/key or admin; reviews 30/minute/user; WebSocket 2 concurrent connections/user. Trusted proxy IP handling must be configured explicitly. Redis counters store short-lived keyed identifiers (HMAC with `RATE_LIMIT_HMAC_KEY`), not raw IP histories. **Login (C-06, approved 31 October 2026):** login throttling is always shared through Redis; if Redis cannot validate throttle state, `POST /auth/login` fails closed with 503 `DEPENDENCY_UNAVAILABLE` before any password check, and there is no in-process fallback. For the other limits (reads, ingestion, reviews) a Redis outage rejects writes if enforcement cannot be assured; whether reads may use conservative in-process limits is decided in M3. Revisit before multiple replicas.

## External integrations and webhooks

Required services are local PostgreSQL, Redis and model artifacts. Runtime audio/text must not leave the environment for hosted inference. Model acquisition is an operator build/provisioning step with license and checksum verification. No MCP connection, telecom integration or webhook is currently required. A future provider integration must first add approved endpoints, credentials, schema, timeouts and idempotency rules here; verify signatures on original webhook bytes and enforce replay limits if that provider uses webhooks.

## Environment variables

| Variable | Location | Purpose |
| --- | --- | --- |
| APP_ENV | Server | development, test or pilot |
| APP_ORIGIN | Server/proxy | Exact browser origin and redirect/Origin allowlist |
| DATABASE_URL | Secret server config | Runtime PostgreSQL credentials; `postgresql+psycopg://` URL for the least-privilege runtime role (validated when set since M2.1) |
| MIGRATION_DATABASE_URL | Secret operator config | Separate migration credentials |
| RETENTION_DATABASE_URL | Secret job config | Restricted expiry job credentials |
| REDIS_URL | Secret server config | Private Redis endpoint/auth; `redis://` or `rediss://` URL (validated when set since M2.1) |
| RATE_LIMIT_HMAC_KEY | Secret server config | Key for the keyed identifiers in Redis throttle counters; required once login throttling exists (M2.3) |
| SUBSCRIBER_HMAC_KEYS / SUBSCRIBER_HMAC_ACTIVE_VERSION | Secret server config | Versioned identity digest keys and selected version |
| PAYLOAD_HMAC_KEYS / PAYLOAD_HMAC_ACTIVE_VERSION | Secret server config | Versioned idempotency digest keys |
| AUDIT_HMAC_KEYS / AUDIT_HMAC_ACTIVE_VERSION | Secret server/job config | Versioned audit signing/verification keys; JSON object `{"<version>": "<32+ character secret>"}` (M2.3) |
| MODEL_DIR / MODEL_MANIFEST_PATH | Server | Trusted local model assets |
| AUDIO_SAMPLE_MANIFEST_PATH | Server | Allowlisted controlled samples |
| POLICY_PATH | Server | Approved versioned thresholds/window configuration |
| INFERENCE_DEVICE | Server | Explicit CPU/GPU selection |
| MAX_INFLIGHT_ANALYSES / INFERENCE_TIMEOUT_SECONDS | Server | Bounded admission/deadline |
| EVENT_RETENTION_DAYS / AUDIT_RETENTION_DAYS | Server/job | Approved expiry policies |
| SESSION_IDLE_MINUTES / SESSION_MAX_HOURS | Server | Approved session limits; defaults 30 and 8 (M2.3) |
| LOG_LEVEL | Server | Structured safe logging verbosity |

Use a documented JSON map or secret-file references for versioned key sets; never include real values in examples. API keys and account passwords are provisioned securely, not hardcoded environment defaults. Relative same-origin browser URLs require no frontend secrets. Bootstrap secret input must not appear in command history or logs.

## Verification

Contract tests must cover every role/endpoint, malformed values, null scores, limits, duplicate/concurrent ingestion, stale review/idempotent retry, session expiry/CSRF, cursor filters, disconnect recovery, privacy-safe responses and dependency failures. Generate OpenAPI from implemented DTOs and compare against this contract; document any approved change before dependent clients ship.
