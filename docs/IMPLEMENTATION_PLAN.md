# KAVACH Implementation Plan

## Current authorized milestone

The user has explicitly started Phase A (repository foundation) and Phase B (backend foundation only). This authorizes the corresponding Python/FastAPI setup without waiting for unrelated D03–D10 decisions. It does not approve authentication implementation, database provisioning, model acquisition, Redis correlation or frontend work. The broader phases below remain the roadmap.

Foundation source, event schemas and pytest tests are written under `backend/`; root README contains setup and verification status. Status verified by the 31 October 2026 repository audit: the foundation is committed as `754a22a` on `main`, which is pushed to `origin`; `dev`, `backend` and `frontend` branches exist at the same commit locally and on `origin`; `pytest` reported 88 passed and Ruff check/format passed in the existing `backend/.venv` (Python 3.12). Still open: `backend/uv.lock` does not exist, installed Ruff is 0.17.3 against the 0.17.2 pin, and no CI is configured. These are tracked as technical debt in [MILESTONE_TRACKER.md](MILESTONE_TRACKER.md), not passed gates.

The M0–M11 milestone labels, their mapping to the phases below, and unresolved mapping conflicts are in [MASTER_DEVELOPMENT_PLAN.md](MASTER_DEVELOPMENT_PLAN.md). Branch and release procedure is in [GIT_WORKFLOW.md](GIT_WORKFLOW.md).

## Planning basis

Read [PRD.md](PRD.md), [DESIGN.md](DESIGN.md), [ARCHITECTURE.md](ARCHITECTURE.md), [DATABASE.md](DATABASE.md), [API.md](API.md) and [AGENTS.md](AGENTS.md). This is a development plan, not evidence that any phase has run. When this plan was first written the project contained only a connection-test file and these documents; the backend foundation described above was added afterward. This plan itself does not initialize code or infrastructure.

Each numbered task should be implemented and verified independently. Do not start a dependent phase before its completion criteria hold. Approval gates refer to pending PRD decisions, not repeated permission requests once the owner has approved them.

## Phase 0 — Resolve scope and evidence inputs

**Goal:** Make the proposed contracts implementable without invented product/model claims.

**Tasks:**

1. Record owner decisions D01–D03 and D09 for MVP scope, stack, authentication and UI.
2. Resolve D04 dataset provenance, license, language scope and artifact availability; record what remains experimental.
3. Resolve D05–D08 event-time, incident semantics, thresholds, retention and capacity defaults. Keep D10 pending until shared deployment is requested.
4. Verify cross-document consistency and create a small scenario/evaluation manifest separating demo fixtures from held-out data.

**Files/modules:** Core Markdown specifications; later `experiments/` and `data_schemas/` manifests.

**Dependencies:** Product owner; lawful data access and actual dataset/model availability.

**Database/API changes:** None; approve contracts before implementation.

**Tests:** Specification review; verify every field/role/endpoint maps to a user journey.

**Completion:** Relevant decisions recorded with date and rationale; unavailable models/datasets have an explicit blocker, not fabricated evidence.

## Phase 1 — Runnable foundations

**Goal:** Establish a minimal application that builds and starts.

**Tasks:**

1. Inspect the repository and preserve existing files; scaffold approved frontend/backend directories and lockfiles.
2. Add validated config, safe logging, error envelope, base routing and design tokens.
3. Add Compose PostgreSQL/Redis, backend and static frontend/proxy; expose only necessary local ports.
4. Add lint, formatting, type checks and test/build scripts; document startup/shutdown.

**Files/modules:** `frontend/`, `backend/core/`, `backend/api/`, `deployment/`, environment example, ignore files, manifests.

**Dependencies:** D01/D02/D09.

**Database/API changes:** Connectivity and `/health/live`; no feature schema or fake incident endpoints.

**Tests:** Frontend production build/type check; backend import/config/liveness test; Compose startup and missing-config failures.

**Completion:** Clean checkout starts; liveness returns real state; no default secrets; no business features fabricated.

## Phase 2 — Persistence and identity

**Goal:** Establish secure identities and durable constraints before exposing evidence.

**Tasks:**

1. Implement reviewed migrations and least-privilege database roles.
2. Implement provisioning, Argon2id hashing, sessions, CSRF and scoped ingestion keys.
3. Add login/session/logout and frontend protected routing.
4. Implement audit signing and transactional append; expiry jobs for sessions and evidence schema.

**Files/modules:** `backend/db/`, `backend/auth/`, `backend/privacy/`, `frontend/src/features/auth/`, migration tests.

**Dependencies:** Phase 1; D03/D07; approved secrets available outside Git.

**Database/API changes:** DATABASE.md tables/constraints; auth endpoints. Tables may be created together to support deferred FKs; domain behavior remains phased.

**Tests:** Fresh migration/upgrade; role matrix; session expiry/revocation; CSRF/Origin; audit rollback; database privilege tests.

**Completion:** Unauthorized users cannot read/write evidence; provisioned accounts work; no default passwords or browser-stored tokens.

## Phase 3 — Reproducible models and sanitized ingestion

**Goal:** Produce real independent signals and safe event receipts.

**Tasks:**

1. Prepare licensed dataset manifests and leakage-resistant splits; train/evaluate SMS TF-IDF logistic baseline.
2. Implement local audio decode/chunking, Whisper-tiny, semantic-intent and acoustic adapters with distinct outputs.
3. Produce checksummed manifests and baseline reports; define missing-model behavior.
4. Implement validated SMS/call ingestion, bounded inference deadline/admission, canonical HMAC idempotency and sanitized persistence.
5. Create standalone incidents and receipts; reject invalid paths, changed replay payloads and unbounded input.

**Files/modules:** `experiments/`, `backend/models/`, `backend/services/`, `backend/privacy/`, `backend/api/`, manifests and fixtures.

**Dependencies:** Phase 2; D04/D08; actual artifacts for full success, otherwise diagnostic unavailable behavior only.

**Database/API changes:** Populate events/standalone incidents/assessments; event POST and receipt GET endpoints.

**Tests:** Real small-model smoke test; privacy scans; duplicate/concurrent submissions; decoder bounds; timeout termination; metadata-only calls; database rollback.

**Completion:** Real artifacts generate versioned results or explicit partial/unavailable outputs; retry does not duplicate durable events. Model quality is reported separately from pipeline correctness.

## Phase 4 — Correlation and fusion

**Goal:** Connect plausible event pairs while preserving independent evidence.

**Tasks:**

1. Implement subscriber-scoped event-time candidate matching and Redis cache with authoritative PostgreSQL fallback.
2. Serialize concurrent same-subscriber commits; enforce unique pair incidents and membership constraints.
3. Train/test continuous fusion; version feature order, units, coefficients and calibration metadata.
4. Implement approved base-risk floor and tiers, structured reasons and immutable assessment snapshots.

**Files/modules:** `backend/correlation/`, `backend/policy/`, `backend/services/`, `experiments/`, database repositories/tests.

**Dependencies:** Phase 3 and D05/D06; paired labeled training/evaluation data.

**Database/API changes:** Pair incident/assessment persistence; extend receipt links and evidence DTOs, no unapproved schema additions.

**Tests:** Both arrival orders; concurrent SMS/call; exact time boundaries; late events; cross-subscriber rejection; brand-only/unrelated rejection; missing signals; cache loss; high standalone score after window expiry; borderline continuous-score candidates.

**Completion:** Eligible pairs are deterministic and unique; independent risk is preserved; held-out fusion results are reproducible and limitations reported.

## Phase 5 — Investigation and review

**Goal:** Let authorized analysts inspect and classify real evidence.

**Tasks:**

1. Implement incident list/detail and review-history APIs with cursor/filter validation.
2. Implement transactionally appended reviews with idempotency, expected-version checks and audit signing.
3. Build incident feed/detail and shared signal, timeline, risk, review and state components.
4. Implement role-aware controls and keyboard-friendly error/conflict handling.

**Files/modules:** `backend/api/`, `backend/services/`, `frontend/src/features/incidents/`, `frontend/src/components/`, browser tests.

**Dependencies:** Phase 4; DESIGN.md approved.

**Database/API changes:** Incident reads and review GET/POST; current/latest pointers updated transactionally.

**Tests:** Filter/pagination stability; concurrent review conflict; safe idempotent retry; viewer denial; assessment revision attribution; loading/empty/error/stale states; responsive and keyboard review flow.

**Completion:** An analyst can inspect evidence and persist a review; viewers cannot mutate; UI shows no fabricated scores or success.

## Phase 6 — Demo controls and operational visibility

**Goal:** Demonstrate reproducibly and surface degradation.

**Tasks:**

1. Add approved synthetic scenario catalog and admin-only simulator using ordinary ingestion endpoints.
2. Add authenticated detailed health and System screen.
3. Add session-checked WebSocket invalidations, bounded buffers, reconnect refetch and polling fallback.
4. Preserve event IDs across retry and expose partial scenario failures.

**Files/modules:** Simulator/system frontend features; API catalog/health/stream; integration/browser tests.

**Dependencies:** Phase 5; synthetic samples available and licensed.

**Database/API changes:** Catalog/health/WebSocket; no new business tables.

**Tests:** Admin-only simulator; disconnect recovery; expired socket session; degraded Redis/STT; model-missing startup; six core scenarios.

**Completion:** Demo runs against actual backend; unavailable capabilities remain visible and scoped.

## Phase 7 — Quality, security and empirical validation

**Goal:** Establish tested prototype behavior and honest performance claims.

**Tasks:**

1. Execute TESTING_QA.md, SECURITY_AUDIT.md and CODE_REVIEW.md against implementation.
2. Run matched-population ablation, calibration and language/speaker/campaign holdouts.
3. Measure stage timings, total alert delay, throughput, overload and cache/database failure behavior on named hardware.
4. Verify expiry deletion, secret/log hygiene and a backup restore; repair critical/high issues.

**Files/modules:** Tests, experiment reports, narrowly justified implementation fixes and updated contracts.

**Dependencies:** Phase 6; representative evaluation data and documented hardware.

**Database/API changes:** No new features; corrective migrations only if justified and approved.

**Tests:** Full critical suite plus adversarial/privacy/accessibility/load tests; measured metrics with denominators.

**Completion:** No critical/high findings; reproducible evidence distinguishes product correctness from model-quality limitations. Failed improvement hypothesis remains explicit.

## Phase 8 — Deployment and launch decision

**Goal:** Prepare the approved environment with recoverable operations.

**Tasks:**

1. Resolve D10 and any real-data policies before provisioning external resources.
2. Follow DEPLOYMENT.md: production build, migrations, TLS, secrets, private dependencies and smoke tests.
3. Follow MONITORING_MAINTENANCE.md: actionable alerts, retention, backups and restore evidence.
4. Execute FINAL_PRODUCTION_AUDIT.md with a verdict scoped to local demo, research host or authorized pilot.

**Files/modules:** `deployment/`, configuration, operational documentation, release report.

**Dependencies:** Phase 7, hosting authorization and required operational/legal reviews for a pilot.

**Database/API changes:** Apply approved migrations, verify dependency readiness; no new integrations by implication.

**Tests:** Production build, clean deployment, role checks, migrations, TLS, restore, secret/log inspection and synthetic end-to-end smoke.

**Completion:** Verified environment URL/status, owner and recovery procedure documented; unknowns listed as manual gates, not passed checks.

## Recommended first task

The backend part of Phase 1 is done. The next task is M2 (Phase 2: PostgreSQL, migrations, identity, scoped authentication, audit), which needs the prerequisites in [MASTER_DEVELOPMENT_PLAN.md](MASTER_DEVELOPMENT_PLAN.md): D02 package approval, D03, D07, and a PostgreSQL test setup. Establish D04 dataset and model provenance before claiming inference functionality. Do not assume the proposed architecture is approved beyond what the owner has recorded.
