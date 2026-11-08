# MVP-B4 Implementation Plan: Admin Browser SMS Submission

Prepared 9 November 2026 on `backend`; **B4-1 to B4-3 approved and implemented the same day (uncommitted)**. Status: MILESTONE_TRACKER.md. Contract: [API.md](API.md) "SMS MVP-1 contract", `POST /api/v1/events/sms` admin browser path (decision A, MASTER_DEVELOPMENT_PLAN.md C-12).

## 1. Goal and non-goals

An authenticated admin submits one synthetic SMS from the browser through the **same** `POST /api/v1/events/sms` route and the **same** ingestion service the key-authenticated path uses. Idempotency, inference, the deadline and the incident write stay identical. The response adds `incident_ids` so the UI can open the result.

Not in B4:
- call submission from the browser, and admin receipt reads (`GET /events/{id}` with a session)
- simulator scenario playback, reviews, WebSocket, voice, correlation, fusion
- any change to the worker setting: `SMS_WORKER_ENABLED` stays `false` until the M4-Q decision (MVP-B2)

## 2. Decisions needed before implementation

| ID | Question | Recommendation |
| --- | --- | --- |
| B4-1 | Must session submissions use `event_id` starting `ui-` and `subscriber_token` starting `ui-sub-`, enforced by the server (422 otherwise)? | **Yes.** It keeps browser IDs out of the simulator runner's `sim-…` namespace inside the shared `simulator` source. An admin then cannot replay or conflict with runner events, and browser-submitted subscribers can never be matched with runner subscribers when M6 arrives. API.md currently says only that the client generates these; this makes it a server rule (contract addition) |
| B4-2 | Does a session submission count toward the 120 per minute read budget? | **No.** It is a write with its own limit, 30 per minute per admin |
| B4-3 | What does a request with no credential get? | **Unchanged:** 401 `INVALID_CREDENTIALS` with `WWW-Authenticate: Bearer`, as today |

## 3. Request pipeline (exact order)

Everything up to step 7 happens **before the body is read**. Every rejection up to step 10 stores nothing.

| Step | Check | Failure |
| --- | --- | --- |
| 1 | Cookie **and** `Authorization` both present | 401 `MIXED_CREDENTIALS` |
| 2 | Neither present | 401 `INVALID_CREDENTIALS` + `WWW-Authenticate: Bearer` (unchanged) |
| 3 | `Authorization` only | **Existing key path, unchanged** (Bearer throttle, key, per-key quota). Skip to step 8 |
| 4 | Cookie only: `Origin` equals `APP_ORIGIN` exactly (`require_trusted_origin`) | 403 `CSRF_REJECTED` |
| 5 | Session valid, account active (`current_session`) | 401 `SESSION_EXPIRED` |
| 6 | Role is `admin` (re-read from the database) | 403 `FORBIDDEN` |
| 7a | `X-CSRF-Token` matches the session (`require_csrf`, constant-time) | 403 `CSRF_REJECTED` |
| 7b | Per-admin submission limit: 30 per minute, Redis sliding window keyed by an HMAC of the user ID (separate namespace from keys) | 429 `RATE_LIMITED` + `Retry-After`; Redis down: 503 `DEPENDENCY_UNAVAILABLE` |
| 8 | Body at most 32 KiB, JSON, `SMSEvent` validation against the server clock | 413 / 422 `VALIDATION_ERROR` |
| 9 | Session path: `source == "simulator"` | 403 `FORBIDDEN` |
| 9b | Session path, if B4-1 is approved: `event_id` starts `ui-`, `subscriber_token` starts `ui-sub-` | 422 `VALIDATION_ERROR` |
| 10 | Idempotency lookup on `(source, external_event_id)`, then inference (only on first creation), then the commit transaction | 200 replay / 409 `EVENT_ID_CONFLICT` / 429 `CAPACITY_EXCEEDED` / 503 `DEPENDENCY_UNAVAILABLE` or `PROCESSING_TIMEOUT` |

Inside the commit transaction:
- the event row, standalone incident, link and assessment revision 1 are written as today
- the audit record has `actor_kind = "user"`, `actor_user_id = <admin>` and `action = "event.ingest"`
- PostgreSQL's unique `(source, external_event_id)` still arbitrates concurrent submissions

## 4. Exact files

| File | Change |
| --- | --- |
| `backend/src/kavach/auth/throttle.py` | `SubmissionQuota.acquire_for_user(user_id, request_id)`: same script and limit, key `kavach:<env>:ratelimit:ingest:user:<hmac("ingest-user\0"+user_id)>` |
| `backend/src/kavach/services/ingestion.py` | New frozen dataclass `SessionSubmitter(user_id: UUID, source: str = "simulator")` and type `Submitter = IngestPrincipal \| SessionSubmitter`. `ingest()` takes a `Submitter` and chooses the audit actor from its type. `Receipt` gains `incident_ids: tuple[UUID, ...]`, filled from the database only for a `SessionSubmitter`, for both a new event and a replay. No other logic changes |
| `backend/src/kavach/db/event_repository.py` | `incident_ids_for_event(db, event_id) -> list[UUID]`: live incidents linked to the event, ordered by ID |
| `backend/src/kavach/api/schemas/events.py` | `AdminEventReceipt(EventReceipt)` with `incident_ids: list[UUID]` and `AdminReceiptResponse`. `EventReceipt` itself is unchanged, so ingestor receipts still have no `incident_ids` |
| `backend/src/kavach/api/routes/events.py` | New dependency `require_submitter(request) -> Submitter` implementing steps 1–7 by calling the existing dependency functions (`require_ingest_key`, quota, `require_trusted_origin`, `current_session`, role and CSRF checks). The SMS route uses it. `submit()` applies step 9 per submitter type and returns `AdminReceiptResponse` for a session. `response_model=ReceiptResponse \| AdminReceiptResponse`, plus `responses=error_responses(...)`. The call route keeps the key-only dependency |
| `backend/contract/openapi.json` | Regenerated |
| `backend/tests/test_contract.py` | Additions in section 6 |
| `backend/tests/integration/test_admin_submission.py` | New, section 5 |
| `docs/API.md`, `docs/MILESTONE_TRACKER.md` | Implementation status; the B4-1 rule if approved |

No migration: `audit_records` already allows `actor_kind = user` with `actor_user_id`, and the runtime role already has the needed grants. No new configuration name.

## 5. Security and behaviour tests (integration, real PostgreSQL and Redis)

**Authentication and authorization**
1. An admin with valid Origin and CSRF gets 201 with `Location`, `incident_ids` equal to the stored link, and nothing else added.
2. Viewer and analyst get 403 `FORBIDDEN`; nothing is stored and the admin quota is not spent.
3. An expired session, a revoked session after logout, and a deactivated admin each get 401. An admin demoted to analyst gets 403 on the next request.
4. Cookie plus Bearer: 401 `MIXED_CREDENTIALS`. No credential: 401 `INVALID_CREDENTIALS` with `WWW-Authenticate`.

**CSRF and Origin**
5. Missing `X-CSRF-Token`, a wrong token, or a token from another session: 403 `CSRF_REJECTED`, nothing stored.
6. Missing `Origin`, `Origin: null`, a trailing slash, another scheme, port or host: 403 `CSRF_REJECTED`, nothing stored.

**Scope and validation**
7. `source` other than `simulator`: 403, nothing stored. With B4-1, an `event_id` without `ui-` or a `subscriber_token` without `ui-sub-` gets 422.
8. Oversize body (413), deep JSON (422), unknown field (422), a phone-number subscriber (422), a stale or future timestamp (422). The response never echoes values.

**Rate limits**
9. 30 admin submissions, then 429 with `Retry-After`. Invalid bodies count, because the limit runs before the body is read.
10. Two admins have independent budgets; the admin budget is independent of an ingestion key's budget.
11. Two processes cannot exceed 30 for one admin.
12. Redis down: 503, nothing stored.

**Idempotency and concurrency**
13. Same `event_id` and payload: 200 `replayed: true` with the same `incident_ids`. Changed text under the same ID: 409.
14. Two concurrent identical submissions: exactly one 201 and one 200, one event row.
15. A key-submitted runner event replayed with a session (if B4-1 is rejected): 200 with that event's incident.

**Model paths, with the test-only fake worker injected**
16. Disabled (the MVP default): `analysis_status: unavailable`, warning `SMS_CLASSIFIER_UNAVAILABLE`, reason `model_not_deployed`.
17. Fake worker ready: 201 `complete` with `SMS_SCORE_UNCALIBRATED`, and no scores or labels in the receipt.
18. Fake worker saturated: 429 `CAPACITY_EXCEEDED`, nothing stored. Starting: 503 with `Retry-After`. Fake timeout or crash: stored as unavailable.

**Audit and privacy**
19. Exactly one audit row per new event, with `actor_kind = user`, the admin's ID and no ingest key ID; replays and rejections write none.
20. Text, sender ID and subscriber token appear in no response and no log record (caplog), and are absent from Redis.
21. The incident detail for an admin-submitted event exposes no source or external ID (reuses the MVP-B3 allowlist).

**Regression**
22. The whole existing key-ingestion suite passes unchanged. Key receipts never contain `incident_ids`. `/events/call` and `GET /events/{id}` behave as before.

## 6. Contract test additions (`test_contract.py`) and snapshot

- `POST /api/v1/events/sms` 201 and 200 responses are `anyOf` of `ReceiptResponse` and `AdminReceiptResponse`. Only the admin receipt has `incident_ids`. Neither contains labels, scores, text or subscriber fields.
- The route declares the error envelope for 401, 403, 409, 413, 422, 429 and 503 plus `default`.
- The API.md receipt example (third JSON block of the MVP-1 section) validates against `AdminReceiptResponse` and round-trips to the same fields.
- The route inventory is unchanged: no new path; `/events/call` still has no session path.
- Regenerate `backend/contract/openapi.json`, review its diff, and copy it to `frontend/contract/` with the new source commit (frontend plan §14).

## 7. Verification for the B4 report

Backend default and integration suites, the incident and read-limit suites (must stay green), Ruff lint and format, `uv lock --check`, `alembic check` (no change expected) and `git diff --check`. Mutation probes:
- skip the CSRF check
- skip the Origin check
- allow the analyst role
- accept a non-`simulator` source
- write an ingestor audit actor for a session
- drop `incident_ids` on replay
- put the admin quota on the key namespace

## 8. Exact next dependency

The owner decides B4-1 to B4-3 and authorizes the implementation. MVP-F3 (`/analyze`) starts only after B4 is implemented, verified and its OpenAPI snapshot is copied to `frontend`.
