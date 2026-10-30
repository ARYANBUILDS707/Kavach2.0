# KAVACH Master Development Plan

## Status and authority

Prepared 31 October 2026 under milestone M0 and revised the same day after owner decisions on conflicts C-01–C-07 and C-10 and on Git policy. This is a plan, not evidence that any milestone beyond M1 has run. Statements of verified status are point-in-time (see MILESTONE_TRACKER.md); historical results are labeled as such and must be re-run before being relied on. Execution status lives in [MILESTONE_TRACKER.md](MILESTONE_TRACKER.md); dated results belong in task reports.

Precedence when documents disagree: [AGENTS.md](../AGENTS.md) → [PRD.md](PRD.md) → [API.md](API.md) / [DATABASE.md](DATABASE.md) / [ARCHITECTURE.md](ARCHITECTURE.md) / [DESIGN.md](DESIGN.md) → this plan and [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). This plan reorders and groups work; it does not change a product requirement, API field, table or policy value. Anything it cannot reconcile is recorded in "Mapping conflicts" and is not silently resolved.

Companion documents: [GIT_WORKFLOW.md](GIT_WORKFLOW.md), [MILESTONE_TRACKER.md](MILESTONE_TRACKER.md), [DEFINITION_OF_DONE.md](DEFINITION_OF_DONE.md), [INTEGRATION_PLAN.md](INTEGRATION_PLAN.md), [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).

## Engineering rules (apply to every milestone)

1. PostgreSQL is the authoritative store for events, receipts, idempotency, incidents, assessments, reviews, sessions and audit. Redis holds only temporary correlation candidates, cache and rate counters; losing Redis loses no authoritative record.
2. Authentication and authorization are server-side on every route and WebSocket, including active-account and source-scope checks. Frontend hiding is convenience only.
3. Idempotency uses a keyed HMAC over the canonical validated payload, stored in PostgreSQL: 201 on first durable creation, 200 on identical replay, 409 `EVENT_ID_CONFLICT` on a changed payload. Success is returned only after commit.
4. No live telecom interception, no automatic call blocking, no account freezing, no external LLM or hosted inference, no public signup.
5. No invented ML predictions or performance claims. Runtime never substitutes mock scores; missing artifacts yield `unavailable`/`partial` with a reason. Test doubles stay in tests. V4 figures (91% recall, 0.4% false positives, 810 ms, 120 streams/GPU) are reported history, not targets.
6. SMS and voice-intent risk stay independent. Expired, absent or unrelated correlation never reduces independently established risk. Base risk is the maximum available SMS/voice-intent score.
7. Synthetic speech alone is never fraud and never raises base risk. `synthesis_score` is displayed separately.
8. Missing evidence is `null` with a reason, never zero, never "safe". No available base signal means tier `unknown`.
9. History is append-only: assessments and reviews are new rows; analyst identity and viewed assessment revision are recorded. No UPDATE/DELETE on reviews or assessments by the runtime role.
10. Routes stay thin (validation, auth dependency, call service, map result). Business rules live in services/domain modules; SQL lives in repositories; ORM entities in `db/`; inference adapters in `models/`.
11. The user performs every Git mutation (staging, commits, pushes, merges, branch switches, pull requests) and every deployment or GitHub settings change; agents use read-only Git commands only.
12. Backend milestones M1.1–M7a stay on `backend`. Backend work reaches `dev` through a single `backend` → `dev` integration pull request after the complete backend passes acceptance testing; there is no per-milestone pull request into `dev`. Frontend work (M7b) stays on `frontend`. `main` holds validated releases only ([GIT_WORKFLOW.md](GIT_WORKFLOW.md)).

## Milestone-to-phase mapping

The user-approved M0–M11 labels are the working labels. "Phase N" refers to [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

| Milestone | Spec phase(s) | Fit |
| --- | --- | --- |
| M0 | Phase 0 (docs and decisions part) | Partial: decisions D01–D10 are not all recorded (see decisions below) |
| M1 | Phase 1 (backend part) | Partial: frontend, Compose, CI and `/health/live` of Phase 1 remain |
| M1.1 | Phase 1 task 4 (lint/test scripts, reproducibility) | Added gate before M2 by owner decision: lockfile, Ruff pin and minimal pytest + Ruff CI |
| M2 | Phase 2 | Direct |
| M3 | Phase 3 task 4–5, Phase 6 task 1 (catalog), Redis parts of Phases 3–4 | Reordered/split as approved: see C-01, C-02, C-03 |
| M4 | Phase 3 task 1 | Direct |
| M5 | Phase 3 tasks 2–3 | Direct |
| M6 | Phase 4 | Direct |
| M7 | Phase 5, Phase 1 frontend scaffold | Split as approved into M7a backend and M7b frontend: see C-04 |
| M8 | Phase 6 tasks 2–4, Phase 5 browser journeys | Grouped |
| M9 | Phase 7 tasks 1 and 4 | Direct |
| M10 | Phase 7 tasks 2–3 | Direct |
| M11 | Phase 8, Phase 1 tasks 3–4 (final form) | Grouped: see C-05 |

## Mapping conflicts

Each conflict is recorded with the interim handling this plan assumes. Items marked **needs approval** are not settled.

| ID | Conflict | Decision / handling | Status |
| --- | --- | --- | --- |
| C-01 | Phase 3 orders models before ingestion; the approved order puts ingestion (M3) before SMS (M4) and voice (M5). | **Approved 31 Oct 2026.** Before ML models exist, every model output is `null` with a reason code and analysis is never represented as safe or zero. Wire/database terms follow DATABASE.md and API.md unchanged: scores `null`, `analysis_status = unavailable`, assessment tier `unknown` (final score `null`). No new enum value is introduced. M4/M5 plug adapters into the same service. | Resolved |
| C-02 | The Redis candidate cache is a Phase 4 item; M3 includes Redis temporary state. | **Approved.** Redis candidate state (post-commit sanitized candidate IDs, counters, readiness) may be introduced early. Correlation and pairing logic, candidate lookup used for matching, and pair incidents belong to M6. | Resolved |
| C-03 | The simulator is Phase 6; M3 includes the controlled simulator. | **Approved.** M3 delivers the scenario catalog (`GET /simulator/scenarios`, admin), the allowlisted sample manifest, and a submission script that uses the ordinary event endpoints. The simulator UI is deferred to M8. | Resolved |
| C-04 | Phase 5 backend work has no backend milestone among M2–M6. | **Approved.** M7a (branch `backend`): incident/review APIs. M7b (branch `frontend`): the interface. M7b depends on M7a. | Resolved |
| C-05 | M2 needs real PostgreSQL for integration tests; Docker deployment is M11. | **Approved.** M2 may create a development/test-only PostgreSQL Compose configuration (not a deployment artifact). The tooling and image/package choices still fall under D02 approval. | Resolved (D02 pending) |
| C-06 | Login throttling is specified on Redis counters (API.md, D08), while login ships in M2 and Redis was planned for M3. | **Decided by the owner, 31 Oct 2026.** M2 must implement shared login throttling (state shared across processes, not held in one process). If the shared throttle is unavailable, password login fails closed (no login attempt is processed). No in-process fallback is implemented for authentication, and a process-local throttle never counts toward M2 acceptance. M2 therefore needs the shared store in its development/test setup (Redis per API.md; its client, image and version fall under D02 approval and are still pending). Ingestion-key authentication does not use login throttling. **Recorded specification conflict:** API.md ("Redis outage uses conservative in-process limits for this single-process MVP or rejects writes if enforcement cannot be assured") and ARCHITECTURE.md ("conservative local throttling or fail-closed for writes if limits cannot be enforced") allow an in-process fallback; for login this decision overrides that option. Those two documents are not edited here; they need an approved contract update before M2 so the specifications agree. The fallback remains a separate open question for non-login rate limits (reads, ingestion, reviews). | **Decided; spec update pending** |
| C-07 | `/health` is public liveness today; API.md makes `/health` authenticated and puts public liveness at `/health/live`. | **Deferred by the owner.** The M1 endpoints (`GET /health`, `GET /api/v1/health`) and their tests are preserved unchanged until a separately approved compatibility plan exists. No milestone changes them. Authenticated detailed readiness (M8) is planned without altering the M1 routes; its path is decided in the compatibility plan. | Deferred |
| C-08 | Handoff milestone order (Redis ingestion in M2, PostgreSQL in M3) disagrees with the specifications. | Superseded by the owner's decision of 31 October 2026: PostgreSQL first, ingestion second, Redis never authoritative. | Resolved |
| C-09 | Schema timing: Phase 2 allows creating all tables together for deferred FKs. | M2 creates the full DATABASE.md schema; domain behavior stays phased. | Resolved (per Phase 2 text) |
| C-10 | CONTRIBUTING.md had no branch rules. | CONTRIBUTING.md now documents the branch workflow and PR policy and points to GIT_WORKFLOW.md. | Resolved |

## Unresolved decisions

None of these is selected by this plan. The owner's 31 October 2026 decisions on conflicts and Git policy do not approve D03, D04, D07, D10 or any package choice; each remains pending explicit approval. Each entry lists the existing proposal and what still needs approval. D01 and D02 were approved only for the backend foundation; D05–D09 remain proposals in [PRD.md](PRD.md).

### D03 — Authentication

- **Existing proposal:** operator-provisioned accounts; no signup or reset email; Argon2id password hashes; opaque database-backed sessions stored as digests (HttpOnly, SameSite=Lax, host-only cookie; proposed idle 30 min, absolute 8 h); session-bound CSRF plus exact Origin checks; roles viewer/analyst/admin; machine ingestion keys scoped to one `source`, digest-only at rest, with expiry. OIDC and multi-tenancy are not part of the MVP.
- **Still requires approval before M2 implementation:** the proposal as a whole; role permissions; session durations; ingestion-key format, lifetime and rotation; password policy; provisioning command interface; Argon2 library and parameters; and the shared throttle store, client and configuration (C-06 requires shared login throttling in M2 with fail-closed login; the store itself is not yet approved).

### D04 — Dataset and model provenance

- **Existing proposal:** TF-IDF logistic SMS baseline; local Whisper-tiny; versioned acoustic and intent baselines; three-second chunks with proposed one-second stride; English first, Hindi/Hinglish experimental.
- **Still requires approval before M4/M5:** named datasets with licenses, permitted use and label provenance; language scope; voice-intent model approach; chunk aggregation rule; artifact sources and checksums; hardware for training and inference; which ML dependencies may be added. If data or artifacts are unavailable, M4/M5 report that blocker; they do not substitute demo scores.

### D10 — Hosting

- **Existing proposal:** local Compose first.
- **Still requires approval before any external provisioning or pilot (M11):** provider, region, hardware, domain/TLS, operating authority, data policy for any non-synthetic data, backup budget, and RPO/RTO acceptance. A local demo release does not require resolving D10 beyond "local only".

### Other decisions gating milestones

| Decision | Gates | Note |
| --- | --- | --- |
| D02 (full stack and package choices) | M1.1 and M2 dependencies: SQLAlchemy, Alembic, psycopg, Argon2 library, Redis client (if used in M2), the PostgreSQL/Redis container images, CI actions | **Pending explicit approval** of exact packages and versions before installing; a recorded reason per dependency |
| D05 | M6 | Window 30 min, lateness 10 min, standalone/pair semantics, base-risk floor |
| D06 | M6 | Tier bands; recalibrate before any pilot |
| D07 | M2 schema (`expires_at`), M9 | Seven-day evidence retention, 30-day audit retention. **Pending explicit approval**; the schema cannot be finalized without it |
| D08 | M3 | Rate limits, 2 concurrent analyses, 30 s deadline; load-test before treating as fixed |
| D09 | M7 | UI tokens and English-first evaluation |

## Milestones

Common to every milestone: the checks, reporting and PR conditions in [DEFINITION_OF_DONE.md](DEFINITION_OF_DONE.md) apply in addition to the milestone items. "Proposed" values come from the existing specifications and stay proposals until approved.

### M0 — Repository, architecture alignment, workflow and reproducibility planning

- **Objective:** one consistent plan, Git workflow and definition of done before feature code. **Prerequisites:** M1 baseline `754a22a`; branches exist.
- **Tasks and deliverables:** the six engineering documents; correct stale status statements in IMPLEMENTATION_PLAN.md, API.md, README.md and ARCHITECTURE.md; add the branch workflow and PR policy to CONTRIBUTING.md; record D03/D04/D07/D10 and package choices as pending approval, and tech debt (lockfile, Ruff pin).
- **Branch:** `dev`. **API/DB dependencies:** none.
- **Tests:** none executed; verification is review that cross-references resolve and no source or test file changed (`git diff --stat`).
- **Acceptance:** six files exist; `git diff --name-only` lists only documentation files (`docs/*`, `README.md`, `CONTRIBUTING.md`); `git diff --check` is clean; relative links resolve; every milestone has all items below; every conflict is recorded.
- **Exit:** owner reviews the documentation diff and approves; commit and PR only on request.
- **PR/merge:** committed directly to `dev` as `a74f420` with explicit owner approval at the time (no PR); documentation only.
- **Risks/assumptions:** GitHub settings (default branch, protection) are intentions only and are not applied. **Unresolved:** the API.md/ARCHITECTURE.md wording on in-process fallbacks (recorded under C-06), C-07 (deferred), and decisions D02, D03, D04, D07, D10.

### M1 — FastAPI foundation (complete)

- **Objective:** a runnable, tested backend skeleton. **Delivered at `754a22a`:** `kavach.main:create_app`, two public liveness routes, `SMSEvent`/`CallEvent` DTOs, settings (`APP_ENV`, `LOG_LEVEL`), safe error envelope, 88 tests, Ruff.
- **Verified:** 31 October 2026 audit: 88 passed, Ruff check and format clean. Live HTTP startup was verified in the earlier 28 October report, not re-run in the audit.
- **Historical vs current:** live HTTP startup was last verified on 28 October 2026 (reported in README); pytest/Ruff results are from the 31 October 2026 audit. Both are point-in-time and are re-run as part of M1.1.
- **Open items carried forward:** no `backend/uv.lock`; installed Ruff 0.17.3 vs pinned 0.17.2; no CI. Public `/health` vs API.md is deferred (C-07): the M1 routes and tests stay unchanged. Tracked as technical debt, not hidden.
- **Branch:** history on `main`. Further changes follow normal workflow.

### M1.1 — Reproducible environment and minimal CI (pre-M2 gate)

- **Objective:** a clean checkout installs from a lockfile and every `backend` push (and every PR into `dev`/`main`) runs pytest and Ruff automatically. Approved on 31 October 2026 as a pre-M2 milestone (not part of the original M0–M11 list); implemented on `backend` and committed by the user as `c8c2ec7`; the first CI run is still pending. **Prerequisites:** M0 approved; the package/network actions below approved; `dev` current.
- **Tasks and deliverables:** diagnose the earlier `uv sync` PyPI timeout before retrying (no blind reruns); generate `backend/uv.lock` through a successful resolver run; resolve the Ruff pin versus the installed 0.17.3 (either pin the installed version or install the pinned one, recorded with the reason); a minimal GitHub Actions workflow that runs `pytest backend/tests`, `ruff check backend` and `ruff format --check backend` on pull requests into `dev` and `main`, with actions pinned by version; update README/CONTRIBUTING commands to the `--locked` forms.
- **Branch:** `backend` (owner instruction; the earlier `feature/m1-1-ci` plan was not used). **API/DB:** none.
- **Tests:** the existing 88 tests are the CI payload; no behavior changes. Verify a clean clone installs with `uv sync --project backend --locked` and CI passes on the PR.
- **Acceptance (measurable):** `backend/uv.lock` committed; clean-clone `uv sync --locked` succeeds and the three commands pass with the recorded counts; CI run is green on the PR; installed and pinned Ruff versions agree.
- **Exit:** DoD met. Only after this milestone are branch protection rules for `main` and `dev` proposed (required PR, required status check, no force-push); applying them still needs separate owner approval.
- **PR/merge:** committed on `backend` by the user (`c8c2ec7`); no PR into `dev` (single integration PR after M7a). Exit requires a green CI run on a `backend` push.
- **Risks/assumptions:** network access to the package index; GitHub Actions usage and action versions need approval. **Unresolved:** D02 (tools and action versions), whether the earlier timeout was network-specific.

### M2 — PostgreSQL persistence, migrations, identity, scoped authentication, audit foundations

- **Objective:** durable constraints and trustworthy identity before any evidence is accepted. **Prerequisites:** M0 approved; M1.1 complete; D02 packages, D03 and D07 **explicitly approved** (not yet); a decision on login throttling (C-06); secrets supplied outside Git. Maps to Phase 2.
- **Tasks and deliverables:**
  - A development/test-only PostgreSQL Compose configuration (approved under C-05; not a deployment artifact).
  - Alembic migrations for the full DATABASE.md schema with check constraints, deferred FKs and cardinality trigger; migration-owner, runtime and retention roles with least privilege.
  - SQLAlchemy entities in `db/`; repositories; transaction helper.
  - Operator provisioning/deactivation commands for users and ingestion keys (audited, no default passwords).
  - Argon2id hashing, random session/key tokens stored as digests, session/logout, cookie flags, CSRF and Origin checks, active/role dependency, rejection of mixed credential mechanisms; scoped ingestion-key authentication.
  - Shared login throttling (C-06, decided): failed-login limits per account+IP and an IP ceiling per API.md/D08, held in a store shared across processes (Redis per API.md, in the M2 development/test setup). If the shared throttle is unavailable, `POST /auth/login` fails closed with a documented dependency-unavailable response and processes no password check. No in-process fallback exists for authentication.
  - HMAC audit signing with versioned keys and transactional append; expiry cleanup for sessions and evidence tables.
  - Config validation at startup for required secrets; `.env.example` placeholders only.
- **Branch:** `backend`. **API:** `GET /auth/session`, `POST /auth/logout`, and `POST /auth/login` (with shared throttling, fail-closed). **Database:** all tables in DATABASE.md.
- **Tests:**
  - Unit: password hashing parameters, token generation, canonical audit HMAC, clock-injected expiry.
  - Integration (real PostgreSQL): fresh migration and upgrade; a violating insert for each constraint; deferred-FK circular cleanup; privilege tests per role; audit rollback on sign failure; session expiry/revocation.
  - Security: role/endpoint matrix, session fixation, CSRF/Origin denial, generic login errors, inactive account, password/token absent from logs.
- **Acceptance (measurable):** `alembic upgrade head` succeeds on an empty database and the upgrade path test passes; every implemented endpoint-role pair in the matrix has a test with the expected 200/401/403 (including login), plus shared-throttle tests: failed attempts counted across separate processes reject the attempt beyond the configured limit, and login returns the documented failure and checks no password when the shared store is unreachable; runtime role cannot UPDATE/DELETE reviews, assessments or audit rows (test asserts the database error); a log-capture test finds no password or token.
- **Exit:** DoD met; the M2 report lists commands and results; migration reviewed by the owner.
- **PR/merge:** stays on `backend` (no PR into `dev`); the owner reviews the milestone report and diff, migrations explicitly; no destructive migration; CI green on the pushed `backend` commit.
- **Risks/assumptions:** Redis (or the approved shared store) enters M2 earlier than first planned; Argon2 and driver packaging on Apple Silicon; a Redis outage makes password login unavailable, which blocks browser journeys and the admin simulator until restored. **Unresolved:** D02 (store, client, images), D03, D07, and the API.md/ARCHITECTURE.md fallback wording (C-06).

### M3 — Authenticated ingestion, transactional idempotency, Redis temporary state, controlled simulator

- **Objective:** accept authorized events exactly once, durably, with explicit unavailable analysis. **Prerequisites:** M2 accepted on `backend` (CI green); D08 approved; HMAC key variables defined. Maps to Phase 3 tasks 4–5 and Phase 6 task 1 (C-01–C-03, approved).
- **Tasks and deliverables:**
  - `POST /events/sms`, `POST /events/call`, `GET /events/{id}` per API.md, reusing the M1 DTOs; ingestor key (own source) or admin with CSRF (`simulator` source only); `source` must equal key scope.
  - Canonical-payload HMAC with versioned keys; unique `(source, external_event_id)`; 201/200/409; replay returns the original receipt without recomputing.
  - Bounded admission (2 concurrent analyses), 30 s deadline with a killable worker, 429 `CAPACITY_EXCEEDED`, 503 `PROCESSING_TIMEOUT`/`DEPENDENCY_UNAVAILABLE`; request-size limit 32 KiB.
  - Inference port: until M4/M5 every model output is `null` with a reason code, `analysis_status` is `unavailable`, and the assessment tier is `unknown` with a `null` final score; never safe, never zero (C-01). Sanitized event, standalone incident and initial assessment in one transaction with audit; subscriber advisory lock.
  - Redis: ingest/read counters (and login throttling if not already provided in M2), readiness check, post-commit sanitized candidate write (TTL 40 min); documented outage behavior (fail closed for writes if limits cannot be enforced). No pairing or matching logic (C-02).
  - Controlled scenario catalog (`GET /simulator/scenarios`, admin) and sample manifest; submission script through the ordinary endpoints; unknown `audio_reference` → 422 `UNKNOWN_AUDIO_REFERENCE`. The simulator UI is not part of M3 (C-03; M8).
- **Branch:** `backend`. **API/DB:** event endpoints and receipt; `events`, `incidents`, `incident_events`, `assessments`, `audit_records`; Redis namespaces.
- **Tests:**
  - Unit: canonicalization, payload HMAC, admission control, deadline.
  - Integration (real PostgreSQL and Redis): duplicate and concurrent same ID leave one row; changed payload 409; lost-response retry; rollback on audit failure; Redis down; DB down gives 503 with no receipt; timed-out worker commits nothing.
  - Security: key cannot read another source's receipt; key cannot reach incident or admin routes; forged `source`; path/URL/base64 audio references rejected; no raw text in DB, Redis, logs or error bodies (privacy scan).
- **Acceptance (measurable):** N concurrent submissions of one event ID produce exactly one `events` row (test with a stated N); every documented status code is produced by a test; stored `signals` contain no free text; a replay returns identical receipt fields with `replayed=true`.
- **Exit:** DoD met; the report states plainly that all model outputs are `null`, analysis is `unavailable`, and no model ran.
- **PR/merge:** stays on `backend`; milestone report and CI green on the pushed commit.
- **Risks/assumptions:** synchronous inference deadline mechanism (process pool) is a design choice to confirm in review; the admin simulator path needs browser session login, which fails closed when the shared throttle is unavailable (C-06). **Unresolved:** D08 values pending load tests.

### M4 — SMS phishing detection and reproducible evaluation

- **Objective:** a real, versioned SMS score with honest evaluation. **Prerequisites:** M3 accepted on `backend`; D04 for SMS data and ML dependencies approved. Maps to Phase 3 task 1.
- **Tasks and deliverables:** dataset manifest (source, license, hashes), leakage-resistant split by campaign/source where the data allows, TF-IDF logistic training in `experiments/`, checksummed artifact and manifest, `models/` adapter returning score, structured reason codes, version and duration; integration into ingestion; unavailable behavior when the artifact is missing.
- **Branch:** `backend`. **API/DB:** none new; populates `sms_score`, `signals`, `model_versions`.
- **Tests:** unit (feature extraction, adapter contract); one separate real-artifact smoke test; evaluation script rerun reproduces the recorded metrics; leakage check; benign OTP, phishing, obfuscation and unknown-language cases; missing-artifact degradation; privacy scan of persisted `signals`.
- **Acceptance (measurable):** the evaluation report lists TP/FP/TN/FN, precision, recall, FPR, exact denominators, confidence intervals and the split definition; rerunning yields the same metrics from the same inputs; artifact digest matches the manifest. **No accuracy threshold is claimed here; any target must be approved by the owner after seeing the report.**
- **Exit:** DoD met; limitations (language, data source) stated in the report.
- **PR/merge:** stays on `backend`; model binaries stay out of Git (stored per `.gitignore` rules).
- **Risks/assumptions:** dataset availability and licensing; keyword baselines are not proof of fraud. **Unresolved:** D04.

### M5 — Voice transcription, conversational fraud intent, separate synthetic-speech indication

- **Objective:** independent voice-intent and synthesis outputs from allowlisted audio. **Prerequisites:** M3 accepted on `backend`; D04 for voice data, Whisper-tiny provenance and ML dependencies; M4 recommended first for shared model-manifest code. Maps to Phase 3 tasks 2–3.
- **Tasks and deliverables:** bounded WAV decode (≤10 MiB, ≤60 s, validated), chunking, local Whisper-tiny adapter, intent classifier adapter, acoustic synthesis adapter, each with its own manifest, version and status; chunk aggregation rule documented and evaluated; killable inference worker; metadata-only calls yield explicit unavailable voice evidence.
- **Branch:** `backend`. **API/DB:** populates `voice_intent_score`, `synthesis_score`, `signals`.
- **Tests:** unit (decoder bounds, chunking, aggregation); real-artifact smoke test; human scam with low synthesis keeps its intent score; benign synthetic IVR is not escalated by synthesis alone; silent/corrupt/noisy audio gives a failed stage with a reason, not zero; STT outage degrades intent only; timeout kills the worker and commits nothing.
- **Acceptance (measurable):** evaluation report with denominators, speakers/campaign split and unevaluated groups labeled; synthesis never contributes to base risk (test); every failed stage is recorded as `unavailable`/`failed` with a reason code.
- **Exit:** DoD met; hardware and latency stated per stage for the named machine.
- **PR/merge:** stays on `backend`; milestone report and CI green on the pushed commit.
- **Risks/assumptions:** model licensing, CPU latency, language coverage (English-first), dataset scarcity. **Unresolved:** D04.

### M6 — Trusted subscriber/time/context correlation and continuous-score fusion

- **Objective:** link authorized SMS/call pairs and fuse continuous evidence without suppressing independent risk. **Prerequisites:** M4 and M5 accepted on `backend` (or an approved reduction of scope); D05, D06 approved; paired labeled data for fusion. Maps to Phase 4.
- **Tasks and deliverables:** subscriber-scoped event-time candidate matching with Redis lookup and authoritative PostgreSQL query inside the advisory lock; pair incidents with unique membership; late-event handling (`late_event`, standalone only); continuous logistic fusion with versioned feature order, units, coefficients and calibration metadata; base-risk floor and tier policy; structured reason codes; append-only assessment revisions.
- **Branch:** `backend`. **API/DB:** extends receipts (`incident_ids` for admin) and evidence DTOs; no unapproved columns.
- **Tests:** both arrival orders; concurrent SMS/call; exact 30-minute and 10-minute boundaries; cross-subscriber rejection; brand-only and unrelated close-time rejection; missing signal (fusion unavailable, base-only); cache loss falls back to PostgreSQL; high standalone score after window expiry stays high; borderline pair reaching meaningful fusion.
- **Acceptance (measurable):** boundary tests at ±1 s around each limit pass; exactly one pair incident per eligible pair under concurrency; final score ≥ base score in every test; held-out ablation (SMS-only, voice-only, rule fusion, learned fusion) is reproducible. **A fusion improvement is claimed only if measured against baselines at a comparable operating point; otherwise the feature ships labeled experimental.**
- **Exit:** DoD met; limitations and sample sizes in the report.
- **PR/merge:** stays on `backend`; policy version constants reviewed; CI green on the pushed commit.
- **Risks/assumptions:** fusion training data size; time-skew handling; the final-score maximum policy is uncalibrated. **Unresolved:** D05, D06.

### M7 — React/TypeScript analyst dashboard

- **Objective:** an analyst can triage, inspect and review real backend data. **Prerequisites:** M3 accepted on `backend` (M6 for pair content); D09 approved; D02 frontend tooling approved. Maps to Phase 5 and the frontend scaffold of Phase 1.
- **Tasks and deliverables:**
  - **M7a (branch `backend`):** incident list/detail and review-history APIs with cursor and filter validation; review POST with `Idempotency-Key`, expected-version and revision checks, transactional append and audit; viewer/analyst/admin enforcement.
  - **M7b (branch `frontend`):** Vite/React/TS scaffold with strict TypeScript and lockfile; DESIGN.md tokens and shared components; login/session/protected routes; incident feed, detail/timeline, review form with draft protection; first-load/empty/error/stale/forbidden states.
- **API/DB:** `/incidents`, `/incidents/{id}`, `/incidents/{id}/reviews`, `/incidents/{id}/review`, `/auth/*`; no new tables.
- **Tests:** backend filter/pagination stability, concurrent review conflict (409 `REVIEW_CONFLICT`), idempotent retry, altered payload under same key (409 `IDEMPOTENCY_CONFLICT`), viewer denial, same 404 for missing and inaccessible; frontend component tests (Vitest/Testing Library) and type-check; no credentials or raw communications in browser storage or URLs.
- **Acceptance (measurable):** analyst journey (feed → detail → save review → reload shows attribution) passes; UI shows `Not available` for null and never "safe"; production build and strict type-check pass.
- **Exit:** DoD met; accessibility checks listed in TESTING_QA run or marked not run.
- **PR/merge:** M7a completes the backend on `backend`; after full backend acceptance (M1.1–M7a) the user opens the **single `backend` → `dev` integration PR** with the gates in GIT_WORKFLOW.md. M7b is developed on `frontend`; its integration into `dev` is an open decision (GIT_WORKFLOW.md).
- **Risks/assumptions:** M7b browser login depends on the shared throttle being available (C-06); unmeasured read-latency targets are not claimed. **Unresolved:** D09.

### M8 — End-to-end integration and analyst workflows

- **Objective:** the whole path from simulator event to reviewed incident works against the real stack. **Prerequisites:** backend integration PR merged into `dev`; M7b integrated into `dev`. Maps to Phase 6 tasks 2–4 and Phase 5 browser journeys.
- **Tasks and deliverables:** session-checked WebSocket `/stream` with bounded buffers and polling fallback; authenticated detailed dependency/model readiness and System page, added without changing the preserved M1 `/health` and `/api/v1/health` routes or their tests (C-07 deferred; the path comes from a separately approved compatibility plan); admin simulator page using ordinary endpoints with stable event IDs and visible partial failures; Playwright journeys in `tests/e2e/`.
- **Branch:** verified on `dev`; how M8 changes reach `dev` is an open decision in GIT_WORKFLOW.md.
- **Tests:** the six journeys in TESTING_QA.md; disconnect and reconnect refetch; expired session closes the socket; degraded Redis/STT/model-missing states shown truthfully; six core scenarios against the actual backend.
- **Acceptance (measurable):** all six journeys pass in a recorded run with exact commands; no duplicate rows after reconnect; degraded state visible when a dependency is stopped.
- **Exit:** DoD met; integration report per INTEGRATION_PLAN.md.
- **PR/merge:** per the GIT_WORKFLOW.md decision for post-integration work; `dev` must be green before M9.
- **Risks/assumptions:** browser tooling setup; WebSocket proxy behavior; the health-path compatibility plan is not yet written. **Unresolved:** C-07.

### M9 — Security, privacy and failure resilience

- **Objective:** find and fix security and privacy defects before measuring performance. **Prerequisites:** M8 green on `dev`. Maps to Phase 7 tasks 1 and 4.
- **Tasks and deliverables:** execute SECURITY_AUDIT.md, CODE_REVIEW.md and the abuse cases (cross-subscriber link, forged source, changed-payload duplicate, concurrent pair, review replay with altered note, stale overwrite, synthetic-only escalation, missing-signal zero fill, malicious audio reference); retention job verification including circular deferred FKs; log, DB, Redis and browser-storage privacy scan; failure drills (DB, Redis, model, worker kill); dependency advisory check; audit HMAC verification.
- **Branch:** findings fixed according to the post-integration workflow decision (GIT_WORKFLOW.md); the report on `dev`.
- **Tests:** regression test for every fix; privacy-leakage tests; overload rejection; restart behavior.
- **Acceptance (measurable):** no open critical or high finding; each fixed finding has a regression test; the report lists tests run and not run. A clean scan is not a security approval, and a pilot legal/privacy review is a separate gate.
- **Exit:** DoD met; residual risks documented.
- **PR/merge:** per the post-integration workflow decision; the user creates and merges any PRs.
- **Risks/assumptions:** HMAC audit detects modification, not deletion by a privileged operator; redaction is imperfect, so no "zero leakage" claim.

### M10 — Adversarial evaluation, ablation, calibration and performance benchmarks

- **Objective:** measured, reproducible claims or documented lack of them. **Prerequisites:** M9 closed; representative labeled data (D04). Maps to Phase 7 tasks 2–3.
- **Tasks and deliverables:** matched-population ablation across SMS-only, voice-only, rule fusion and learned fusion; calibration; speaker/campaign/language holdouts; blind adversarial cases (paraphrase, obfuscation, voice-only scams, benign IVR); stage and total latency, throughput, overload and failure behavior on named hardware, separating collection, admission, inference and total delay.
- **Branch:** `dev`, per the post-integration workflow decision (GIT_WORKFLOW.md); evaluation code under `experiments/`.
- **Tests:** deterministic seeds and manifests; no tuning on the held-out set.
- **Acceptance (measurable):** every reported rate has numerator and denominator, confidence interval and dataset provenance; untested groups are labeled; a failed improvement hypothesis is reported as failed.
- **Exit:** DoD met; the report states what is and is not demonstrated.
- **PR/merge:** `dev` PR; no accuracy claim enters README or UI beyond the report.
- **Risks/assumptions:** insufficient paired data; benchmark hardware differs from deployment.

### M11 — CI/CD, Docker deployment, release verification, demo readiness

- **Objective:** a clean checkout builds, tests, starts and demos reproducibly. **Prerequisites:** M10 report; D10 only for anything beyond local. Maps to Phase 8 and the final form of Phase 1 tasks 3–4.
- **Tasks and deliverables:** committed frontend lockfile (backend `uv.lock` and the pytest/Ruff workflow come from M1.1); extend GitHub Actions to frontend checks, integration tests and the release smoke test; Compose (reverse proxy, backend, PostgreSQL, Redis, static UI) with private data ports and read-only model mounts; migrations once before traffic; release candidate and tag; RELEASE_CHECKLIST.md execution; demo script.
- **Branch:** `dev` → `main` release PR.
- **Tests:** clean-clone install with `--locked`; full suites in CI; Compose smoke test with synthetic end-to-end flow; rollback rehearsal.
- **Acceptance (measurable):** CI green on the release commit; clean-clone smoke test succeeds with recorded commands; checklist items each marked pass/fail/not-run with evidence.
- **Exit:** owner approves release; the report states target as local demo, research host or authorized pilot, never implied beyond what was verified.
- **PR/merge:** `dev` → `main` merge commit after approval; tag only on approval.
- **Risks/assumptions:** deployment scope depends on D10; legal and privacy review for any pilot is outside engineering.

## Rollout principles

- Do not start a dependent milestone before the prior exit criteria hold or the owner explicitly accepts a scope reduction, recorded in the tracker.
- Contract changes (API, schema, policy values) update the source-of-truth document in the same PR as the code.
- Reports record exact commands and actual outcomes; unavailable checks are "not run" with the reason.
