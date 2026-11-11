# KAVACH Integration Plan

How independently built pieces connect, in what order, and how each connection is verified. Contracts are defined in [API.md](API.md) and [DATABASE.md](DATABASE.md); this document sequences their integration and does not change them. Milestones are in [MASTER_DEVELOPMENT_PLAN.md](MASTER_DEVELOPMENT_PLAN.md).

## Integration boundaries

| Boundary | First integrated | Rule |
| --- | --- | --- |
| API ↔ PostgreSQL | M2 | Repositories only; parameterized SQL; runtime role has no DDL; browser never connects |
| API ↔ auth | M2 | One dependency chain: credential type → active user/key → role/scope; mixed credentials rejected |
| Ingestion ↔ PostgreSQL | M3 | One transaction: idempotency recheck, event, standalone incident, assessment, audit |
| Ingestion ↔ Redis | M3 | Rate counters and post-commit candidate IDs (no matching logic until M6); Redis failure cannot roll back or fake a commit |
| Ingestion ↔ inference | M3 (port), M4/M5 (adapters) | Typed adapter result: score or `null`, status, reason code, version, duration; before models exist outputs are `null`, analysis is `unavailable`, tier `unknown`; models never inside request handlers |
| Correlation ↔ PostgreSQL/Redis | M6 | Redis accelerates lookup; the PostgreSQL query inside the subscriber advisory lock decides |
| Backend ↔ frontend | MVP-1 (M7 subset) | Typed same-origin REST; wire fields snake_case; errors use the documented envelope; development uses the Vite proxy on the `APP_ORIGIN` origin |
| Backend ↔ browser (live) | M8 | WebSocket carries incident IDs and versions only; REST refetch is the source of truth |
| Simulator ↔ ingestion | M3 (scenario catalog and submission script), M8 (UI) | Ordinary event endpoints only; no score injection |
| Everything ↔ deployment | M11 | Compose, migrations once before traffic, private data ports |

## Order of integration

0. **M1.1 (before M2):** lockfile, Ruff pin and minimal pytest + Ruff CI, so every backend push is checked automatically. Committed on `backend` (`c8c2ec7`); first CI run pending.
1. **M2:** schema and identity stand alone. Integrate by running migrations against the development/test-only PostgreSQL Compose configuration and exercising auth routes through the app factory. Password login ships only with shared throttling and fails closed if the shared throttle is unavailable (C-06); there is no in-process fallback for authentication.
2. **M3:** ingestion on top of M2. Verify the full write path with all model stages `unavailable`, then concurrency, replay, outage and rate-limit behavior.
3. **M4, M5:** each adapter replaces the unavailable stage behind the same port. Integration check: ingestion tests still pass unchanged; new behavior adds assertions, not exceptions.
4. **M6:** correlation reads M3 events and M4/M5 scores. Integration check: both arrival orders and concurrent submission produce exactly one pair incident.
5. **M7a then M7b:** API before UI. The UI is developed on `frontend` against real endpoints (or the OpenAPI schema), not hardcoded scores.
5a. **First integration: SMS MVP-1 (approved 9 Nov 2026, C-12; replaces the earlier single post-M7a backend PR as the first integration).** The accepted backend MVP (M1.1–M4-I.2 as already verified, plus the MVP-1 backend work: M4-Q decision, incident reads with the `channel` filter, the read limit, admin browser SMS submission and the frozen contract) and the accepted frontend MVP are integrated into `dev` after **joint acceptance** (checklist below). M5 and M6 are not prerequisites. Each branch reaches `dev` through its own owner-controlled PR; gates in [GIT_WORKFLOW.md](GIT_WORKFLOW.md). Steps 0–5 happen on `backend` and `frontend`, not on `dev`.
6. **M8:** assemble the whole path from simulator to reviewed incident, add live updates and health, run browser journeys.
7. **M9–M11:** harden, measure, package.

The preserved M1 health routes (`/health`, `/api/v1/health`) and their tests must keep passing at every checkpoint (C-07 deferred). Backend milestones accumulate on `backend` and frontend milestones on `frontend`, each checked by CI on every push; neither has a per-milestone PR into `dev`. After MVP-1, the postponed work (M5, M6, reviews, M7 advanced features, M8–M11) continues on `backend`/`frontend` and reaches `dev` through further owner-controlled PRs, each with its own acceptance evidence.

## SMS MVP-1 joint acceptance (gate for the first integration into `dev`)

Both branches must pass this together on their PR heads, run against a real backend, PostgreSQL and Redis, with exact commands and outcomes in an integration report ("not run" with a reason where something could not run):

1. **Backend checks:** default, integration (real PostgreSQL/Redis) and worker suites, Ruff lint/format, `uv lock --check` for each locked project, `alembic check`; CI green on the pushed commits.
2. **Frontend checks:** strict type-check, lint, Vitest, production build. The bundle contains no ingestion key, no test double and no fixture predictions.
3. **Contract:** frontend types match the committed backend OpenAPI snapshot and the MVP-1 section of API.md; every documented error envelope is exercised.
4. **Authentication:** login, idle and absolute expiry, logout revocation, inactive account refused, CSRF rejected without the header, wrong `Origin` rejected, mixed credentials rejected; login fails closed when Redis is down.
5. **Authorization:** viewer and analyst cannot reach `/analyze` and the server returns 403 for their submission; admin submits only `source=simulator`; missing and expired incidents return the same 404.
6. **Model state:** the UI shows the actual `GET /system/models` state. With the worker disabled (the MVP default until the M4-Q decision), submissions show the honest unavailable state. Only if the M4-Q rule enables the worker (C-12 D): a synthetic benign and a synthetic scam SMS submitted through the UI show the real native outputs from the pinned model, labelled uncalibrated, with tier `unknown` and null scores.
7. **Degraded paths** each show their documented state: worker disabled, starting (503), saturation (429 `CAPACITY_EXCEEDED`), inference timeout and worker crash (stored unavailable), Redis down (fail closed), PostgreSQL down (503), read limit (429).
8. **Idempotency:** same-ID retry returns 200 `replayed: true`; a changed payload under the same ID returns 409.
9. **Privacy:** no SMS text in browser storage, URLs, logs or any API response; authenticated responses send `no-store`.
10. **Accessibility:** keyboard focus order, visible focus, status conveyed by text and not colour alone.
11. **Preserved behavior:** every existing backend feature (key ingestion, simulator runner, operator CLI, retention, candidate index, M1 health routes) still passes its tests unchanged.

Accuracy is not part of this gate: no MVP-1 artifact may claim production accuracy, and the solo M4-Q result is reported only with its stated limits.

## Contract discipline

- The OpenAPI document is generated from implemented DTOs and compared to API.md at each milestone that adds routes; differences are fixed in code or in an approved documentation change.
- A contract change (field, status code, error code, table) is implemented together with its document update and the consumer change. Frontend work is not built on an unapproved shape.
- Schema changes need an Alembic migration and an approved contract change. Versioned HMAC keys, model manifests and policy versions are recorded with each stored result.

## Test environments

| Layer | Needs |
| --- | --- |
| Unit | No services; injected clock and model doubles (tests only) |
| Backend integration | Disposable PostgreSQL (M2) and Redis (M3); separate namespaces from development |
| Real-model smoke | Checksummed artifacts from M4/M5; separate from UI fixtures |
| Browser journeys | Real backend, PostgreSQL, Redis; synthetic data only |
| Release smoke | Compose from a clean checkout |

M2 may create a development/test-only PostgreSQL Compose configuration (approved under C-05; tooling and image choices still need D02 approval). Redis (or the approved shared store) joins the test setup in M2 for shared login throttling (C-06); other Redis use follows in M3. Until a real database is available, no integration test may be reported as passing.

## Integration checkpoints

At the end of M3 and M6 (on `backend`), at the MVP-1 joint acceptance, and at the end of M8 and M11 (on `dev`), produce an integration report containing: branch and commit, services and versions, commands with outputs, scenarios exercised (benign OTP plus family call, phishing plus human scam caller, benign synthetic IVR, unrelated close-timed events, out-of-order delivery, missing signals), duplicate-submission behavior, and failures. Scenarios that could not run are "not run" with the reason.

## Failure handling to verify at each stage

- **Database down:** writes fail with 503, no success receipt.
- **Redis down:** correlation falls back to PostgreSQL; limits enforced conservatively or writes rejected; status degraded.
- **Model artifact missing or stage failing:** persisted explicit partial/unavailable result with reason; system status shows reduced capability; never a zero score.
- **Worker deadline exceeded:** worker terminated; nothing committed afterward; client retries with the same event ID.
- **Lost response:** same-ID retry returns the committed receipt with `replayed=true`.

## Not integrated

No live telecom feed, SIP, SMSC, external fraud provider, hosted LLM, webhook receiver, MCP server or external notification service is integrated in this plan. Adding any requires a separate authorization and a documented contract first.
