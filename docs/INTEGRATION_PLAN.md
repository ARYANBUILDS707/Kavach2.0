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
| Backend ↔ frontend | M7 | Typed same-origin REST; wire fields snake_case; errors use the documented envelope |
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
5a. **Backend integration PR:** after M1.1–M7a pass acceptance testing on `backend`, the single `backend` → `dev` PR brings the complete backend into `dev` (gates in [GIT_WORKFLOW.md](GIT_WORKFLOW.md)). Steps 0–5 above happen on `backend`, not on `dev`.
6. **M8:** assemble the whole path from simulator to reviewed incident, add live updates and health, run browser journeys.
7. **M9–M11:** harden, measure, package.

The preserved M1 health routes (`/health`, `/api/v1/health`) and their tests must keep passing at every checkpoint (C-07 deferred). Backend milestones M1.1–M7a accumulate on `backend` and are checked by CI on every push; they reach `dev` through one integration PR after full backend acceptance, not per milestone. Frontend work stays on `frontend`; its integration timing is an open decision ([GIT_WORKFLOW.md](GIT_WORKFLOW.md)).

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

At the end of M3 and M6 (on `backend`), at the backend integration PR, and at the end of M8 and M11 (on `dev`), produce an integration report containing: branch and commit, services and versions, commands with outputs, scenarios exercised (benign OTP plus family call, phishing plus human scam caller, benign synthetic IVR, unrelated close-timed events, out-of-order delivery, missing signals), duplicate-submission behavior, and failures. Scenarios that could not run are "not run" with the reason.

## Failure handling to verify at each stage

- **Database down:** writes fail with 503, no success receipt.
- **Redis down:** correlation falls back to PostgreSQL; limits enforced conservatively or writes rejected; status degraded.
- **Model artifact missing or stage failing:** persisted explicit partial/unavailable result with reason; system status shows reduced capability; never a zero score.
- **Worker deadline exceeded:** worker terminated; nothing committed afterward; client retries with the same event ID.
- **Lost response:** same-ID retry returns the committed receipt with `replayed=true`.

## Not integrated

No live telecom feed, SIP, SMSC, external fraud provider, hosted LLM, webhook receiver, MCP server or external notification service is integrated in this plan. Adding any requires a separate authorization and a documented contract first.
